# Staging reads payload files with a declared structure; the raw table holds no payloads — requirements

Issue: #150 · Tier: L · Status: draft

## Problem

`raw.api_responses` holds each API response whole, as one JSON value per row: 27,417 rows
and 8.97 GB of payload text for eight seasons, values up to 4.3 MB. Every staging model re-parses those
values in SQL. The same cause has surfaced three times and been worked around each time
(#143 batched six models by season, #149 made the load incremental), and is open a
fourth time in #146, where two data tests run out of memory at any thread count. The
eight-season build runs only with DuckDB held to 12 GB by a local profile, and a load from
scratch peaks at 14.9 GB (#149).

Measured for this spec on 2026-10-14 (design.md, *Claims ledger*): storage is not the
cause. Neither a smaller row group (direction 3 of #150) nor Parquet files (direction 1)
let #146's tests or the batched models run in 12 GB. What costs the memory is passing
megabyte JSON values through a query. Read from the payload files with a declared
structure instead, the four heaviest staging shapes give today's rows exactly, for all
eight seasons, in under 1 GB and a few seconds, and need no more for eight seasons than
for one.

The owner decided on 2026-10-14 that DuckDB stays the development warehouse with every
season in it, set the bar below, and chose this direction and the seven decisions in
design.md.

## Goals

- From an empty warehouse on the development machine, `front-office load`, `dbt build`
  and `dbt test` succeed with every landed season, with the committed profile.
- Memory does not grow with the number of seasons: the smallest DuckDB memory limit under
  which load, build and test pass is the same for one season as for eight.
- Every model returns the rows it returns today.
- One mechanism: every staging model reads its captures the same way, on DuckDB from the
  landing zone's files and on BigQuery from the uploaded table, through one macro.
- CI, the gates, the tenant-isolation check and the BigQuery slice keep working; a
  BigQuery build bills what it bills today.

## No-gos

- **No change to any row of any model.** The comparison is exact, model by model.
- **No change to the landing zone** or to how captures are written, published or
  quarantined (ADRs 0014, 0015). Ingestion still never interprets a payload.
- **No new request** to ESPN or MLB. The eight landed seasons are what this is measured on.
- **No redesign of BigQuery's raw layer.** The production loader is #140's. BigQuery keeps
  its uploaded `raw.api_responses` with a JSON payload.
- **No memory limit or thread count in the committed profile.**
- **No fixture data changed**, and no fixture file added except where a test of the empty
  case needs one.
- **No change to what a staging model means**: grains, column sets and dedup rules stay.
  Only where the captures come from, and how they are parsed, changes. The one exception
  is `season_start`, which the six batched models lose with batching (R4.2; the owner's
  decision 3, ADR 0069).
- **No work on #147's reconciliation failures**, other than #146's two tests, which this
  spec rewrites.

## Rabbit holes

- *Why DuckDB's JSON functions cost so much on large values* → not chased. The probes show
  the file reader avoids it; the cause is recorded as an open question, and a report to
  DuckDB is a follow-up the owner may choose.
- *Parsing only the fields a model needs, per model* → no. One structure per endpoint
  (ADR 0068), the union of what its models read; the probes show the whole union parses
  in seconds.
- *Reading only the newest capture of each entity* → no. The glob parses every committed
  capture of the endpoint and staging dedups as today (ADR 0067); superseded snapshots
  cost about 25% more boxscores and almost nothing else.
- *Removing the loader* → no. It is still where the landing zone is listed through
  `LandingZone`, keys are checked for collisions (ADR 0011) and the manifest is written.
- *Rewriting the small endpoints' models to declared structures* → no. They read the whole
  document as `payload` and keep their SQL; together they are about 0.13 GB.

## Requirements

### R1. The raw table is a manifest of committed captures

The loader records which captures exist and what identifies them; it stores no payloads.

- R1.1 THE SYSTEM SHALL keep, in the DuckDB warehouse, a table `raw.captures` with one row
  per committed capture and the columns `source`, `endpoint`, `request_path`,
  `request_key`, `fetched_at`, `partitions` (JSON) and `file_path`, and no payload.
- R1.2 THE SYSTEM SHALL store `file_path` relative to the landing root
  (`espn/roster/season=2026/…/fetched_at=…Z/payload.json`).
- R1.3 WHEN `front-office load` runs THE SYSTEM SHALL insert a row for every committed
  capture listed by `LandingZone.iter_landed` that is not already present, without
  reading any payload.
- R1.4 IF two different files share one key (ADR 0011) THEN THE SYSTEM SHALL refuse the
  load, insert nothing and name both files, as today.
- R1.5 IF the warehouse holds a `raw.api_responses` table THEN THE SYSTEM SHALL refuse to
  load, change nothing, and say to load into a new warehouse file.
- R1.6 THE SYSTEM SHALL keep `raw.captures` append-only: no load replaces or deletes a row.
- R1.7 IF a committed capture's `fetched_at` is not of the form `%Y%m%dT%H%M%SZ` THEN THE
  SYSTEM SHALL refuse the load, insert nothing and name the capture, so every row of
  `raw.captures` is one the glob of R2.1 matches.

### R2. A model reads only committed, loaded captures

- R2.1 THE SYSTEM SHALL read payload files only through a glob that matches committed
  capture directories alone: `<root>/<source>/<endpoint>/**/fetched_at=*Z/payload.json`,
  where the stamp ends in `Z` and a temporary directory (`….tmp-<pid>`) does not.
- R2.2 THE SYSTEM SHALL inner-join what the glob reads to `raw.captures` on `file_path`,
  so a file the loader has not recorded never contributes a row.
- R2.3 IF a payload file the glob matches does not parse, recorded in `raw.captures` or
  not, THEN THE SYSTEM SHALL fail the model that reads it, naming the file. (DuckDB opens
  every matched file before the join; `front-office repair` moves such a file to the
  quarantine, as it does today.)
- R2.4 WHEN an endpoint has no committed capture under the landing root THE SYSTEM SHALL
  give that endpoint's capture view zero rows with its full column set, not an error.
- R2.5 THE SYSTEM SHALL take the landing root from the target: an environment variable
  for each of `dev` and `ci`, defaulting to the repository's `data/raw` and
  `fixtures/landing`.

### R3. One capture view per endpoint

- R3.1 THE SYSTEM SHALL have one view per endpoint, `stg_raw__<source>_<endpoint>`, with
  one row per committed, loaded capture and the manifest's columns.
- R3.2 WHERE the endpoint is `espn/roster`, `espn/matchup_days` or `mlb/boxscore` THE
  SYSTEM SHALL add the fields its staging models read, parsed with one declared structure
  per endpoint, and no `payload` column.
- R3.3 WHERE the endpoint is any other THE SYSTEM SHALL add `payload`, the whole document
  as one JSON value, one row per capture even when the document is a JSON array.
- R3.4 THE SYSTEM SHALL write the file read only inside a dispatched `fo_*` macro, so no
  model or view names `read_json` itself.
- R3.5 THE SYSTEM SHALL have every staging model and every singular test that reads
  captures read them through these views, and none through a raw table.
- R3.6 THE SYSTEM SHALL choose the newest capture of an entity from `raw.captures`'
  columns alone, and apply the choice to a capture view by a semi-join on `file_path`,
  never by ranking parsed rows. (Ranking parsed rosters ran out of memory at 2 GB;
  choosing on the manifest gave the same rows in 0.18 GB, C19.)

### R4. Built whole, not by season

- R4.1 THE SYSTEM SHALL build `stg_mlb__batting_game_logs`, `stg_mlb__pitching_game_logs`,
  `stg_espn__roster_entries`, `stg_espn__roster_entry_slots`,
  `stg_espn__player_game_stats` and `stg_espn__matchup_days` as plain tables on both
  warehouses, with no microbatch configuration.
- R4.2 THE SYSTEM SHALL remove what existed only for batching: `stg_raw__season_responses`,
  the `season_start` column, the `first_season_start` variable,
  `fo_batches_back_to_first_season`, the three tests that guard batching
  (`stg__batched_models_hold_every_season_with_captures`,
  `stg__batched_rows_are_filed_under_their_own_season`,
  `stg_mlb__a_boxscore_game_is_captured_under_one_season`) and `test_dbt_batched_models.py`.

### R5. BigQuery reads the same way, from its uploaded table

- R5.1 WHEN the target is BigQuery THE SYSTEM SHALL build each capture view from the
  uploaded `raw.api_responses`, giving the same columns as on DuckDB.
- R5.2 THE SYSTEM SHALL have the BigQuery upload read payloads from the landing zone
  through `LandingZone` and keys from `raw.captures`, keeping its privacy check and its
  projections (ADRs 0054, 0061).
- R5.3 WHEN the slice is built on BigQuery THE SYSTEM SHALL give relations equal to
  DuckDB's under `compare_bigquery_slice.py`, as before.
- R5.4 WHERE a declared structure has a map (a boxscore side's players, a game line's
  stats) THE SYSTEM SHALL give it on BigQuery as an array of key–value structs, and models
  SHALL read maps only through dispatched `fo_map_*` macros. (`bigquery__fo_json_parse`
  accepts no map today.)

### R6. The bar

- R6.1 WHEN the warehouse is empty and every landed season is under the landing root THE
  SYSTEM SHALL complete `front-office load` and `dbt build` with the committed profile on
  the development machine (29 GB), and `dbt test` SHALL run every test to a result: none
  errors for memory or any other cause than its own assertion, every test that passes
  today passes, and the only failures are the four other tests #147 lists, with today's
  rows. ("Pass" in R6.2 and ADR 0065 means this.)
- R6.2 THE SYSTEM SHALL pass load, build and test under the same smallest DuckDB memory
  limit, on the ladder 1, 2, 4, 8 GB, for a landing root holding 2026 alone as for one
  holding all eight seasons.
- R6.3 THE SYSTEM SHALL give every relation of today's eight-season warehouse
  (`data/warehouse_83.duckdb`) the same rows, under `scripts/compare_warehouses.py`,
  except the relations R4.2 removes and `raw.api_responses`, and except the column
  `season_start` of the six models; the comparison names these exclusions and fails on
  any other missing relation or column.
- R6.4 THE SYSTEM SHALL pass `stg_espn__payload_identity_matches_partitions` and
  `stg_mlb__batting_totals_match_team_stats` on the eight seasons (closes #146).

### R7. Documentation follows the design

- R7.1 THE SYSTEM SHALL state in AGENTS.md how the landing zone is read by dbt (the glob of
  R2.1, joined to the manifest), replacing "never glob by hand" for this one reader, and
  remove the section on batched models.
- R7.2 THE SYSTEM SHALL remove the README's local-profile recipe for many seasons, and say
  how `FO_LANDING_ROOT` is set.

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| `raw.captures` rows after a load of `data/raw` | 27,417 | `select count(*) from raw.captures`; equals committed captures on disk (C11) |
| Every relation against today's warehouse | identical, every relation | `scripts/compare_warehouses.py` against `data/warehouse_83.duckdb` |
| `stg_espn__roster_entries` | 437,227 rows | the comparison above; probe C6 gave the same from files |
| `stg_espn__player_game_stats` | 7,526,702 rows | as above, probe C8 |
| `stg_espn__matchup_days` | 1,469 rows | as above, probe C9 |
| `stg_mlb__batting_game_logs` | 437,977 rows (the file read gives 437,978 before the model's dedup: game 746942 lists player 643376 on both sides) | as above, probe C7 and C10 |
| Load from scratch, eight seasons | passes under 1 GB; seconds | `/usr/bin/time` around `front-office load` with `memory_limit` set |
| Smallest limit, load + build + test | the same rung for 2026 alone and for eight seasons | the ladder of R6.2, recorded on #150 |
| `dbt test`, eight seasons | every test passing today passes; #146's two pass; the four other failures #147 lists (as updated 2026-10-14) fail with the same rows | `dbt test` on the new warehouse |
| CI and gates | green; tenant isolation 0 differences | `.agentic/gates` |
| BigQuery slice on 2026 | every relation equal; bytes billed within 5% of 6.277 GB | `compare_bigquery_slice.py`; the job's billed bytes |
