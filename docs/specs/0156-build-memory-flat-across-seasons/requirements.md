# A full build's memory does not grow with the captures loaded — requirements

Issue: #156 · Tier: M · Status: draft

## Problem

ADR 0065 set the bar for DuckDB as the development warehouse: the smallest DuckDB memory
limit, on the ladder 1, 2, 4, 8 GB, under which load, build and test pass is the same for
a landing root holding one season as for one holding all. Spec 0150 shipped without it
(its R6.2), by the owner's decision of 2026-10-15, and split it to #156.

Measured again on 2026-10-25, on `main` at 827971c and the landing zone as it is today
(design.md, *Claims ledger*): 2026 alone passes at 2 GB and eight seasons at 4 GB (C3).
Two causes, measured node by node (C5 to C13):

- **Plans that hold a whole parse.** Seven of the thirteen nodes that parse the heavy
  endpoints' files (rosters, matchup days, boxscores) have, in their DuckDB plan, an
  operator that gathers every parsed capture before it emits a row: a materialized CTE,
  or a `cross join unnest` DuckDB could not turn into a streaming unnest. Every node that
  needs more memory for eight seasons than for 2026 has one, and none of the nodes that
  need the same has one (C7).
- **A cost per DuckDB thread.** A node that streams still needs about 1.5 GB at DuckDB's
  default of 16 threads and 0.5 GB at 4, for 2026 as for eight seasons (C8). dbt builds
  four nodes at once on one DuckDB instance, which shares one limit (C12).

The landing zone has also grown since #156 was opened: every past season's boxscores were
fetched a second time for verification (2019 a third), so eight seasons hold 41,394
boxscore captures where they held about 24,000 (C1). The owner decided on 2026-10-25 to
keep them: a superseded capture is what the landing zone holds by design (ADR 0015), an
in-season game has about two as it settles, and the bar must hold with them (C2).

## Goals

- The bar of ADR 0065 holds for the full build with the committed profile: the smallest
  rung under which load, `dbt build` and `dbt test` pass is the same for 2026 alone as
  for all eight seasons, on the landing zone as it is.
- No node that parses the heavy endpoints' files holds the parse whole, and CI says so
  when a change brings such a plan back.
- Every model returns the rows it returns today.

## No-gos

- **No change to any row of any model.** The comparison is exact, relation by relation.
- **No change to the landing zone** or to what it holds. The verification captures stay
  (the owner's decision, 2026-10-25); no capture is moved, deleted or skipped.
- **No capture view reads only the newest capture of an entity.** Spec 0150 ruled that out
  (its *Rabbit holes*, ADR 0067), and the owner kept it ruled out on 2026-10-25.
- **No memory limit in the committed profile.**
- **No change to BigQuery's build** beyond what a rewritten model's SQL changes; the slice
  still builds, compares equal and bills within 5% of today.
- **No work on the lineup solver's run time** (136 s of a 226 s eight-season build, C14).
  It is a Python loop over team periods in one thread (`int_fantasy__optimal_lineups.py`,
  `lineup_solver.py`) and parses no capture; its time is a separate question.
- **No new request** to ESPN or MLB.

## Rabbit holes

- *Why DuckDB reserves about 0.1 GB per thread for a streaming parse* → not traced. The
  JSON reader's `maximum_object_size` does not change it (C10). The thread count is the
  lever this spec uses; a report to DuckDB is a follow-up the owner may choose.
- *Disabling DuckDB optimizers* (`common_subplan`, which turns a repeated subplan into a
  materialized CTE even when the SQL says `not materialized`, C11) → no. The setting is
  marked a debug setting, applies to the whole instance, and did not stop the
  materialization in the game-log models on its own.
- *A memory ladder in CI* → no. CI's fixtures are 22 captures; memory cannot grow there.
  The plan check is what CI can hold (C13), and the ladder stays a real-season check.
- *Rewriting the small endpoints' models* (settings, teams, matchups, transactions,
  players, schedule, id map) → no. Their plans have materialized CTEs and delim joins too,
  over payloads that are 0.13 GB in all (spec 0150, C1).

## Requirements

### R1. The development build runs one node at a time on four DuckDB threads

So no two heavy nodes share the memory limit, and a streaming node's floor is 0.5 GB
(ADR 0100).

- R1.1 THE SYSTEM SHALL set, in `dbt/profiles.yml`'s `dev` target, dbt's `threads` to 1
  and DuckDB's `threads` (under `settings`) to 4, and no memory limit.
- R1.2 THE SYSTEM SHALL leave the `ci` and `bq` targets' thread counts as they are.

### R2. No node gathers a heavy parse unless it is registered

- R2.1 THE SYSTEM SHALL give, from `stg_espn__matchup_days`, `stg_espn__matchup_player_lines`,
  `stg_espn__player_game_stats` and the test
  `stg_espn__matchup_player_lines_one_line_per_player`, exactly the rows they give on
  `main`.
- R2.2 THE SYSTEM SHALL plan those four nodes with no delim join and no materialized CTE
  over a read of a heavy endpoint's files.
- R2.3 IF no shape of `stg_espn__player_game_stats` or of the test meets R2.1 and R2.2
  THEN THE SYSTEM SHALL keep the node as it is and bring it to the owner as a proposed
  exemption with its measured limits, as an amendment, before it is registered.

### R3. The MLB schedule is read with a declared structure

- R3.1 THE SYSTEM SHALL give `stg_raw__mlb_schedule` the manifest's columns and `dates`,
  parsed from `{"dates": [{"games": ["JSON"]}]}` as each file is read, and no `payload`
  (ADR 0101).
- R3.2 THE SYSTEM SHALL give, from `stg_mlb__games` and every test that reads the schedule,
  exactly the rows they give on `main`.
- R3.3 THE SYSTEM SHALL read each game with the `fo_json_*` expressions used today, from
  the game's JSON value.
- R3.4 THE SYSTEM SHALL give, from `stg_raw__mlb_schedule`, for every capture, the same
  games as `main`'s view gives in its `payload` under `$.dates[*].games[*]`: compared as
  multisets of (`file_path`, the game's JSON with its keys sorted), since
  `scripts/compare_warehouses.py` does not compare JSON values.
- R3.5 WHEN `bigquery_slice` is built on BigQuery THE SYSTEM SHALL build
  `stg_raw__mlb_schedule` and `stg_mlb__games` from the uploaded table with the same
  columns, and `compare_bigquery_slice.py` SHALL find them equal.

### R4. A gate holds R2 in CI

- R4.1 THE SYSTEM SHALL have a gate step, after the fixture build, that finds every model
  and test reaching a heavy capture view (one that declares a structure) through views
  and ephemerals alone, and runs `explain` on its compiled SQL against `dbt/ci.duckdb`. A capture view declares
  a structure when its source calls `fo_captures` with one, whether or not CI holds
  captures of its endpoint.
- R4.2 IF a found node's plan has a delim join or a materialized CTE whose input reads a
  heavy endpoint's files, and the register does not list that node, operator and
  endpoint, THEN THE SYSTEM SHALL fail the step, naming all three.
- R4.3 THE SYSTEM SHALL keep the register in `dbt/plan_shapes.yml`, each entry naming the
  node, the operator, the endpoint, the reason, an ADR, and the node's measured smallest
  limit alone at four DuckDB threads for 2026 and for all seasons, with the date.
- R4.4 IF a register entry's node no longer has that operator over that endpoint, or no
  such node exists, THEN THE SYSTEM SHALL fail the step, naming the entry.
- R4.5 THE SYSTEM SHALL start the register with `stg_mlb__batting_game_logs`,
  `stg_mlb__pitching_game_logs` and `stg_mlb__batting_totals_match_team_stats` (the
  newest-boxscore CTE, ADR 0102), and no other node.
- R4.6 THE SYSTEM SHALL print every problem the step finds, not only the first.

### R5. Documentation follows

- R5.1 THE SYSTEM SHALL state in AGENTS.md's *dbt gotchas* the two gathering shapes, the
  plan check and its register, and that the `dev` profile is serial on purpose.

### R6. The bar

- R6.1 WHEN the warehouse is empty THE SYSTEM SHALL pass `front-office load` and
  `dbt build` with the committed profile and no override, for 2026 alone and for all
  eight seasons, under the same smallest limit on the ladder 1, 2, 4, 8 GB.
- R6.2 WHEN the build passes THE SYSTEM SHALL fail no test other than those failing on
  `main` today, with their rows.
- R6.3 THE SYSTEM SHALL give every relation of a `main` build of the same landing root the
  same rows and the same columns (`scripts/compare_warehouses.py --strict-columns`),
  excluding only `staging.stg_raw__mlb_schedule:payload` and
  `staging.stg_raw__mlb_schedule:dates`, which R3.4 compares instead.

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| Ladder, 2026 alone, committed profile | 1 GB passes | `probes/ladder.sh`, `ROOTS=raw_2026 RUNGS="1 2"`; C20, C21 |
| Ladder, eight seasons, committed profile | 1 GB passes; if not, the same rung as 2026, and the cause brought to the owner | `probes/ladder.sh`, `ROOTS=raw RUNGS="1 2 4"`; C21, C24 |
| Build time, eight seasons | about 300 s (accepted, ADR 0100) | the ladder's `build exit … s` |
| Every relation against `main` | identical rows and columns, each landing root, the schedule view's two columns excluded | `scripts/compare_warehouses.py --strict-columns --exclude staging.stg_raw__mlb_schedule:payload --exclude staging.stg_raw__mlb_schedule:dates <main build> <new build>` |
| The schedule view's games against `main` | equal multisets, each landing root; 20,780 game entries for eight seasons (C24) | R3.4's comparison |
| `stg_espn__matchup_days`, eight seasons | 1,469 rows | the comparison above; C9 |
| `stg_mlb__games` games, eight seasons | as `main`; the schedule holds 20,780 game entries, 20,342 distinct games | the comparison above; C24 |
| Plan check on fixtures | passes, with three registered entries and no other gathering operator over a heavy read | `scripts/check_plan_shapes.py` |
| Nodes the check reads | 41 on `main`'s fixtures (C13), give or take the nodes the rewrites add or remove | the check's output |
| `dbt test`, eight seasons | the same failures as `main` with the committed profile today: none (C3) | the ladder's `run_results.json` |
| BigQuery slice on 2026 | every relation equal; billed bytes within 5% of the same build of `main` (run with its own `fo_schema_suffix`) | `compare_bigquery_slice.py`; the jobs' billed bytes |
| Gates | green; tenant isolation 0 differences | `.agentic/gates` |
