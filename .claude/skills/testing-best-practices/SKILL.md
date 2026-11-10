---
name: testing-best-practices
description: Use when adding or reviewing dbt tests (schema tests, singular tests, incremental dedup safety, source freshness) to ensure adequate, non-cosmetic test coverage — especially on regulatory/compliance-facing marts and incremental models. Applies to any dbt project that depends on the nyl_dbt_utils package.
metadata:
  dbt.managed_by: dbt
  dbt.source: package
  dbt.package: molly_snowflake_sandbox
  dbt.version: 87a42f82972885ba03e49cdaa1cf816a52c1764b
  dbt.source_path: skills/testing-best-practices
  dbt.source_hash: sha256:6b61591703b0cd6f7f5b520edf0b3dccaf52f262408256db12b459cbf87cc81e
  dbt.installed_at: 2026-11-06T19:55:47.645355166+00:00
---

# Every model needs real, non-cosmetic test coverage

A model without tests is unverified, not "done." Test coverage isn't a documentation nicety — it's the only thing that catches a broken join, a duplicated row, or a silently-failed incremental run before it reaches a report.

## Rules

- **Every model's grain has a `unique` + `not_null` test.** This is non-negotiable and is the single highest-leverage test in any project — see [[model-yml-requirements]] for the `.yml` scaffold. A model with zero tests is a Must-Fix, not a "nice to have."
- **Incremental models need a real dedup safety net.**
  - Prefer `incremental_strategy: merge` (or `delete+insert`) with a declared `unique_key` over the grain — this makes reprocessing idempotent by construction.
  - If a model uses `incremental_strategy: append` driven by an external watermark (e.g. a separate batch-key/log table updated in a `post_hook`), treat this as fragile: the watermark advance and the row write are two separate statements, so a failed/retried run between them silently duplicates rows. Flag this pattern regardless of table size or history of "working fine" — the failure mode is `Must Fix` in a compliance report.
  - Add a `unique` test on the grain key even when the strategy is `merge` — the test catches upstream duplicates that `merge` alone would silently overwrite-and-hide.
- **Regulatory/compliance-facing domains get the strictest bar, not the same bar as everything else.** Marts feeding regulatory reporting (e.g. suitability, Reg BI, statutory filings) or financial reconciliation must have grain tests and FK `relationships` tests before merge — missing tests here outrank every other finding in a review.
- **Foreign keys get `relationships` tests** back to the parent model/source — not just a `not_null`, which only proves the value exists, not that it's valid.
- **Enum-like / status / flag columns get `accepted_values` tests** so an unexpected new value fails loudly instead of silently flowing downstream as an unhandled case.
- **Sources with a reliable load timestamp get a `freshness:` block** (`loaded_at_field` + `warn_after`/`error_after`) — a pipeline that silently stops loading is worse than one that fails loudly.
- **`severity: warn` is a temporary state, not a way to permanently silence a failing test.** If a test is downgraded to `warn`, it should have a tracked follow-up to fix the underlying data or upgrade it back to `error` — don't let `warn` become the permanent resting state for a known-broken assumption.
- **A passing test suite with near-zero real coverage is worse than an honestly small one.** Don't count boilerplate or copy-pasted tests as coverage — a `unique` test on the wrong column, or a test file that exists but tests nothing meaningful, should be flagged the same as a missing test.

## When adding or reviewing a model's tests

1. Confirm the model's grain (primary key, or composite key via `dbt_utils.unique_combination_of_columns`) has `unique` + `not_null`. If it doesn't, this is the first thing to fix — before anything else.
2. If the model is `incremental`, check `incremental_strategy`:
   - `merge`/`delete+insert` with `unique_key` set → confirm a `unique` test still exists on that key.
   - `append` (or any strategy without a `unique_key`) → check whether it's fed by an external watermark mechanism. If so, call out the duplicate-row risk explicitly and recommend either switching to `merge` with a real `unique_key`, or making the watermark update transactional with the write, in addition to adding the `unique` test.
3. If the model sits under a regulatory, compliance, or financial-reporting domain, apply the strictest bar: missing grain tests or FK tests here are `Must Fix`, never `Recommended`.
4. Check every `_id`-suffixed FK column for a `relationships` test back to its parent — see [[naming-conventions]] for the suffix convention and [[source-and-ref-usage]] for how the parent is referenced.
5. Check enum/status/flag columns for `accepted_values`.
6. Check any source with a load timestamp for a `freshness:` block.
7. Grep for `severity: warn` — for each one, confirm there's a known reason and a follow-up, not a silent permanent downgrade.
8. Never sign off on a model with zero tests, and don't count boilerplate tests (wrong column, no-op assertions) toward coverage.
