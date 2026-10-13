# Staging models that parse a payload per game or per day, built a season at a time — requirements

Issue: #143 · Tier: L · Status: draft

## Problem

The build of #83 covered a second season and the real build ran out of memory: DuckDB's
limit, 23.9 GiB of a 29 GB machine. It is working memory, not disk. Five staging models
each parse one large JSON payload per game or per scoring period, and what they hold at
once grows with the captures loaded: 1.4 GB of boxscore JSON and 0.74 GB of roster JSON
for two seasons. Measured on 2026-10-12 with 2025 and 2026 loaded (design.md, *Claims
ledger*): the three roster models fail under a 12 GB limit even on one thread and pass
under 16 GB; the two boxscore models fail under 12 GB at the default sixteen threads. On
`main`, with every seed loaded, the two-season run passes at the default limit with a
peak of 23.1 GB, under one gigabyte from the wall. #83 lands five more seasons, about
four times these captures.

The owner chose on 2026-10-12 to build these models a season at a time, to merge #142
first, and to spec this before #83 resumes.

## Goals

- The real build's peak memory no longer grows with the number of seasons loaded: it is
  set by the largest single season.
- Every model returns the rows it returns today.
- The build stays one `dbt build`, with no step a person has to remember.
- CI, the gates, the tenant-isolation check and the BigQuery slice keep working, and a
  build on BigQuery costs no more than it does today.

## No-gos

- **No change to any row of any model**, other than the one column R1.1 adds.
- **No landing of data and no request.** The two seasons already landed are what this is
  measured on.
- **No change to #83's branch.** Its sixth model of this kind, `stg_espn__matchup_days`,
  follows the pattern when #83 resumes.
- **No change to ingestion or to `raw.api_responses`.** Ingestion never interprets.
- **No batching on BigQuery**, where the limit does not exist and each batch would be
  billed for the endpoint's whole payload again (ADR 0060).
- **No memory limit or thread count written into the committed profile** as the fix.
- **No new fixture data**, and no fixture file changed.
- **No model outside the five named in R1.1 changes materialization.**

## Rabbit holes

- *Why DuckDB holds every payload at once* → not chased. The likely cause is in *Open
  questions*; the fix does not depend on it.
- *Batches smaller than a season* → not built. A capture's date is not in the raw table,
  only its season, and one season fits (C8).
- *Showing memory flat over three or more seasons* → cannot be shown here: two seasons
  are landed and this spec lands nothing. It is shown for two, argued for more (one
  batch at a time, each one season's captures), and measured for eight by #83.
- *Rebuilding only the seasons that changed* → not built. Every season is rebuilt on
  every build, which costs seconds (C9); skipping unchanged seasons is a later
  optimisation with its own risk of stale rows.
- *Making the roster models cheaper per payload* → not here. It would change SQL that #142
  has just ported.

## Requirements

### R1. The five models are built a season at a time on DuckDB

- R1.1 THE SYSTEM SHALL build `stg_mlb__batting_game_logs`, `stg_mlb__pitching_game_logs`,
  `stg_espn__roster_entries`, `stg_espn__roster_entry_slots` and
  `stg_espn__player_game_stats` on DuckDB with dbt's `microbatch` incremental strategy,
  one batch per calendar year, each batch reading only the captures of that season, and
  SHALL add to each one column, `season_start`, a date, not null: the first of January of
  the capture's season.
- R1.2 THE SYSTEM SHALL provide a view, `stg_raw__season_responses`, holding every column
  of `raw.api_responses` and `season_start`, declared as the relation's event time, and
  the five models SHALL read their captures through it.
- R1.3 WHEN `dbt build` or `dbt run` is run without `--full-refresh` THE SYSTEM SHALL
  rebuild every season from the first season with a capture to the current one, so that a
  table never holds a row an earlier build made from a capture since superseded.
- R1.4 THE SYSTEM SHALL take the first batch's year from one project variable, so that a
  season earlier than today's first needs one value changed.
- R1.7 THE SYSTEM SHALL run a model's batches one after another, never two at once
  (`concurrent_batches: false`), so that a model's peak is one season's whatever the
  number of seasons a run redoes.
- R1.8 IF one of the five tables exists without the `season_start` column, as every
  warehouse built before this change does, THEN an ordinary build SHALL fail naming the
  model and saying to run with `--full-refresh`; it SHALL NOT insert into or silently
  keep the old table. The first build after this change is a full refresh, and the README
  and AGENTS.md say so.
- R1.5 IF a model of R1.1 would read a relation with no event time declared THEN THE
  SYSTEM SHALL fail the gates: every batch would then insert every season's rows.
- R1.6 THE SYSTEM SHALL build the five models on the `ci` target the same way, so that CI
  exercises the batched path on every run.

### R2. Rows do not change

- R2.1 THE SYSTEM SHALL produce, on the real warehouse with 2025 and 2026 loaded, every
  relation identical to the one built from `main` at this spec's base commit, over the
  columns it had: `scripts/compare_warehouses.py OLD NEW` reports no relation differing
  in rows, and the only columns on one side are the five `season_start`.
- R2.2 THE SYSTEM SHALL produce the same on the `ci` target from the fixtures.
- R2.3 WHEN the build is run a second time with nothing new loaded THE SYSTEM SHALL leave
  every relation identical to the first run's: no row duplicated, none lost.
- R2.4 WHEN a newer capture of a game or scoring period is loaded and the build is run
  without `--full-refresh` THE SYSTEM SHALL hold that entity's rows from the newer capture
  only.

### R3. Memory

- R3.1 THE SYSTEM SHALL complete the real `dbt build` with 2025 and 2026 loaded under a
  DuckDB memory limit of 16 GB at the profile's four dbt threads. On `main` the same run
  fails under that limit (C4).
- R3.2 THE SYSTEM SHALL record, for that build and for one with no limit set: wall time,
  peak resident memory, and the slowest five models.
- R3.3 IF R3.1 cannot be met THEN the build SHALL stop and take the measurements to the
  owner. It SHALL NOT lower dbt's thread count or set a memory limit in the committed
  profile to get there.

### R4. BigQuery

- R4.1 THE SYSTEM SHALL build the five models on the `bq` target as tables in one piece,
  as today, with the `season_start` column.
- R4.2 THE SYSTEM SHALL write `stg_raw__season_responses` and the `season_start`
  expression under ADR 0051, so that the slice builds on both warehouses, and SHALL add
  the view to the `bigquery_slice` selector's expected models (31 where the spike
  counted 30).
- R4.3 THE SYSTEM SHALL build the slice on BigQuery and compare it with DuckDB as spec
  0130 does: 30 of 30 relations pass, the 29 of the spike and the new view, with the new
  column equal on both.
- R4.4 THE SYSTEM SHALL report bytes billed by that build beside the 5.35 GB of #130. IF
  it is more than 10% higher THEN the build SHALL stop for the owner.

### R5. Tests and tooling

- R5.1 THE SYSTEM SHALL keep every unit test and data test of the five models, with what
  each asserts unchanged. A unit test whose input changes from the raw source to the view
  is given the same rows through the view. IF dbt cannot unit-test a `microbatch` model
  THEN the build SHALL stop for the owner; no test is dropped.
- R5.2 THE SYSTEM SHALL add dbt unit tests for `stg_raw__season_responses`: a capture's
  season gives the first of January of that year; a capture with no season in its
  partitions gives null and is in no batch.
- R5.3 THE SYSTEM SHALL add a singular test that the five models hold only rows whose
  `season_start` agrees with their own season, where the model has one.
- R5.4 THE SYSTEM SHALL add a pytest for R1.5, R1.7 and R1.1's list: the five models, and
  no other, are `microbatch` on DuckDB with `concurrent_batches` false and
  `on_schema_change` `fail`, and every relation they read through `ref` or `source`
  declares an event time or is a seed.
- R5.5 THE SYSTEM SHALL keep the tenant-isolation check at 0 differing pairs, sqlfluff
  clean, and the docs site building.
- R5.6 THE SYSTEM SHALL say in AGENTS.md what a person must know: which models are built
  a season at a time and why; that a column added to one needs `--full-refresh`, as a
  seed does; and that a model of this kind reads its captures only through the view.

## Expected values

Measured on 2026-10-12 on `data/warehouse_143.duckdb`, both seasons loaded, `main` at
e8ee62d (design.md, *Claims ledger*).

| Check | Expected | How to verify |
|---|---|---|
| Rows of the five models, real warehouse | batting 102,595 · pitching 41,668 · roster entries 113,059 · the other two as built from `main`, recorded in task 1 | `compare_warehouses.py` against task 1's copy |
| `season_start` | 2025-01-01 and 2026-01-01 only, on the real warehouse; no null | query |
| Roster entries by season | 57,406 (2025) · 55,653 (2026) | query; the prototype's split |
| Every other relation | identical | `compare_warehouses.py` |
| A second build | every relation identical to the first | R2.3 |
| An ordinary build on a warehouse built before this change | fails on the five models, naming `--full-refresh` | R1.8, on a copy of task 1's warehouse |
| Batches of one model | never two running at once | dbt's log: each batch's START after the one before's OK |
| Real build under a 16 GB limit | passes; on `main` it fails with 3 models out of memory | R3.1 |
| Peak resident memory of one roster model's run | about 7 GB, against 12.5 GB in one piece | `/usr/bin/time -v`; the prototype's 7.2 to 7.4 GB |
| Batches of a run on 2026-10-12 | one per year from the first-season variable to 2026 | dbt's log |
| CI | passes; warnings unchanged at 3; isolation 0 | `.agentic/gates` |
| BigQuery slice | 31 models (21 tables, 9 views, 1 ephemeral); 30 of 30 relations equal to DuckDB | spec 0130's comparison |
| Bytes billed by a slice build | within 10% of 5.35 GB | `run_results.json` |
