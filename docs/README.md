# Front Office — project docs

The [top-level README](../README.md) is the public front door: what the project does,
how to run it, and the decisions worth explaining. This directory is the working record
behind it.

## Where we are

**Updated 2026-09-27.** Sub-project 1 implementation is complete and running on the landed 2026 data.
Sub-project 2 is underway.

| Sub-project | Design | State |
|---|---|---|
| 1 — ingestion, staging, CI | [`01-ingestion-and-staging.md`](design/01-ingestion-and-staging.md) | Complete, PRs 1–6 |
| 2 — intermediate layer and marts | [`02-intermediate-and-marts.md`](design/02-intermediate-and-marts.md) | In progress; milestones 7–8 merged (PRs #7, #14) |
| 3 — BigQuery, orchestration, dashboard | not yet written | Not started |

Each design doc carries its own milestone-by-milestone progress table, so this page
stays a pointer rather than a second place to keep the same facts current.

## Review and validation

The [2026-09-27 code review](reviews/2026-09-27-code-review.md) records prioritized
findings, test coverage gaps, challenged assumptions, and the remediation plan. Existing
checks pass, but ingestion lifecycle and multi-season identity defects remain open.
Review-remediation status lives there; milestone status remains in the design tables.
The [reviewer follow-up](reviews/2026-09-27-reviewer-follow-up.md) answers the implementer
and records the conditions for doing milestone 9 before the general ingestion fixes.

## Outstanding

The 2026 MLB backfill stopped at **2,402 of 2,430 games**, because the regular season
ran through 2026-09-27. Re-run the backfill after that date, and again around
2026-10-05 with `--refresh` to capture corrections to already-landed games, then refresh the
NAS backup. The fantasy season ended at scoring period 180 (2026-09-20), so no fantasy
analysis depends on those last 28 games — but the MLB season is not complete until this
runs. The current age-only skip rule does not guarantee a final settled capture; see
review finding R4. Record commands, capture dates, counts, and backup verification when
this operational work is completed.

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
