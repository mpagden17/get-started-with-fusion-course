---
name: source-and-ref-usage
description: Use when writing or reviewing dbt model SQL to ensure it references upstream data via source() and ref() instead of hardcoded database.schema.table names. Applies to any dbt project that depends on the nyl_dbt_utils package.
metadata:
  dbt.managed_by: dbt
  dbt.source: package
  dbt.package: molly_snowflake_sandbox
  dbt.version: 87a42f82972885ba03e49cdaa1cf816a52c1764b
  dbt.source_path: skills/source-and-ref-usage
  dbt.source_hash: sha256:4494b058b059090e70a04e2c904df571bd4c739fa5d651a8110a2e970f7c5b7d
  dbt.installed_at: 2026-11-06T19:55:47.645114321+00:00
---

# Always use source() and ref(), never hardcoded table names

A dbt model must never contain a literal `database.schema.table` reference. Every upstream dependency is resolved through `{{ source(...) }}` or `{{ ref(...) }}` so dbt can build the DAG, apply environment-specific database/schema names, and run tests in the right order.

## Rules

- **Raw/external data** (landed by an ingestion tool, not built by dbt) → `{{ source('source_name', 'table_name') }}`. The `source_name`/`table_name` pair must be declared in a `sources:` block in a `.yml` file in the same folder.
- **Any dbt-built model** (staging, intermediate, mart, or a `generate_quarantine_models` output) → `{{ ref('model_name') }}`. Never `ref()` a source, and never `source()` something dbt itself built.
- Never write a bare table name, a fully qualified `catalog.schema.table` string, or an f-string/concatenated identifier in a `from`/`join` clause of a model — this breaks dbt's dependency graph (no lineage, no correct build order, `dbt build --select` can't find it).
- The one sanctioned exception is inside `nyl_dbt_utils.generate_quarantine_models` args (`ref_model` / `source_name`+`source_table`), which the macro itself turns into proper `ref()`/`source()` calls in the generated SQL — don't hand-edit those generated calls into raw table names either.
- Staging models select from exactly one `source()`; everything downstream of staging uses `ref()` only.

## When reviewing a model

1. Grep the model's `from`/`join` clauses for anything that isn't `{{ ref(...) }}` or `{{ source(...) }}`.
2. If a `source()` is used, confirm it's declared in that folder's `.yml` — see [[model-yml-requirements]].
3. If a raw table name is found, replace it with the correct `ref()`/`source()` call and add the missing source declaration if needed.
