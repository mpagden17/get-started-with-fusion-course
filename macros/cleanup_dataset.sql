{% macro cleanup_dataset(schemas=none, dry_run=True, max_drops=25) %}

    {#
        Drops tables/views in the given schema(s) that are NOT produced by this
        dbt project. Snowflake-only.

        ASSUMPTIONS — read before using:
          * This project EXCLUSIVELY owns the target schema(s). Anything else in
            them (other dbt projects, ELT landing tables, manual/ad-hoc objects)
            will be treated as droppable. Do NOT point this at a shared schema.
          * Default quoting (unquoted / UPPERCASE identifiers). Mixed-case or
            quoted identifiers will break the name matching.
          * External / materialized / dynamic tables are skipped by design.
          * Requires a seed `cleanup_dataset_exclusions` with column
            `table_name_to_keep` (an allow-list; may be header-only).

        ARGS:
          schemas   : list of schema names to clean. If omitted, defaults to
                      every schema this project's graph writes to.
          dry_run   : True (default) logs the drop statements without executing.
          max_drops : safety cap. If a non-dry run would drop more than this,
                      it aborts instead. Raise deliberately after reviewing.
    #}

    {% if not execute %}{% do return('') %}{% endif %}

    {# ---- 1. Map what THIS project builds: {DB: {SCHEMA: [TABLE, ...]}} ---- #}
    {% set graph_locations = {} %}
    {% for node in graph.nodes.values()
        | selectattr("resource_type", "in", ["model", "seed", "snapshot"]) %}
        {% set db  = node.database | upper %}
        {% set sch = node.schema  | upper %}
        {% if db not in graph_locations %}
            {% do graph_locations.update({db: {}}) %}
        {% endif %}
        {% if sch not in graph_locations[db] %}
            {% do graph_locations[db].update({sch: []}) %}
        {% endif %}
        {% do graph_locations[db][sch].append(
            (node.alias if node.alias else node.name) | upper) %}
    {% endfor %}

    {# ---- 2. GUARD: never touch a schema this project doesn't populate ---- #}
    {% if graph_locations | length == 0 %}
        {% do exceptions.raise_compiler_error(
            "cleanup_dataset aborted: the project graph resolved to zero models/"
            ~ "seeds/snapshots. Refusing to run to avoid dropping a whole schema.") %}
    {% endif %}

    {% set owned_schemas = [] %}
    {% for db in graph_locations %}
        {% for sch in graph_locations[db] %}
            {% do owned_schemas.append(sch) %}
        {% endfor %}
    {% endfor %}

    {% if schemas is not none %}
        {% for requested in schemas %}
            {% if (requested | upper) not in owned_schemas %}
                {% do exceptions.raise_compiler_error(
                    "cleanup_dataset aborted: requested schema '" ~ requested
                    ~ "' is not one this project builds into "
                    ~ "(project builds into: " ~ owned_schemas | join(", ") ~ "). "
                    ~ "This guard prevents cleaning a schema the project does not own.") %}
            {% endif %}
        {% endfor %}
    {% endif %}

    {# ---- 3. Exclusion allow-list (upper-cased) ---- #}
    {% set exclusion_list = dbt_utils.get_column_values(
        ref('cleanup_dataset_exclusions'), 'table_name_to_keep') %}
    {% set exclusions_upper = [] %}
    {% for e in exclusion_list %}
        {% do exclusions_upper.append(e | upper) %}
    {% endfor %}

    {# ---- 4. Build the orphan-detection query ---- #}
    {% set cleanup_query %}
        with models_to_drop as (
            {% for db in graph_locations.keys() %}
                {% if not loop.first %}union all{% endif %}
                select
                    table_catalog,
                    table_schema,
                    table_name,
                    case
                        when table_type = 'BASE TABLE' then 'table'
                        when table_type = 'VIEW'       then 'view'
                    end as relation_type
                from {{ db }}.INFORMATION_SCHEMA.TABLES
                where (
                    {% for sch, tables in graph_locations[db].items() %}
                        {% if schemas is none or (sch in (schemas | map('upper') | list)) %}
                            {% if not loop.first %}or{% endif %}
                            (
                                table_schema = '{{ sch }}'
                                and table_name not in ('{{ "', '".join(tables) }}')
                            )
                        {% endif %}
                    {% endfor %}
                )
                {% if exclusions_upper | length > 0 %}
                    and table_name not in ('{{ "', '".join(exclusions_upper) }}')
                {% endif %}
            {% endfor %}
        )
        select
            'drop ' || relation_type || ' "'
                || table_catalog || '"."'
                || table_schema  || '"."'
                || table_name    || '";' as command
        from models_to_drop
        where relation_type is not null
    {% endset %}

    {% set drop_commands = run_query(cleanup_query).columns[0].values() %}

    {# ---- 5. Blast-radius cap ---- #}
    {% if not (dry_run | as_bool) and drop_commands | length > max_drops %}
        {% do exceptions.raise_compiler_error(
            "cleanup_dataset aborted: " ~ drop_commands | length
            ~ " objects would be dropped, exceeding max_drops=" ~ max_drops
            ~ ". Re-run with dry_run=True to review, then raise max_drops if intended.") %}
    {% endif %}

    {# ---- 6. Execute or log ---- #}
    {% if drop_commands %}
        {% do log("cleanup_dataset: " ~ drop_commands | length
            ~ " orphan(s) found. dry_run=" ~ (dry_run | as_bool), True) %}
        {% for cmd in drop_commands %}
            {% do log(cmd, True) %}
            {% if not (dry_run | as_bool) %}
                {% do run_query(cmd) %}
            {% endif %}
        {% endfor %}
    {% else %}
        {% do log("cleanup_dataset: no orphaned relations found.", True) %}
    {% endif %}

{%- endmacro -%}
