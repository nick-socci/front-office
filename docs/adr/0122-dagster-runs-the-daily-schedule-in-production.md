# 0122. Dagster's daemon runs the daily schedule in production

- Status: accepted
- Date: 2026-11-04
- Spec: [0216-where-the-daily-run-runs](../specs/0216-where-the-daily-run-runs/design.md) · Issue: #216

## Context

The roadmap says "Dagster asset definitions locally, Cloud Scheduler + Cloud Run in production",
which describes the pipeline in two places that can drift apart. The origin design (docs/design/00)
chose that split because Dagster's "persistent webserver + daemon … doesn't fit cleanly into 'pay
only when invoked' free tiers". On the NAS (ADR 0121) nothing is paid per invocation. Measured
over this project's graph (spec C8): the daemon holds 505 MB and the UI 349 MB, idle.

Dagster's terms, as they appear here: an **asset** is something the pipeline produces (a landed
endpoint, a dbt model); a **job** materializes a selection of assets; a **schedule** starts a job
at set times; the **daemon** is the long-running process that evaluates schedules and launches
runs; the **UI** (dagster-webserver) shows assets, lineage and run history.

## Decision drivers

- The pipeline described once (#217).
- Run history and lineage visible without reading logs.
- Memory on the host (C8).

## Considered options

1. **Dagster is production**: the daemon runs the schedule on the NAS; the UI is on the LAN.
2. **Dagster for definitions only**: the host's scheduler (DSM's Task Scheduler) calls
   `dagster asset materialize` once a day; no daemon, no UI between runs.
3. **No Dagster**: one CLI entry point and the host's scheduler.

## Decision

Chosen by the owner on 2026-11-05, at the spec's walkthrough: **option 1**, as recommended.

It is the one where what #217 writes is exactly what runs, schedule included, and where a failed
morning can be read and retried from the UI. Option 2 saves 0.85 GB and loses the run history
between runs. It is the fallback if the NAS's memory falls short (spec R6.2). Option 3 drops the
orchestration tool that sub-project 4 exists to show.

## Consequences

- Good: one description of the pipeline; run history in Dagster's SQLite instance.
- Good: Cloud Scheduler and Cloud Run leave the plan. The README's roadmap and the milestone say so.
- Bad / accepted cost: two long-running processes to keep up, about 0.85 GB; a restarted container
  must restart them.
- Bad / accepted cost: dagster-dbt 0.29.28 did not read the real manifest (C8). #217 has to solve
  that.
- Follow-ups: #217 writes the definitions; #218 deploys them; #219 alerts on a failed run.
