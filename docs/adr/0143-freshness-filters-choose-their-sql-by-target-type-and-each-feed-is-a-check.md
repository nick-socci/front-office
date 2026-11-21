# 0143. Freshness filters choose their SQL by target type, and each feed is a check

- Status: accepted
- Date: 2026-11-20
- Spec: [0219-alert-on-the-daily-run](../specs/0219-alert-on-the-daily-run/design.md) · Issue: #219
- Amends: [0050](0050-freshness-is-declared-once-per-feed-over-the-same-relation.md)

## Context

ADR 0050 declares freshness once per feed, with a filter in DuckDB SQL, "to be rewritten … for
BigQuery". dbt makes no project macro available in source YAML, so no `fo_*` macro can be used
there. Spec 0217 (R3.5) therefore left `source_freshness` out of the BigQuery `daily`, and the
production run builds BigQuery (ADR 0123). `target` does render in that YAML, in
`loaded_at_field` and in `freshness.filter` (C10), and the BigQuery form runs through dbt (C11)
with the DuckDB form unchanged (C12). `dbt source freshness` exits 0 at warn (C9), so the asset's
exit code alone hides a feed under seven days stale.

## Decision drivers

- One declaration per feed (ADR 0050), and one set of thresholds.
- Freshness runs where production runs, and a stale feed reaches the alert (ADR 0140).

## Considered options

1. **Branch on `target.type` in the YAML**: `parse_timestamp('%Y%m%dT%H%M%SZ', fetched_at)` and
   `json_value` on BigQuery, the current SQL on DuckDB. `source_freshness` reads `sources.json`
   and emits one check per feed, and runs in `daily` on both warehouses.
2. **Freshness as a model or singular test** of feed ages through the `fo_*` macros, replacing
   dbt's freshness.
3. **Two source files**, one enabled per target.

## Decision

Chosen by the owner on 2026-11-20: **option 1**, as recommended. Option 2 throws away ADR 0050's declarations and dbt's own freshness
for portability that one `if` gives. Option 3 duplicates every threshold, and the copies drift.

## Consequences

- Good: the stale-feed alert works on BigQuery. A feed's status and age are a check with
  metadata, readable without parsing logs.
- Bad / accepted cost: the YAML holds two dialects side by side. `test_dbt_portable_sql_rule.py`
  does not read it, so a parse test per target holds the branch instead.
- Follow-ups: ADR 0050's status reads "amended by 0143"; AGENTS.md's freshness sentence changes.
