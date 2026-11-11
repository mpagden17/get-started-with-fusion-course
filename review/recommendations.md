# Project review recommendations

## Review basis

Reviewed the local project on branch `mpagden17-patch-1`, including all SQL and YAML under `models/`, `dbt_project.yml`, package configuration and lockfile, the local currency macro, and relevant seed headers/sample rows. Findings describe the current working tree, including pre-existing uncommitted changes; they are not claims about the deployed production/staging environment.

There is no root-level `skills/` directory. The complete checklist was accessible under `dbt_packages/molly_snowflake_sandbox/skills/`, at the revision recorded in `package-lock.yml` (`87a42f82972885ba03e49cdaa1cf816a52c1764b`). All five files were read:

- `model-yml-requirements/SKILL.md`
- `naming-conventions/SKILL.md`
- `orphan-model-detection/SKILL.md`
- `source-and-ref-usage/SKILL.md`
- `testing-best-practices/SKILL.md`

The initially available `.agents/skills/` and `.claude/skills/` folders each contained an installed orphan-detection skill, which was also read. The package copies supplied the other four skills, including the referenced supporting guidance. Although their descriptions refer to `nyl_dbt_utils` (not declared by this project), their rules were applied as the requested review rubric. Naming differences are treated as convention gaps, not execution failures.

Validation: a project-scoped `dbt ls --select package:jaffle_shop_17 --output json` completed successfully using dbt v2 Stable 2.0.11. This verifies resource discovery/parsing for that invocation, not SQL execution or passing tests. No build, data tests, unit tests, source freshness checks, or warehouse profiling were run. No reviewed model/configuration file was edited. The dbt invocation automatically refreshed package-managed installed skill copies and generated artifacts; those CLI side effects are distinct from review fixes.

## Must Fix

The testing skill explicitly classifies a model with zero tests as Must Fix. Upstream staging tests do not test the materialized mart itself.

### MF-01 — Untested and undeclared locations mart

- **File:** `models/marts/locations.sql`; missing model entry in `models/marts/*.yml`.
- **Issue:** The mart has no YAML declaration, model description, or attached data tests. Its output grain is one row per `location_id`.
- **Suggested fix:** Add a `locations` entry to the marts YAML documentation with a meaningful description and `unique` + `not_null` tests on `location_id`. Document the tax rate and opening date. Build/test the mart after adding coverage.
- **Skill basis:** `model-yml-requirements`, `testing-best-practices`.

### MF-02 — Untested and undeclared products mart

- **File:** `models/marts/products.sql`; missing model entry in `models/marts/*.yml`.
- **Issue:** No YAML declaration or tests protect the one-row-per-`product_id` mart.
- **Suggested fix:** Declare the model and add `unique` + `not_null` on `product_id`. Document price units, product type, and classification flags; add domain checks after confirming allowed values.
- **Skill basis:** `model-yml-requirements`, `testing-best-practices`.

### MF-03 — Untested and undeclared supplies mart

- **File:** `models/marts/supplies.sql`; missing model entry in `models/marts/*.yml`.
- **Issue:** No YAML declaration or tests protect the mart. The upstream key is `supply_uuid`; `supply_id` alone is explicitly not the documented grain.
- **Suggested fix:** Document the intended grain and add `unique` + `not_null` on `supply_uuid`. Include a product relationship test and document cost semantics. Reconcile the upstream historical-cost description with the key design before relying on this for historical costs (see R-09).
- **Skill basis:** `model-yml-requirements`, `testing-best-practices`.

### MF-04 — Untested and undeclared daily sales mart

- **File:** `models/marts/daily_sales_broken.sql`; missing model entry in `models/marts/*.yml`.
- **Issue:** An enabled daily product rollup has no documentation or tests. Neither its grain nor revenue/count logic is independently protected. The filename alone is not evidence of a runtime failure.
- **Suggested fix:** Declare its purpose and establish the intended grain. The current SQL groups by `order_date`, `product_id`, and `product_name`; confirm whether `(order_date, product_id)` is the business key. Add `dbt_utils.unique_combination_of_columns` for the confirmed key, `not_null` on its components, and a product relationship test. Add fixture-based checks for daily revenue, item count, and ranking.
- **Skill basis:** `model-yml-requirements`, `testing-best-practices`.

## Recommended

### R-01 — Missing foreign-key relationship coverage

- **Files:** `models/staging/stg_orders.yml`, `models/staging/stg_order_items.yml`, `models/staging/stg_supplies.yml`, `models/marts/orders.yml`, `models/marts/order_items.yml`.
- **Issue:** Several foreign keys used by downstream joins are not covered: staging orders' `customer_id` and `location_id`; staging order items' `product_id`; staging supplies' `product_id`; mart orders' `location_id`; and mart order items' `product_id`. Existing order/customer relationship tests cover only part of this graph. Left joins can preserve unmatched rows with null enrichment values.
- **Suggested fix:** Add relationship tests to the appropriate `stg_customers`, `stg_locations`, and `stg_products` keys, following existing conventions. Add `not_null` where the relationship is mandatory because relationship tests alone do not reject null foreign keys. Do not treat repeated `supply_id` as a unique parent key without confirming its business meaning.
- **Skill basis:** `model-yml-requirements`, `testing-best-practices`.

### R-02 — Customer column documentation does not match SQL

- **Files:** `models/marts/customers.yml`, `models/marts/customers.sql`.
- **Issue:** YAML documents `first_ordered_at` and `last_ordered_at`, while SQL returns `first_order_date` and `last_order_date`. Descriptions incorrectly call these timestamps. The `customer_id` description also calls it the key of the orders mart.
- **Suggested fix:** Update YAML to describe the existing date columns and correct the customer-key description. Keep the SQL column names unless a separately planned consumer migration requires renaming them. This is stale column documentation, not an orphaned model.
- **Skill basis:** `model-yml-requirements`, `orphan-model-detection`, `naming-conventions`.

### R-03 — Missing descriptions for model purpose and derived columns

- **Files:** `models/marts/order_items.yml`; the six `models/staging/stg_*.yml` files; `models/marts/orders.yml`, `models/marts/customers.yml`.
- **Issue:** `order_items` has no model-level description, and many calculated fields have no column documentation: converted currency and original cents, `gross_revenue`, product classification flags, `supply_cost`, `customer_order_number`, and derived item counts. Existing YAML does not fully communicate these semantics.
- **Suggested fix:** Document each model's grain and the non-obvious output columns in standard dbt YAML. State currency units, tax inclusion, null behavior, and ordering rules. Retain the established per-model YAML layout; consolidating files is not necessary for coverage.
- **Skill basis:** `model-yml-requirements`.

### R-04 — Model names and folders differ from the requested conventions

- **Files:** all six `models/staging/stg_*.sql` files and all seven `models/marts/*.sql` files, with their YAML and exposure references.
- **Issue:** The skill expects `stg_<source>__<entity>` under a source subfolder and `dim_`/`fct_` marts under domain subfolders. Current staging names omit the source, and mart names omit layer prefixes. `daily_sales_broken` also encodes a temporary status rather than its business purpose.
- **Suggested fix:** Either document an approved sandbox exception or plan a coordinated naming migration, for example `stg_ecom__orders`, `dim_customers`, and `fct_orders`. Classify supply and daily-sales grains before choosing names. Update refs, YAML, exposures, selectors, and external consumers together; preserve compatibility where needed. Do not rename models as an isolated cleanup.
- **Skill basis:** `naming-conventions`.

### R-05 — Six local source declarations appear unused

- **Files:** `models/staging/__sources.yml`; all six `models/staging/stg_*.sql` files.
- **Issue:** All six `ecom.raw_*` declarations have no active `source()` caller in local model SQL. Staging reads the corresponding dbt seeds with `ref()`. The apparent source calls in comments are inside Jinja comments and do not create dependencies.
- **Suggested fix:** Decide whether this is intentionally a seed-backed tutorial. If so, remove unused source declarations or clearly document them as optional examples after checking package/dynamic consumers. If moving to externally loaded data, wire staging to the declared sources and update unit-test inputs and ingestion configuration together. Do not replace valid seed refs merely to satisfy a source-only staging convention.
- **Verification limit:** Local SQL and the local macro were inspected; package-wide dynamically constructed source names and external consumers were not exhaustively verified. These declarations therefore *appear* orphaned, not proven safe to delete.
- **Skill basis:** `orphan-model-detection`, `source-and-ref-usage`.

### R-06 — Terminal mart consumers need documentation

- **Files:** `models/exposures/weekly_jaffle_metrics.yml`; `models/marts/locations.sql`, `products.sql`, `supplies.sql`, `daily_sales_broken.sql`.
- **Issue:** These four terminal marts have no local downstream model consumers or exposure dependencies. The existing exposure directly declares `orders` and `customers`. Terminal marts are allowed to end the DAG; this does not establish that they are unused. The dashboard URL is also an example URL and its description does not explain its purpose.
- **Suggested fix:** Confirm consumers with the owner and add accurate exposures where BI/report consumers exist. Replace the example URL and describe the dashboard's business purpose. Only consider retirement after confirming actual usage; do not delete terminal marts based on missing refs.
- **Skill basis:** `orphan-model-detection`.

### R-07 — Product categories and flags lack domain checks

- **Files:** `models/staging/stg_products.yml`, `models/staging/stg_supplies.yml`, `models/marts/orders.yml`.
- **Issue:** `product_type`, food/drink classification flags, `is_perishable_supply`, and order food/drink flags lack accepted-value coverage. A new product type would silently classify as neither food nor drink under the current expressions. The existing `customer_type` accepted-values test is a useful pattern.
- **Suggested fix:** Confirm the supported product taxonomy, add `accepted_values` for enum/boolean fields, and add null checks where flags must be populated. Add a unit test for unknown and null product types so the desired behavior is explicit.
- **Skill basis:** `testing-best-practices`.

### R-08 — Gross revenue expression needs explicit unit handling

- **Files:** `models/staging/stg_orders.sql`, `models/staging/stg_orders.yml`; context: `seeds/raw_orders.csv`, `macros/cents_to_dollars.sql`.
- **Issue:** The input has cent-valued columns named `subtotal` and `tax_paid`, and the SELECT reuses those names for dollar-valued aliases. `gross_revenue` then uses unqualified `(subtotal + tax_paid)` in the same SELECT. This creates a source-column/alias collision and a risk of cent-valued revenue beside dollar-valued totals. No dedicated assertion covers `gross_revenue`.
- **Suggested fix:** Define the intended unit and tax semantics, then compute revenue explicitly from converted values in a subsequent CTE or explicitly convert the raw sum. Add an assertion against the expected dollar total and a fixture with known cents. Confirm Snowflake output before treating the metric as reliable.
- **Verification limit:** The naming collision and seed units were verified statically; actual warehouse output was not queried.
- **Skill basis:** `model-yml-requirements`, `testing-best-practices`; supplemental SQL review.

### R-09 — Historical supply-cost description exceeds the implemented key/selection logic

- **Files:** `models/staging/stg_supplies.yml`, `models/staging/stg_supplies.sql`, `models/marts/order_items.sql`; context: `seeds/raw_supplies.csv`.
- **Issue:** Documentation says cost changes receive new UUIDs, but the surrogate key uses only `id` and `sku`. If the same pair receives another cost, it receives the same key. The mart also sums all supply rows per product with no effective-date selection. That is valid for distinct recipe components but would overcount if rows represent successive historical prices. The seed header has no effective-date field.
- **Suggested fix:** Confirm whether rows represent recipe components or cost history. For components, correct the documentation. For historical costs, introduce a version/effective-period key upstream and select the cost valid on the order date before aggregation. Add tests for the chosen grain and repeat cost versions. Do not simply add cost to the key and continue summing every historical version.
- **Verification limit:** No duplicate-key or historical-overcount failure was demonstrated in warehouse data.
- **Skill basis:** `model-yml-requirements`, `testing-best-practices`; supplemental grain review.

### R-10 — Order numbering is reverse chronological and nondeterministic on ties

- **Files:** `models/marts/orders.sql`, `models/marts/orders.yml`; related: `models/marts/daily_sales_broken.sql`.
- **Issue:** `customer_order_number` orders by date descending, so 1 identifies a latest order rather than a first order. Same-day orders have no tie-breaker because staging retains only the date. The daily leaderboard likewise has no tie-breaker for equal revenue. Intended business semantics are undocumented.
- **Suggested fix:** Confirm whether numbering means first-to-latest or recency rank; document it and choose a clear name/order. Add a stable tie-breaker such as `order_id`, preserving the original order timestamp if real chronology is required. For daily ranking, decide between a deterministic unique position and tied business ranks. Add same-day/equal-revenue unit fixtures.
- **Skill basis:** `model-yml-requirements`, `testing-best-practices`; supplemental SQL review.

### R-11 — Placeholder columns and copied unit-test description

- **Files:** `models/marts/customers.sql`, `models/marts/order_items.sql`, `models/marts/order_items.yml`.
- **Issue:** Published marts include constant placeholder columns (`test_column = 'testing'` and `testing = 'test column'`). The supply-cost unit test's description describes food/drink booleans instead of supply aggregation.
- **Suggested fix:** Confirm whether the placeholder columns have consumers, then remove them through the appropriate compatibility process or document their deliberate purpose. Update the test description to match its aggregation fixture. Preserve the useful aggregation test.
- **Skill basis:** `model-yml-requirements`, `testing-best-practices`.

## Notes

### N-01 — No local staging/intermediate model orphan found

- **Files:** `models/staging/stg_*.sql`, `models/marts/*.sql`.
- **Observation:** Every staging model has an active model consumer: customers → customers; locations → locations; order items → order_items; orders → orders/order_items; products → products/order_items; supplies → supplies/order_items. No local intermediate layer is present. All existing local YAML model entries match SQL model names; the four SQL-without-YAML cases are listed under Must Fix.
- **Suggested action:** Retain these staging models; continue checking consumers when changing the DAG. Package-level orphan analysis was not exhaustive.

### N-02 — Seed refs and CTE references are appropriate

- **Files:** `models/staging/stg_*.sql`, `models/marts/*.sql`, `seeds/raw_*.csv`.
- **Observation:** Local models use dbt refs for dbt-built inputs; no hardcoded warehouse relation was found. Bare FROM/JOIN names in these models refer to local CTEs, not undeclared external tables. The source-only staging rule needs a seed-backed sandbox exception.
- **Suggested action:** Keep refs while seeds remain authoritative. Use sources when inputs are externally ingested, as described in R-05.

### N-03 — Freshness cannot be prescribed from event timestamps alone

- **File:** `models/staging/__sources.yml`.
- **Issue/limitation:** `raw_orders` declares `ordered_at` and `raw_stores` declares `opened_at` as loaded-at fields, with no freshness thresholds. These represent business events, not verified ingestion times; an old store opening does not imply stale ingestion. Sources are currently unused locally.
- **Suggested fix:** If activating external sources, confirm a reliable ingestion/load timestamp and business SLA before adding warning/error thresholds. For intentional static seed fixtures, document that automated source freshness is not applicable. No reliable load timestamp or freshness SLA was verified.

### N-04 — Package warnings require owner follow-up, not vendor-file edits

- **Files:** `packages.yml`, `package-lock.yml`; installed dependency `dbt_packages/molly_snowflake_sandbox/`.
- **Issue:** Resource listing emitted `SemanticModelDeprecated` for legacy semantic YAML in `molly_snowflake_sandbox` and `UnsupportedConstraintMaterialization` for constraints ignored on views. These warnings did not fail listing. The precise originating constraint file was not identified, and cached parsing may suppress additional warnings.
- **Suggested fix:** Investigate with a fresh `--no-partial-parse` invocation in a separate remediation task; migrate the dependency in its owning repository and consume a validated revision. Review the originating view constraint and use enforceable tests/materialization where appropriate. Do not patch `dbt_packages/`. This review neither migrated semantic YAML nor verified package runtime compatibility.

### N-05 — Runtime and external usage remain unverified

- **Files:** all reviewed `models/` SQL/YAML; `.github/workflows/`, `scripts/`.
- **Issue/limitation:** This is a source review, not a passing-build certification. Data distributions, null/duplicate rates, actual unit-test results, external BI consumers, dashboard URLs, credentials, GitHub protection rules, and production behavior were not verified. Workflow/script files were inspected for context but were not executed or comprehensively audited against a separate automation/security rubric. No model is labeled broken solely because its filename says so.
- **Suggested fix:** After approved changes, run the relevant dependency-slice builds and tests in development and compare output-affecting changes with production. Verify external consumers and deployment protections with owners. Keep all findings requiring business confirmation conditional until verified.

### N-06 — Existing working-tree changes were preserved

- **Files:** `dbt_project.yml`, `packages.yml`, `package-lock.yml`, `.claude/skills/orphan-model-detection/SKILL.md`; package-managed installed skill folders.
- **Observation:** The branch had uncommitted changes before the review. No fixes were applied to the reviewed SQL/YAML/configuration. The resource-listing command automatically installed/refreshed the package's skills under `.agents/skills/` and `.claude/skills/` and generated normal dbt artifacts.
- **Suggested action:** Review the working-tree diff before committing and keep the requested report separate from pre-existing edits and package-managed installation side effects. No skill was inaccessible after locating the package's `skills/` directory; runtime and external verification limits are stated above.
