# 0065. DuckDB stays the development warehouse, with every season in it

- Status: proposed
- Date: 2026-10-14
- Spec: [0150-staging-reads-payload-files](../specs/0150-staging-reads-payload-files/design.md) · Issue: #150

## Context

The project began on DuckDB for local speed, to move to BigQuery before v1
(`docs/design/00-project-origin.md`); ADR 0051 keeps DuckDB working throughout, as what CI
and the fixtures build on. With eight seasons landed by #83, DuckDB runs the real build
only with its memory held to 12 GB by a local profile, cannot load from scratch on the
development machine at twice today's data (#149), and cannot run two data tests at all
(#146). #150 listed, as one direction, leaving it and relying on BigQuery, with DuckDB for
CI and small work. AGENTS.md requires anything that produces numbers to be checked against
the real season, and that checking is done locally, where a query costs nothing.

## Decision drivers

- Real-season verification stays local and free.
- A bar that shows the problem is gone, not deferred: memory must not grow with seasons.
- The committed configuration works as committed.

## Considered options

1. **DuckDB holds the full history, to a stated bar** — the raw layer is changed until it
   meets it.
2. **DuckDB for CI and small work only** — the full history lives on BigQuery (#150,
   direction 4).

## Decision

Chosen by the owner on 2026-10-14: **option 1**, with this bar, checked two ways (spec
0150, R6):

- From an empty warehouse on the development machine, `front-office load`, `dbt build`
  and `dbt test` pass with every landed season and the committed profile, with no
  memory or thread override. For `dbt test`, "pass" is defined in spec 0150's R6.1: every
  test runs to a result, none errors other than by its own assertion, and the only
  failures are the known ones #147 tracks, with their known rows.
- The smallest DuckDB `memory_limit`, on the ladder 1, 2, 4, 8 GB, under which load, build
  and test pass is the same for a landing root holding one season as for one holding all.

Option 2 would move every real-data check to a billed warehouse and leave the
development warehouse unable to answer questions about most of the data.

## Consequences

- Good: real-season checks stay local; the README's local-profile recipe can go; #147's
  question about whether a local profile is acceptable is answered (it is not needed).
- Bad / accepted cost: the raw layer must change to meet the bar (ADR 0066), a large change.
- Follow-ups: the ladder is run by spec 0150's build and recorded on #150; a later
  change that breaks the bar is a regression.
