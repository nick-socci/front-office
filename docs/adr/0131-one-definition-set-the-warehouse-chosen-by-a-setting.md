# 0131. One definition set, the warehouse chosen by a setting

- Status: accepted
- Date: 2026-11-15
- Spec: [0217-dagster-daily-pipeline](../specs/0217-dagster-daily-pipeline/design.md) · Issue: #217

## Context

ADR 0123: production builds BigQuery after `upload`; the laptop builds DuckDB, which needs
`front-office load` first. The issue's "done" is one green run against the real season locally,
which is the DuckDB side. Dagster reads one manifest, and the asset keys are the same on both
targets. Duplicate asset keys cannot live in one set of definitions.

## Decision drivers

- Fetch code and dbt assets exist once (the point of #217).
- The laptop can run the same job with no cloud account.
- No second description of the pipeline that drifts (spec 0216 R3.1).

## Considered options

1. **One definition set**; `FO_WAREHOUSE` (`bigquery` or `duckdb`, default `duckdb`) chooses `upload`
   or `load` inside one asset, `raw_in_warehouse`, and the dbt target.
2. **BigQuery only**: the laptop runs the pipeline against suffixed BigQuery datasets.
3. **Two code locations** sharing asset functions.

## Decision

Chosen by the owner on 2026-11-15: **option 1**. The owner chose "one definition set, two jobs";
the spec shows that a second job would select exactly the same assets, since the two warehouses'
steps are one asset with one key, so it has one job, `daily`, and the setting that decides what it
does. This refinement is flagged in the spec PR for the owner to confirm.

Option 2 bills about 16 GB a run to prove a local change and has no DuckDB path. Option 3 is the
drift this issue exists to remove.

## Consequences

- Good: the schedule and `dagster dev` run the same job; the laptop needs no credentials.
- Bad / accepted cost: `raw_in_warehouse` does two different things by setting; a test holds each.
- Follow-ups: #218 sets `FO_WAREHOUSE=bigquery` and `FO_BQ_PROJECT` in the host's environment.
