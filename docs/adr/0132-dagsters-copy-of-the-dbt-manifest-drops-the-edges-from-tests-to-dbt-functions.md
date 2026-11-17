# 0132. Dagster's copy of the dbt manifest drops the edges from tests to dbt functions

- Status: accepted (the owner chose this on 2026-11-17, at Codex round 4 of PR #227: it amends an accepted decision)
- Date: 2026-11-17
- Spec: [0217-dagster-daily-pipeline](../specs/0217-dagster-daily-pipeline/design.md) · Issue: #217
- Amends: [0128](0128-dagster-reads-the-real-dbt-manifest-through-dagster-dbt-0-29-30.md)

## Context

ADR 0128 chose the real dbt manifest, unfiltered, through dagster-dbt 0.29.30, and named a
manifest filtered before Dagster reads it as the fallback if a BigQuery-target load or run failed.
Its task 3 loaded a BigQuery manifest and ran one seed and one view; both worked. The first full
`dbt build` on the BigQuery target, on `mothership` (2026-11-17), failed at node 539 of 579: for a
singular test that has several parents and no asset key, dagster-dbt looks each parent up in the
manifest's `nodes` or `sources`, a dbt function is in neither, and the lookup returns `None` and
raises `'NoneType' object has no attribute 'get'`. On the BigQuery target two lineup tests
(`fct_lineup_decisions_are_never_worse_than_the_actual_lineup`,
`fct_lineup_decisions_change_nothing_when_nothing_is_gained`) read the function `sum_in_order`
through `fo_sum_in_order`. On DuckDB no test does, so no DuckDB build or fixture could show it.

## Decision drivers

- Every model, seed and test still runs, and runs as dbt decides: Dagster only describes and streams.
- Per-model lineage and status in the UI (ADR 0128's driver), 80 assets as before.
- Nothing that hides a node the selector builds (ADR 0128's objection to a filtered manifest).
- No change to a dbt test for a quirk of the orchestrator.

## Considered options

1. **Drop, in Dagster's copy, the edges from tests to dbt functions** (`without_function_parents`):
   no node, asset or test is removed; dbt's own manifest and run are untouched.
2. **Give the two tests a dagster asset key in their dbt meta**, so they load as asset checks and
   never reach the failing path: keeps the manifest literally unfiltered, but changes two dbt test
   files for the orchestrator.
3. **Revert and wait for a dagster-dbt that handles a function parent**: `daily` cannot finish a
   BigQuery build until then, which blocks #218 on an upstream release.
4. **A manifest filtered of the nodes involved** (ADR 0128's option 2): hides nodes the selector
   builds.

## Decision

Chosen by the owner: **option 1**. It is the smallest departure from ADR 0128's "the real
manifest": the node set, the assets and the tests are the real ones; only an edge dagster-dbt
cannot read is absent from the copy it is given. Option 2 would have kept the word "unfiltered" at
the price of two dbt test files; option 3 would have stopped #218.

A test (`test_the_manifest_dagster_gets_survives_a_test_event_whose_parent_is_a_function`) runs
dagster-dbt's own test-event conversion over the manifest `build_dbt_assets` hands it, and has a
control that fails when dagster-dbt stops raising on a function parent: that is the signal to
delete `without_function_parents` and mark this record superseded.

## Consequences

- Good: the BigQuery build runs to the end (579 nodes, 427 checks passed, on `mothership`,
  2026-11-17); the manifest dbt itself reads is unchanged.
- Bad / accepted cost: Dagster's lineage omits the edge from those two tests to `sum_in_order`, and
  nothing else about them. The orchestration holds a small adaptation to a 0.x library.
- Follow-ups: remove the adaptation when the control test fails after a dagster-dbt upgrade.
