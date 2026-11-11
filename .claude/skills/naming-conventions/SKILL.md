---
name: naming-conventions
description: Use when creating, renaming, or reviewing dbt models, sources, or columns to enforce EDM's model layer naming and folder structure. Applies to any dbt project that depends on the nyl_dbt_utils package.
metadata:
  dbt.managed_by: dbt
  dbt.source: package
  dbt.package: molly_snowflake_sandbox
  dbt.version: 87a42f82972885ba03e49cdaa1cf816a52c1764b
  dbt.source_path: skills/naming-conventions
  dbt.source_hash: sha256:d85886349aef45dfe5199c5332fe19eaf8e94dd9748630565fbb190919900673
  dbt.installed_at: 2026-11-10T23:08:58.230778787+00:00
---

# Model and file naming conventions

Consistent naming lets anyone predict a model's layer and purpose from its name alone.

## Layer prefixes

- **Staging** — `stg_<source>__<entity>.sql` (e.g. `stg_salesforce__accounts.sql`). One staging model per source table. Lives under `models/staging/<source>/`.
- **Intermediate** — `int_<entity>__<verb>.sql` (e.g. `int_orders__joined_to_customers.sql`). Describes a transformation step, not a final grain. Lives under `models/intermediate/`.
- **Marts** — `dim_<entity>.sql` / `fct_<entity>.sql` (e.g. `dim_customers.sql`, `fct_orders.sql`). Prefer `fct_` for event/transaction-grain tables and `dim_` for descriptive/slowly-changing entities. Lives under `models/marts/<domain>/`.
- **Quarantine generator outputs** — when using `nyl_dbt_utils.generate_quarantine_models`, keep the generated `<model>__flagged` / `<model>` / `<model>__quarantine` naming as-is; don't rename these three.

## General rules

- All identifiers (files, models, CTEs, columns) are `snake_case`, lowercase, no abbreviated cleverness (`cust` → `customer`).
- A model's filename **is** its model name — never rename one without the other.
- Foreign key columns end in `_id` and are named after the entity they reference, not the table (`customer_id`, not `cust_fk` or `id`).
- Boolean columns are prefixed `is_` / `has_` (`is_active`, `has_shipped`).
- Timestamp columns end in `_at` (`created_at`); date-only columns end in `_date` (`ordered_date`).
- Avoid reserved SQL words as column names.

## When reviewing or generating a model

1. Confirm the layer prefix matches what the model actually does (a staging model should not contain business-logic joins — that belongs in `int_`/marts).
2. Confirm the folder path matches the prefix's convention.
3. Flag any column that violates the `_id` / `is_`/`has_` / `_at`/`_date` rules above.
