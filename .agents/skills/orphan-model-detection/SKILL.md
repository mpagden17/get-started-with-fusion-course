---
name: orphan-model-detection
description: Use when adding or reviewing models to find orphan models — staging/intermediate models with no downstream consumer — versus marts/exposures, which are expected to be unreferenced by other dbt models. Applies to any dbt project that depends on the nyl_dbt_utils package.
metadata:
  dbt.managed_by: dbt
  dbt.source: package
  dbt.package: molly_snowflake_sandbox
  dbt.version: 87a42f82972885ba03e49cdaa1cf816a52c1764b
  dbt.source_path: skills/orphan-model-detection
  dbt.source_hash: sha256:a59a77bcd964b7311f7de1d9706e9cb834d42fda16c5207cea2ff946cc0c33f4
  dbt.installed_at: 2026-11-06T19:55:47.646548273+00:00
---

# Find orphan models — but know which layer is allowed to be one

An "orphan" model is one nothing consumes. Whether that's a problem depends entirely on the model's layer — a terminal mart with no dbt-level consumer is normal; a staging model with no consumer is dead weight.

## Rules

- **Staging models must have at least one downstream consumer.** Per [[naming-conventions]], a `stg_` model exists only to feed `int_`/`dim_`/`fct_` models. If no other model's SQL contains `{{ ref('stg_<x>') }}`, that staging model is a true orphan: either dead code left over from a removed feature, or a model that was scaffolded but never wired into anything. Flag it for removal or follow-up — don't assume it's fine because it compiles and has tests.
- **Intermediate models must have at least one downstream consumer**, same logic — an `int_` model with zero `ref()` callers isn't doing any transformation work for anyone.
- **Marts (`dim_`/`fct_`) are expected to be unreferenced by other dbt models.** They're the terminal layer — BI tools, reports, and reverse-ETL query them directly, outside the dbt DAG. Zero in-project `ref()` callers is normal here, not a defect. Don't flag a mart as orphaned just because nothing in `models/` refs it.
- **Cross-check marts against `exposures:` where they exist.** If the project declares `exposures:` (dashboards, reports consuming marts), a mart with no downstream `ref()` *and* no exposure entry is worth a second look — it may genuinely be unused, or the exposure simply hasn't been documented yet. Treat a missing exposure as a prompt to ask, not as proof the model is dead.
- **A source declared in a `.yml` but never called via `{{ source(...) }}` anywhere is also an orphan** — a stale source declaration with no staging model consuming it. See [[model-yml-requirements]].
- **A `.yml` model entry with no matching `.sql` file** (or vice versa) is a stale-docs orphan, not a dead-model orphan — flag it as a doc cleanup, distinct from the cases above.

## When reviewing for orphan models

1. For each `stg_`/`int_` model, grep the project for `ref('<model_name>')`. Zero matches → flag as orphan, layer-appropriate severity (staging/intermediate orphans are a real finding, not cosmetic).
2. For each `dim_`/`fct_` model, grep for `ref('<model_name>')` too, but don't flag a zero-match result on its own — check whether an `exposures:` block references it first. Only raise it as a question if neither exists.
3. For each declared `source()` table, grep for `source('<source_name>', '<table_name>')` usage. Zero matches → flag the source declaration as orphaned.
4. Cross-reference `.yml` model/source entries against actual `.sql` files in the same folder (and vice versa) — mismatches are a documentation orphan, call it out separately from unused-model findings.
5. Before recommending deletion of anything, confirm it isn't referenced via `{{ ref(...) }}` with a variable/macro-constructed name (rare, but grep-based checks can miss it) — flag as "appears orphaned, verify manually" rather than asserting dead code with certainty.
