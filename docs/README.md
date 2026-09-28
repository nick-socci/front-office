# Front Office — project docs

The [top-level README](../README.md) is the public front door: what the project does,
how to run it, and the decisions worth explaining. This directory is the working record
behind it.

## Where we are

Sub-project 1 is complete. Sub-project 2 is underway.

| Sub-project | Design | Tracker |
|---|---|---|
| 1 — ingestion, staging, CI | [`01-ingestion-and-staging.md`](design/01-ingestion-and-staging.md) | Complete, PRs 1–6 |
| 2 — intermediate layer and marts | [`02-intermediate-and-marts.md`](design/02-intermediate-and-marts.md) | [Milestone](https://github.com/nick-socci/front-office/milestone/1) |
| 3 — BigQuery, orchestration, dashboard | not yet written | — |

**Live status is in [Issues](https://github.com/nick-socci/front-office/issues), not in
this repo's markdown.** Design docs say what was decided and what it got wrong; issues
say what is done. Keeping a status table here as well would mean two places to update
and one of them going stale.

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
