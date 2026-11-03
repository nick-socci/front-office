# The production raw loader for BigQuery — requirements

Issue: #140 · Tier: L · Status: draft

## Problem

BigQuery's raw data arrives through `scripts/spike_load_bigquery.py`: run by hand, it replaces
`raw.api_responses` whole on each run, and ADR 0052 says it is not the production design. It
holds no record of what already went up and has no key-collision check (ADR 0011).

The table's shape now costs more than the loader's manual steps do. A full build bills 56.07 GB
(C1), against the 5.35 GB of the spike's slice that #140 was written from: run daily, 1.53 TiB
a month, about 3.31 USD over the free terabyte against a 5 USD budget (C2). 47.83 GB of that is
nodes that read the raw table (C3). A boxscore model is billed the whole payload of every
boxscore and takes 486 s to 1,031 s (C4); a test of the 4 MB id map is billed 0.32 GB, because
clustering reads whole blocks shared with boxscores (C5).

## Goals

- Raw data reaches BigQuery by an append that a scheduler can repeat, not by replacing a table.
- A full build costs little enough that a daily one stays inside the free terabyte, with no
  model's rows changed.
- A capture that cannot be told apart from another, a payload that does not fit its declared
  structure, or anything naming a member stops the load before anything is sent.

## No-gos

- Running the loader on a schedule, Cloud Run, Cloud Scheduler, Dagster: sub-project 4.
- Fetching captures in the cloud, or moving the landing zone off the owner's machine: this
  spec's loader reads a local landing zone (ADR 0119).
- Any change to DuckDB's raw layer, to `raw.captures` there, or to what a DuckDB build returns.
- Any change to a model's SQL beyond what names the raw tables. A staging or later model's
  rows must not change.
- Widening what may leave the machine: no endpoint or field that does not go up today.
- A rule for resolving a key collision: ADR 0011 keeps that for after live operation.
- Incremental dbt models. Every build still rebuilds every model (ADR 0069).

## Rabbit holes

- Typing the seven small endpoints → they stay whole JSON documents, and their models keep
  their SQL. At most 25 MB each, they bill near the 10 MB floor once alone in a table (C8).
- Typing inside a JSON leaf (a player's `person`, a game line) → the leaves stay as the
  structures declare them. The structures are what the models read; redesigning them is not
  this work.
- Partitioning raw tables by season → every model reads every season (ADR 0069), so nothing
  would prune.
- Reconstructing past load history → nothing needs it. The first load fills each table from the
  landing zone, and the local manifest stays the record of what has landed.
- Comparing each uploaded payload on every run → a daily load does not re-read 2.2 GB. Each run
  compares keys; `--verify` compares the rows when a table is first filled or rebuilt (R4.4).

## Requirements

### R1. The raw tables

- R1.1 THE SYSTEM SHALL keep one native BigQuery table per uploaded endpoint, named
  `raw.<source>_<endpoint>`, for the eleven endpoints that go up today.
- R1.2 THE SYSTEM SHALL give `espn/roster`, `espn/matchup_days`, `mlb/boxscore` and
  `mlb/schedule` one column per top-level field of the structure their capture view declares:
  a declared object as a `RECORD`, a list as `REPEATED`, a map as `REPEATED RECORD` of `key` and
  `value`, a `JSON` leaf as `JSON`, `BIGINT` as `INT64` and `VARCHAR` as `STRING`.
- R1.3 THE SYSTEM SHALL give the seven other endpoints a `payload` column of type `JSON`, holding
  the document whole, or for `espn/teams` and `espn/transactions` the projection of ADR 0093.
- R1.4 THE SYSTEM SHALL keep `raw.captures` on BigQuery with the columns and meaning it has on
  DuckDB: one row per uploaded capture, no payload.
- R1.5 THE SYSTEM SHALL create every table of R1.1 and R1.4 on its first run, so that an endpoint
  with no captures gives its capture view no rows rather than a missing table.
- R1.6 WHEN `espn/matchup_days` goes up THE SYSTEM SHALL apply its projection of ADRs 0061 and
  spec 0147 before the structure, so that `rosterForCurrentScoringPeriod` stays an empty object.

### R2. Models read the new tables through the capture views

- R2.1 THE SYSTEM SHALL change only `bigquery__fo_captures`, `fo_capture_keys`, the raw sources
  and the fixtures that name the manifest, so that no staging or later model's SQL changes.
- R2.2 THE SYSTEM SHALL have a heavy capture view on BigQuery select its table's columns without
  parsing, with the columns and types the view has today.
- R2.3 THE SYSTEM SHALL read the manifest as `source('raw', 'captures')` on both warehouses.
- R2.4 THE SYSTEM SHALL keep `fo_capture_rows` fixtures working on both warehouses, the structure
  still written once.

### R3. Appending

- R3.1 WHEN the loader runs THE SYSTEM SHALL upload only captures absent from the table they
  belong in, by load jobs, appending, and SHALL do nothing to a table with none to add.
- R3.2 THE SYSTEM SHALL read what a table holds through the table read API (`tabledata.list` with
  selected fields), which bills nothing.
- R3.3 IF a run stops after some tables were appended THEN THE SYSTEM SHALL, on the next run, add
  exactly what is missing from each table, duplicating nothing.
- R3.4 THE SYSTEM SHALL append to `raw.captures` after the capture's endpoint table, so that the
  manifest never names a capture the endpoint table lacks.
- R3.5 IF two different files claim one key (ADR 0011), in the landing zone or against a row
  already in BigQuery, THEN THE SYSTEM SHALL send nothing and SHALL name both files.
- R3.6 IF a capture's `fetched_at` has not the form the loader accepts THEN THE SYSTEM SHALL send
  nothing, as `front-office load` does.
- R3.7 THE SYSTEM SHALL never replace or delete a row in normal running.
- R3.8 WHILE an upload runs THE SYSTEM SHALL hold a local lock of its own, taken before it reads
  any table's state, and a second upload on the machine SHALL stop without sending anything. The
  lock is not the landing zone's writer lock, so that fetching can go on during an upload.

### R4. Rebuilding and checking

- R4.1 IF a typed table's schema is not what its declared structure gives THEN THE SYSTEM SHALL
  refuse to append to it and SHALL name the table and the rebuild command.
- R4.2 WHEN asked to rebuild an endpoint THE SYSTEM SHALL replace that table, in one load job,
  from every committed capture of the endpoint.
- R4.3 WHEN a run has appended THE SYSTEM SHALL check that each load job's row count is what was
  sent, and that each table's `file_path`s and the manifest's are exactly the landing zone's for
  that endpoint, each key appearing once, and SHALL exit non-zero otherwise.
- R4.4 WHEN `--verify` is given THE SYSTEM SHALL read back every row of the named tables and
  compare it with what would be sent, as parsed values, exiting non-zero on any difference.

### R5. A payload that does not fit

- R5.1 THE SYSTEM SHALL read a typed endpoint's declared structure from
  `dbt/macros/capture_structures.sql`, so that the view and the loader cannot hold two.
- R5.2 THE SYSTEM SHALL keep only declared fields, and SHALL treat a declared field the payload
  lacks as the view treats it: `null`, or an empty list for a list or a map.
- R5.3 IF a `BIGINT` leaf holds anything but a whole number, a `VARCHAR` leaf holds an object or a
  list, a list holds a `null`, or a present non-null value is not the container its structure
  declares (an object for a list, a list for an object or map), THEN THE SYSTEM SHALL send nothing
  and SHALL name the capture and the path, never the value.
- R5.4 WHEN a `VARCHAR` leaf holds a number THE SYSTEM SHALL store its text, as `lax_string` reads
  it (the league `id`, C7).

### R6. What may leave the machine

- R6.1 THE SYSTEM SHALL upload only the eleven endpoints of ADRs 0054, 0061, 0093 and 0095, from a
  constant list with no option to widen it.
- R6.2 THE SYSTEM SHALL build `espn/teams` and `espn/transactions` from the one field list per
  endpoint that the fixtures use (ADR 0093), now held in the package.
- R6.3 THE SYSTEM SHALL check every row to be sent with the rules of ADRs 0054 and 0094 before any
  job runs, with a map's keys still keys (before they become `key` values), and SHALL send
  nothing on a hit, naming where and never what.
- R6.4 THE SYSTEM SHALL cross-check every transaction id in the landing zone, not only new ones,
  against the account ids of all `espn/teams` and `espn/transactions` captures, on every run, so
  that an account first seen today is checked against ids sent earlier.
- R6.5 IF billing is not enabled on the project, or no project is named, THEN THE SYSTEM SHALL run
  no job. The project is always named explicitly, never taken from a global default.
- R6.6 THE SYSTEM SHALL read no ESPN credential.
- R6.7 IF the cross-check of R6.4 finds an id equal to an account in a row already in BigQuery THEN
  THE SYSTEM SHALL send nothing, exit non-zero, and name the table and the row's capture, never the
  value, saying that the row is already uploaded and what the owner's remedy is (design, *A hit on a
  row already sent*). It SHALL refuse every later run until the row is gone.

### R7. How it is run and what replaces what

- R7.1 THE SYSTEM SHALL provide `front-office upload --project <id> [--raw-root …] [--dry-run]
  [--rebuild <source/endpoint>] [--verify]`, where `--dry-run` sends nothing. Without `--project` it needs
  neither credentials nor the `bigquery` dependency group, does the local checks only (stamps,
  collisions in the zone, reduction, privacy) and says so. With `--project` it also does the remote
  read-only checks (schemas, stored keys), and needs credentials and the group.
- R7.2 THE SYSTEM SHALL read the landing zone only through `LandingZone`, and SHALL need no DuckDB
  warehouse.
- R7.3 WHEN this work is merged THE SYSTEM SHALL no longer hold
  `scripts/spike_load_bigquery.py` or `raw.api_responses`, the old table being dropped only once
  the real build on the new tables compares equal.

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| Rows per endpoint table, and in `raw.captures` | roster 1,471; matchup_days 1,469; boxscore 41,394; schedule 20; settings 21; teams 13; matchups 12; pro_schedule 9; players 9; transactions 7; player_id_map 1; manifest 44,426, unless the landing zone has grown, then what it holds (C10) | `--verify`, and `front-office upload --dry-run` |
| Every relation of a full build | exactly equal to the DuckDB build, floats included: 80 relations pass | `scripts/compare_bigquery.py`, against the same landing zone |
| Bytes billed by a full build | no more than 20 GB; the estimate is 14.45 GB (C9). Above that, stop and report | `run_results.json` of `dbt build --selector bigquery --exclude-resource-type unit_test` |
| Storage of the heavy tables | about 2.24 GB against 8.44 GB (C6) | table metadata |
| Unit tests on BigQuery | all pass, as on DuckDB | the commands in AGENTS.md |
| A second upload with nothing new | no load job, exit 0 | run it twice |
