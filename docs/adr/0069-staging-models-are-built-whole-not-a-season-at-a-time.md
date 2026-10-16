# 0069. Staging models are built whole, not a season at a time

- Status: accepted; supersedes [0058](0058-a-model-that-parses-a-payload-per-game-or-day-is-built-a-season-at-a-time.md), [0059](0059-every-build-rebuilds-every-season.md), [0060](0060-batched-models-are-plain-tables-on-bigquery.md)
- Date: 2026-10-14
- Spec: [0150-staging-reads-payload-files](../specs/0150-staging-reads-payload-files/design.md) · Issue: #150

## Context

ADR 0058 built six staging models a season at a time (dbt microbatch) because parsing
payloads from the raw table held every payload of a run in memory; ADRs 0059 and 0060
followed from it. It costs a rebuild of every season on every build, an event-time view
(`stg_raw__season_responses`, `season_start`), a guard against seasons that fall outside
the batches, a registry test, and different mechanisms on DuckDB and BigQuery. Read from
files with a declared structure (ADR 0066), the heaviest of the six read all eight seasons
in one query in seconds and under 1 GB: player game stats 7,526,702 rows in 3.0 s at
0.17 GB, roster entries 2.0 s, boxscore lines 3.8 s, matchup days 1.7 s (spec 0150,
C6–C9).

## Decision drivers

- The reason for batching is gone.
- One mechanism on both warehouses.
- Fewer moving parts that can silently drop a season.

## Considered options

1. **Build whole** — the six become plain tables on both warehouses, and the batching
   machinery goes.
2. **Keep batching** — the six only change where they read from; each batch filters the
   glob to its season.

## Decision

Chosen by the owner on 2026-10-14: **option 1**. ADRs 0058, 0059 and 0060 are superseded.

The full shapes of the two largest models were also run over every committed capture
(C19, C20): one step, ranking parsed rows to find the newest capture, ran out of memory
at 2 GB, and spec 0150 replaces it with a choice on the manifest (0.18 GB, the same rows).
The other four were measured as reads. If the build's ladder (ADR 0065) shows one of the
six needs batching after all, it comes back for that model alone, by a new ADR.

## Consequences

- Good: a build no longer reruns each season as a batch; `stg_raw__season_responses`,
  `season_start`, `first_season_start`, the three tests that guard batching and the
  registry test go; no season can fall outside a batch; DuckDB and BigQuery build the six
  the same way.
- Bad / accepted cost: a build parses every season every time, as it does today; nothing
  bounds a single model's memory by season if a later model needs it.
- Follow-ups: none planned.
