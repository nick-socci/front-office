# 0114. A unit test names the manifest through the target

- Status: accepted
- Date: 2026-10-29
- Spec: [0138-unit-tests-on-bigquery](../specs/0138-unit-tests-on-bigquery/design.md) · Issue: #138

## Context

The newest capture of an entity is chosen on the loader's manifest (`fo_espn_latest`,
`fo_latest_boxscore_responses`), read through `fo_capture_keys()`. That is
`source('raw', 'captures')` on DuckDB and `source('raw', 'api_responses')` on BigQuery
(ADR 0070). A unit test must give each direct parent of its model. 20 tests give
`source('raw', 'captures')`, so on BigQuery they fail before running (spec 0138, C4).

dbt renders an `input:` string at parse time with `target` available (C6). An input
written as `"source('raw', '{{ 'api_responses' if target.type == 'bigquery' else
'captures' }}')"` resolves to the right source on each warehouse, and the same rows serve
both (C8).

## Decision drivers

- One `given` entry per test, for both warehouses.
- No change to BigQuery's raw layer before the production loader is designed (#140).

## Considered options

1. **The input names the source through the target**, in exactly the spelling above,
   held by the gate (spec 0138, R2.2).
2. **BigQuery gets a `raw.captures` too.** For example, a view over `api_responses`'
   keys, created by the upload script. `fo_capture_keys()` would then be
   `source('raw', 'captures')` on both, and the tests would need no change.

## Decision

Chosen by the owner on 2026-10-29, as recommended: **option 1**.

Option 2 makes the warehouses more alike and removes the conditional. It also adds an
object to BigQuery's raw layer that dbt does not build, ahead of #140, which decides what
that layer is. If #140 gives BigQuery a `raw.captures`, the conditional can go then, in
one search-and-replace.

## Consequences

- Good: the 20 tests run on both warehouses with one changed line each.
- Bad / accepted cost: a long, conditional input string, repeated in 20 tests. The gate
  accepts only that spelling, so it cannot drift.
- Follow-ups: #140 says whether BigQuery gets a `raw.captures`. If it does, option 2
  replaces this.
