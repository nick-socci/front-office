# 0105. The BigQuery selector builds every model and is renamed `bigquery`

- Status: accepted; amends [0096](0096-every-sql-model-is-written-for-both-warehouses-and-bigquery-builds-all-but-the-solver-and-its-readers.md)
- Date: 2026-10-26
- Spec: [0137-lineup-solver-on-bigquery](../specs/0137-lineup-solver-on-bigquery/design.md) · Issue: #137

## Context

ADR 0096 made `bigquery_slice` "every model except the solver and its descendants". It
left the rename to `bigquery` to #137, "when the exclusion is gone". With ADR 0103 the
solver runs on BigQuery, so the exclusion goes. What stays excluded is one test,
`stg_raw__capture_views_cover_the_manifest`, which checks DuckDB's capture glob and has
nothing to check on BigQuery. The selector's name appears in AGENTS.md, README,
`dbt/selectors.yml`, three tests and `scripts/compare_bigquery_slice.py` (ADR 0096), and
in the commands of earlier specs, which are records and are not edited.

## Decision drivers

- The name says what the selector is.
- Little churn in files the decision doesn't otherwise change.
- Earlier specs' commands stay readable as history.

## Considered options

1. **Rename to `bigquery`**, with the script (`compare_bigquery.py`) and its test.
2. **Keep `bigquery_slice`**, and drop only the exclusion.

## Decision

Chosen by the owner on 2026-10-26, going through the spec's decisions, as recommended:
**option 1**. Once nothing but a DuckDB-only test is left out, "slice" is wrong, and the
files that name it are being edited by spec 0137 anyway: AGENTS.md and README for the
solver, the selector test for its counts. Earlier specs keep the old name as a record of
what was run then.

Option 2 saves a rename of seven files, and leaves a name that suggests part of the
project is missing from BigQuery.

## Consequences

- Good: the selector's name and definition agree.
- Bad / accepted cost: earlier specs' commands name a selector that no longer exists.
  AGENTS.md and README carry the current command.
- Follow-ups: none.
