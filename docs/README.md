# Front Office — project docs

The [top-level README](../README.md) is the public front door: what the project does,
how to run it, and the decisions worth explaining. This directory is the working record
behind it.

## Where we are

Sub-projects 1 and 2 are complete: ingestion and staging, then the intermediate layer,
the marts and the reconciliation against ESPN. Sub-project 3 is not started.

| Sub-project | Design | Tracker |
|---|---|---|
| 1 — ingestion, staging, CI | [`01-ingestion-and-staging.md`](design/01-ingestion-and-staging.md) | Complete, PRs 1–6 |
| 2 — intermediate layer and marts | [`02-intermediate-and-marts.md`](design/02-intermediate-and-marts.md), then one spec per unit of work in [`specs/`](specs/) | Complete: [milestone](https://github.com/nick-socci/front-office/milestone/1?closed=1) |
| Review remediation: ingestion hardening | [code review](reviews/2026-09-27-code-review.md) | Complete: [milestone](https://github.com/nick-socci/front-office/milestone/2?closed=1) |
| 3 — BigQuery, orchestration, dashboard | not yet written | — |

**Live status is in [Issues](https://github.com/nick-socci/front-office/issues), not in
this repo's markdown.** Design docs say what was decided and what it got wrong; issues
say what is done, and issue dependencies say what must happen first. Keeping a status
table here as well would mean two places to update and one of them going stale.

## Review and validation

The [2026-09-27 code review](reviews/2026-09-27-code-review.md) records prioritized
findings, test coverage gaps, challenged assumptions, and the remediation plan. It maps
each finding to its issue, and all six of those issues are closed.
The [reviewer follow-up](reviews/2026-09-27-reviewer-follow-up.md) answers the implementer
and records the conditions for doing milestone 9 before the general ingestion fixes.

## What is here

| | |
|---|---|
| [`design/00-project-origin.md`](design/00-project-origin.md) | Why the project exists, the rejected alternative, and the cost analysis. A historical record — superseded in places, and says so. |
| [`design/01-ingestion-and-staging.md`](design/01-ingestion-and-staging.md) | Raw JSON landing zone, the warehouse, the dbt staging layer, CI. |
| [`design/02-intermediate-and-marts.md`](design/02-intermediate-and-marts.md) | The platform-neutral intermediate layer and the marts built on it. |
| [`specs/`](specs/) | One directory per unit of work since October 2026: requirements with expected values, a design with the alternatives weighed, and the tasks. Approved before anything is built; amended in the open, with a date, when the build shows the spec was wrong. |
| [`adr/`](adr/README.md) | One record per decision a reasonable engineer could have made differently, with the options considered and what the choice costs. |
| [`examples/`](examples/) | Queries to run against a built warehouse: sub-project 1's definition of done (a team's roster on one day, and what each player did in MLB that day), and one over each question the marts answer. dbt declares each as an exposure, and CI runs them. |
| The [docs site](https://nick-socci.github.io/front-office/) | Every model's description, columns, SQL and tests, and the graph of what feeds what. Built by CI from the fixtures. |

Design docs are written before the work, then annotated afterwards where reality
disagreed. Those annotations are marked **Resolved** and the original wording is left
alone, because a plan edited to look prescient is worth nothing. Specs follow the same
rule under the heading *Amendments*.
