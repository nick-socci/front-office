# Front Office — project docs

The [top-level README](../README.md) is the public front door: what the project does,
how to run it, and the decisions worth explaining. This directory is the working record
behind it.

## Where we are

**Updated 2026-09-26.** Sub-project 1 is complete and running on the full 2026 season.
Sub-project 2 is underway.

| Sub-project | Design | State |
|---|---|---|
| 1 — ingestion, staging, CI | [`01-ingestion-and-staging.md`](design/01-ingestion-and-staging.md) | Complete, PRs 1–6 |
| 2 — intermediate layer and marts | [`02-intermediate-and-marts.md`](design/02-intermediate-and-marts.md) | In progress, PR 7 merged |
| 3 — BigQuery, orchestration, dashboard | not yet written | Not started |

Each design doc carries its own milestone-by-milestone progress table, so this page
stays a pointer rather than a second place to keep the same facts current.

## Outstanding

The 2026 MLB backfill stopped at **2,402 of 2,430 games**, because the regular season
ran through 2026-09-27. Re-run the backfill after that date, and again around
2026-10-05 so the seven-day settle window closes on the final games, then refresh the
NAS backup. The fantasy season ended at scoring period 180 (2026-09-20), so no fantasy
analysis depends on those last 28 games — but the MLB season is not complete until this
runs.

## What is here

| | |
|---|---|
| [`design/00-project-origin.md`](design/00-project-origin.md) | Why the project exists, the rejected alternative, and the cost analysis. A historical record — superseded in places, and says so. |
| [`design/01-ingestion-and-staging.md`](design/01-ingestion-and-staging.md) | Raw JSON landing zone, the warehouse, the dbt staging layer, CI. |
| [`design/02-intermediate-and-marts.md`](design/02-intermediate-and-marts.md) | The platform-neutral intermediate layer and the marts built on it. |
| [`examples/roster_day_query.sql`](examples/roster_day_query.sql) | Sub-project 1's definition of done: who was on a roster on a given day, and what they did in MLB that day. |

Design docs are written before the work, then annotated afterwards where reality
disagreed. Those annotations are marked **Resolved** and the original wording is left
alone, because a plan edited to look prescient is worth nothing.
