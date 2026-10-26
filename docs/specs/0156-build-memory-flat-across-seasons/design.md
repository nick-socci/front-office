# A full build's memory does not grow with the captures loaded — design

Issue: #156 · Requirements: [requirements.md](requirements.md) · Tasks: [tasks.md](tasks.md)

## Overview

Three causes were measured, and the build changes once for each.

1. **Heavy nodes share one limit.** dbt builds four nodes at once on one DuckDB instance,
   and each streaming parse needs about 1.5 GB at DuckDB's default 16 threads (C8, C12).
   The `dev` profile builds one node at a time on four DuckDB threads (ADR 0100), so a
   build needs what its heaviest node needs alone, and that floor drops to 0.5 GB.
2. **Some plans gather a whole parse.** Seven nodes have a delim join or a materialized
   CTE over a heavy endpoint's read, and those are the nodes that grow (C5 to C7). Four
   are rewritten so the parse streams. The game-log models and their totals test are
   registered as exempt instead: at four threads they grow from 0.5 to 0.75 GB, and every
   shape without their shared CTE measured costs more (C15). The MLB schedule, read as
   megabyte JSON values through a view, gets a declared structure (ADR 0101).
3. **Nothing in CI would see it come back.** A gate step runs `explain` on every node
   that parses a heavy endpoint and fails on a gathering operator over that read, unless
   a register lists it with its measured limits (ADR 0102). The fixtures give the real
   season's plans (C13).

The target, from C20, C21 and C24: 1 GB for 2026 and for eight seasons, which meets ADR
0065's bar. Rows do not change.

## Claims ledger

Every statement this spec makes about the data and the build, with what showed it. All run
on the development machine (16 cores, 29 GB), DuckDB 1.5.5, dbt-duckdb 1.11.0, on `main`
at 827971c unless a row says otherwise. "Smallest limit" is the first passing rung of
0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4 GB (`probes/node_memory.py`, one node alone, one dbt
thread) or of 1, 2, 4, 8 GB (`probes/ladder.sh`, a full build from empty). Roots:
`data/raw_2026` (2026 alone) and `data/raw` (eight seasons).

| # | Claim | Query (or script) | Result | Run on |
|---|---|---|---|---|
| C1 | Eight seasons hold 44,426 captures, 41,394 of them boxscores: two per game for 2018 and 2021–2025, three for 2019, about two for 2026. #156 was measured on 27,417 captures (about 24,000 boxscores). | `select endpoint, partitions->>'season', count(*), count(distinct request_key) from raw.captures group by all` after `front-office load` of `data/raw` | 2018 4,862 / 2,431 games; 2019 7,286 / 2,429; 2021–2025 about 4,860 / 2,430 each; 2026 4,950 / 2,430; matchup days and rosters one per scoring period | 2026-10-25 |
| C2 | The past seasons' second boxscore captures were fetched 2026-10-12/13 and 2026-10-19/20, and mostly match the first byte for byte; where they differ, staging already reads the newer. | 40 random games per season, SHA-256 of each capture's bytes and of its parsed JSON (sorted keys) | identical content in 40/40 games for 2019, 2022–2025; 39/40 in 2018; 37/40 in 2021; 2026 (in-season settling, 2026-09-26 to 10-07) 38/40 | 2026-10-25 |
| C3 | The full build's smallest limit on `main` with the committed profile is 2 GB for 2026 and 4 GB for eight seasons. | `probes/ladder.sh`, `RUNGS="2 4 8"` | 2026: 2 GB pass (57 s, peak 2.2 GB). Eight seasons: 2 GB fails (15 errors), 4 GB passes (226 s, peak 5.5 GB, 790 results, no failure) | 2026-10-25 |
| C4 | Thirteen nodes parse a heavy endpoint's files (reach `stg_raw__espn_roster`, `stg_raw__espn_matchup_days` or `stg_raw__mlb_boxscore` through views only): seven models and six singular tests. | `probes/plan_shapes.py` on the eight-season build's warehouse and target | models: matchup_days, matchup_player_lines, player_game_stats, roster_entries, roster_entry_slots, batting_game_logs, pitching_game_logs; tests: matchup_days_answer_the_period_asked, matchup_days_mark_one_period, matchup_player_lines_one_line_per_player, payload_identity_matches_partitions, batting_totals_match_team_stats, capture_views_cover_the_manifest | 2026-10-25 |
| C5 | Seven of the thirteen have, in their plan, an operator that gathers its whole input over a read of a heavy endpoint's files: a delim join or a materialized CTE. | `probes/plan_shapes.py` (`explain (format json)`; an operator's endpoints are those its subtree's `raw.captures` scans filter on) | delim join over matchup days: matchup_days, matchup_player_lines_one_line_per_player; over rosters: player_game_stats (2). CTE over matchup days: matchup_player_lines; over boxscores: batting_game_logs, pitching_game_logs, batting_totals_match_team_stats. None in the other six | 2026-10-25 |
| C6 | Each node's smallest limit alone, 2026 → eight seasons, at DuckDB's default 16 threads and at 4. | `probes/node_memory.py --threads 16` and `--threads 4`, on each root's own full build | matchup_days 0.5→2 / 0.5→1.5; matchup_player_lines 1.5→2 / 0.5→1; player_game_stats 0.5→1 / 0.25→0.5; batting_game_logs 1.5→3 / 0.5→0.75; pitching_game_logs 1.5→3 / 0.5→0.75; batting_totals test 1→2 / 0.5→0.75; capture_views_cover test 1→1.5 / 0.5→0.5; roster_entries, roster_entry_slots, answer_the_period_asked, mark_one_period, payload_identity 1.5→1.5 / 0.5→0.5 | 2026-10-25 |
| C7 | Every node of C6 whose smallest limit grows has a gathering operator over a heavy read (C5), and every node with neither is flat, with one exception at 16 threads only (capture_views_cover, 1→1.5, flat at 4). | C5 against C6 | as stated | 2026-10-25 |
| C8 | A node that streams needs about 1.5 GB at 16 DuckDB threads and 0.5 GB at 4, for 2026 as for eight seasons. Its failures below that come within a second, at a resident peak near 0.1–0.2 GB: memory reserved, not filled. | C6's flat nodes; failing rungs' messages | e.g. matchup days rewritten (C9) at 1 GB, 16 threads: "failed to allocate 4.0 KiB (962.7 MiB/953.6 MiB used)" after 0.0 s, peak 0.21 GB | 2026-10-25 |
| C9 | DuckDB plans `cross join unnest(...)` as a delim join when a WHERE comparing a column or a struct field applies to the joined rows (even a left-side column), or when the list is a struct field; with no such WHERE it streams as `UNNEST`. A WHERE on a JSON-function expression over the unnested element did not cause it (batting game logs, `stg_mlb__games`: C5, C25). Carrying the condition as a column and applying it after a `group by` (`having max(is_marked) = 1`) keeps the unnest streaming. | `explain` of small queries over a 10-row table; then `stg_espn__matchup_days` rewritten that way (prototype worktree) | delim join: filter on an element's struct field, the same filter in a later CTE, filter on a left-side column, struct-field list, left join on true. Stream: no filter. Matchup days rewritten: same rows as `main` on eight seasons (except-all both ways: 0 and 0); 2026 → eight seasons 1.5→1.5 GB at 16 threads, 0.5→0.5 at 4; 0.8 s instead of 5.6 s; peak 0.13 GB at 4 threads | 2026-10-25 |
| C10 | The JSON reader's `maximum_object_size` does not move a node's smallest limit. | batting game logs over the boxscore view inlined with `maximum_object_size` 16 MB (default), 8 MB, 1 MB, 16 threads | 3 GB for 2026 at each value | 2026-10-25 |
| C11 | DuckDB's `common_subplan` optimizer turns a repeated subplan that contains a join into a materialized CTE even when the SQL says `as not materialized`, and even when the subquery is written out twice. Disabling it removes the CTE scan only when the CTE is also written out per use. | `explain` of small queries with `set disabled_optimizers`; the batting model with `not materialized`, then inlined per branch | small queries: CTE scan with `not materialized` unless `common_subplan` is disabled. Batting: `not materialized` alone, or with `common_subplan` disabled, keeps 2 CTE scans; inlined per branch with it disabled has none | 2026-10-25 |
| C12 | dbt-duckdb gives every dbt thread a cursor on one DuckDB connection, so `memory_limit` and DuckDB's `threads` are one setting for every node building at the same moment. | `dbt/adapters/duckdb/environments/local.py` (`handle()` returns `self.conn.cursor()`) | as stated | 2026-10-25 |
| C13 | The CI fixtures give the same result as eight seasons: the same 41 nodes parse a heavy endpoint (the schedule included, ADR 0101) and the same seven gather one. | `probes/plan_shapes.py` on a fixture build (`front-office load --raw-root fixtures/landing`, `dbt build --target ci`) and on C20's eight-season build | both: 41 nodes; the seven of C5, with the same operators over the same endpoints | 2026-10-25 |
| C14 | The lineup solver takes 136 s of the 226 s eight-season build (17 s of 57 s for 2026); the build's node times sum to 440 s (133 s). | `run_results.json` of C3's passing builds | as stated | 2026-10-25 |
| C15 | Three growth-free shapes of the game-log models were measured; each raises their floor. | `probes/node_memory.py`, batting and pitching; each shape gives `main`'s rows on 2026 (except-all both ways) | Two sides as a list of two structs, unnested: 4 threads 1→1 (batting), 2→2 (pitching); 16 threads 3→above 3. Newest boxscores written out per branch, `common_subplan` disabled: 4 threads 1→1; 16 threads 2→above 3. A constant two-row list of sides, players chosen by CASE: 4 threads 1→1 / 2→2, 39 s for batting; in a full build with 4 DuckDB threads, eight seasons failed at 4 GB on pitching (42 s, out of memory) | 2026-10-25 |
| C16 | With 4 DuckDB threads in the profile and nothing else changed, the full build needs more, not less: eight seasons 8 GB (304 s); 2026 2 GB (63 s). | `probes/ladder.sh` with `DTHREADS=4` | eight seasons: 2 GB fails (10 errors), 4 GB fails (player_game_stats, stg_mlb__games tests), 8 GB passes, peak 8.4 GB | 2026-10-25 |
| C17 | With matchup days rewritten as in C9 and 4 DuckDB threads, the full build needs 2 GB for 2026 and 4 GB for eight seasons: one rung less than C16, and the same rungs as `main` with the committed profile (C3). | `probes/ladder.sh` with `DTHREADS=4`, in a worktree of `main` with only `stg_espn__matchup_days.sql` changed | 2026: 1 GB fails, 2 GB passes (57 s). Eight seasons: 2 GB fails (player_game_stats among 11 errors), 4 GB passes (209 s, peak 5.0 GB) | 2026-10-25 |
| C18 | With 1 DuckDB thread (4 dbt threads), `main` needs 2 GB for 2026 and more than 2 GB for eight seasons. | `probes/ladder.sh`, profile with DuckDB `threads: 1` (a run meant to set dbt's threads; the script set DuckDB's, fixed since) | 2026: 1 GB fails (4 errors), 2 GB passes (54 s). Eight seasons: 1 and 2 GB fail; 4 GB not run | 2026-10-25 |
| C19 | The six heavy models, run one after another in one DuckDB instance at 2 GB and 4 threads over eight seasons, all pass, and the buffer pool holds only table data between them. | `probes/sequence_memory.py` against C16's eight-season warehouse, with the external file cache on and off | each passes (2.5–18 s); `duckdb_memory()` after each: base tables 8 → 79 MB, nothing else above 1 MB; the same with the cache off | 2026-10-25 |
| C20 | With 1 dbt thread and 4 DuckDB threads, `main` needs 1 GB for 2026 and 2 GB for eight seasons, a rung below the committed profile for both (C3), at 72 s and 305 s. | `probes/ladder.sh`, `THREADS=1 DTHREADS=4` | 2026: 1 GB passes (72 s, peak 1.2 GB). Eight seasons: 1 GB fails (matchup_days and two `stg_mlb` tests), 2 GB passes (305 s, peak 2.8 GB) | 2026-10-25 |
| C21 | With 1 dbt thread, 4 DuckDB threads and matchup days rewritten (C9), eight seasons at 1 GB fails only on two tests that read the MLB schedule; 2026 passes at 1 GB. | as C20, in C17's worktree | 2026: 1 GB passes (77 s). Eight seasons at 1 GB: 2 errors, `stg_mlb__games_prefers_played_over_unplayed` and `stg_mlb__no_stats_for_unplayed_games` (out of memory at 0.94 of 0.95 GB) | 2026-10-25 |
| C22 | Those two tests grow with seasons with no delim join or CTE scan in their plan: they read `stg_raw__mlb_schedule`, whose 20 captures (4 for 2026) are each over 1 MB, as a whole JSON `payload`. | `probes/node_memory.py --threads 4` on C20's builds; `probes/plan_shapes.py`-style `explain`; `find data/raw/mlb/schedule -name payload.json -size +1M` | prefers_played_over_unplayed 0.5 → 1.5 GB; no_stats_for_unplayed_games 0.75 → 1.5 GB; delim joins 0, CTE scans 0; 20 of 20 schedule payloads over 1 MB, 66 MB in all | 2026-10-25 |
| C23 | With 1 dbt thread and DuckDB's default 16 threads (matchup days rewritten), eight seasons fails at 2 GB on the two game-log models alone; 2026 passes at 2 GB (73 s). | `probes/ladder.sh`, `THREADS=1`, in C17's worktree | 2026: 1 GB fails, 2 GB passes. Eight seasons: 1 GB fails (8 errors), 2 GB fails (batting and pitching game logs only); 4 GB not run | 2026-10-25 |
| C24 | Read with `dates[].games[]` declared and each game kept as JSON, the MLB schedule needs the same limit for both roots and gives the same rows; read as a whole payload it grows. `stg_mlb__games`, which reads it, is a view, so every node that reads `stg_mlb__games` parses the schedule again. | `probes/schedule_shape.py` (4 DuckDB threads); `materialized` of `stg_mlb__games` in the build's manifest | payload: 0.5 GB (2026) → 0.75 GB (eight seasons); structure: 0.5 → 0.5 GB; distinct (game, state) pairs / distinct games: 2,486 / 2,430 (2026) and 20,780 / 20,342 (eight seasons), both ways; `stg_mlb__games` is a view | 2026-10-25 |
| C25 | 29 nodes parse the MLB schedule (through `stg_mlb__games`, a view); none gathers over it. Three `stg_espn__scoring_periods_*` tests have a delim join or CTE, but over `espn/settings`, a small endpoint. | `probes/plan_shapes.py` with the schedule as the only heavy endpoint, then with every endpoint | schedule readers: 29, gathering over the schedule: 0. scoring_periods_start_on_opening_day, _have_game_lines_to_check, _agree_with_espn_game_lines: CTE or delim join over `settings` only | 2026-10-25 |

## Alternatives considered

| | A: serial profile, streaming rewrites, plan check (chosen) | B: today's profile, rewrites only | C: batch the heavy models by season again | D: DuckDB for CI only, history on BigQuery |
|---|---|---|---|---|
| Bar met, as measured | 1 / 2 GB on `main` (C20); 1 GB for both expected once the schedule streams (C21, C24) | not shown: the game logs alone need 3 GB at 16 threads (C6, C15) | not measured | the bar is dropped |
| Committed configuration works as committed | yes, a thread count in `dev` | yes | yes | n/a |
| Real-season build time | 72 s / ~300 s, from 57 s / 226 s (C3, C20) | unchanged | unknown; ADR 0069 removed batching for its cost | n/a |
| CI holds the cause | yes, the plan check (C13) | yes, if the check is added | no | no |
| Rework | four models, one view, one gate step | as A without the profile | the machinery ADRs 0058–0060 had, back | every real-data check billed |

**A — chosen.** It is the only combination measured to bring both roots to the same rung,
and the two other parts are what make the rung low and keep it there.

**B — today's profile with the rewrites.** At 16 DuckDB threads every streaming node needs
about 1.5 GB and the game logs 3 GB for eight seasons; dbt's four threads add those up
(C16, C17). No rewrite of the game logs measured brings them under that (C15).

**C — batching by season.** ADR 0069 removed it and said it could come back for one model,
by a new ADR, if the ladder showed the need. A batch bounds the rows a model parses at a
time, but not DuckDB's per-thread floor or the overlap of nodes, which are what the ladder
shows (C8, C16); and it brings back a guard against seasons outside a batch.

**D — leave the history to BigQuery.** ADR 0065 rejected it on 2026-10-14; nothing here
reopens it.

## Decisions

| ADR | Decision | Status |
|---|---|---|
| [0100](../../adr/0100-the-development-build-runs-one-node-at-a-time-on-four-duckdb-threads.md) | The `dev` target builds one node at a time (dbt `threads: 1`) on four DuckDB threads; `ci` and `bq` unchanged (owner, 2026-10-25) | accepted |
| [0101](../../adr/0101-the-mlb-schedule-is-read-with-a-declared-structure.md) | `stg_raw__mlb_schedule` declares `dates[].games[]`, each game kept as JSON; the schedule joins the heavy endpoints (owner, 2026-10-25) | accepted |
| [0102](../../adr/0102-a-node-that-parses-a-heavy-endpoint-may-not-gather-the-parse-unless-registered.md) | A gate step fails a node that parses a heavy endpoint and whose plan has a delim join or CTE scan, unless a register lists it with its measured limits; the game logs and the batting-totals test start in it (owner, 2026-10-25) | accepted |

## Detailed design

### The `dev` profile (R1, ADR 0100)

`dbt/profiles.yml`, target `dev`: `threads: 1`, and `settings: {threads: 4}` (DuckDB's
threads). A comment says why and points to ADR 0100. `ci` and `bq` are unchanged. No
memory limit is set.

### Nodes that gather a heavy parse (R2)

Each rewrite gives exactly the rows `main` gives (`scripts/compare_warehouses.py`, every
relation) and leaves no gathering operator over a heavy read in its plan (the check of
R4). The rule the rewrites follow, from C9 and C11:

- a WHERE comparing a column or struct field of the rows of a `cross join unnest` of
  parsed captures makes DuckDB gather them; the condition is carried as a column and
  applied after a `group by` (or another operator DuckDB does not push a filter
  through). Which filters DuckDB pushes is its optimizer's choice, so the plan check, not
  this rule, is what decides;
- a CTE of parsed captures read more than once is materialized, whatever the SQL says;
  what is needed from it twice is read once, or taken from `raw.captures` instead.

| Node | Today (C5) | Change |
|---|---|---|
| `stg_espn__matchup_days` | delim join: the marker is a WHERE over the unnested matchups | the marker becomes `is_marked`; `group by` the five output columns, `having max(is_marked) = 1` (prototyped, C9) |
| `stg_espn__matchup_player_lines` | CTE: `latest` (parsed matchup-days captures) is read by `newest` and by `header` | `newest` takes `file_path`, league, season and scoring period from `fo_capture_keys()` (the manifest), so the parsed captures are read once |
| `stg_espn__player_game_stats` | two delim joins: the game-line filter (`statSourceId`, `statSplitTypeId`, `scoringPeriodId`) is a WHERE over unnested lines | the filter is applied where DuckDB keeps the unnest streaming; the shape is found in the build and held by R4 |
| `stg_espn__matchup_player_lines_one_line_per_player` (test) | delim join over matchup days | as for the model it checks |
| `stg_mlb__batting_game_logs`, `stg_mlb__pitching_game_logs`, `stg_mlb__batting_totals_match_team_stats` | CTE: the newest boxscores, read once per side | unchanged; registered (R4.3) |

If no streaming shape of `stg_espn__player_game_stats` or the test gives the same rows,
that node is proposed to the owner as an exemption, with its measurement (C6: 0.25 →
0.5 GB at four threads), as an amendment.

### The MLB schedule (R3, ADR 0101)

`stg_raw__mlb_schedule` declares `{"dates": [{"games": ["JSON"]}]}` and gives no `payload`.
`stg_mlb__games` takes its games from `dates[].games[]` (two unnests) instead of
`fo_json_array('payload', '$.dates[*].games[*]')`, and reads each game with the same
`fo_json_*` expressions as today; its filter on `gameType` stays a JSON-function
expression, which does not make DuckDB gather today (C25), and the plan check holds it. `stg_mlb__games_prefers_played_over_unplayed` does the
same. The unit tests that mock `stg_raw__mlb_schedule` give `dates` instead of `payload`.
`scripts/compare_warehouses.py` does not compare JSON values and the view's column
changes, so the view is compared on its own (R3.4): per capture, the games of `main`'s
`payload` under `$.dates[*].games[*]` against the new `dates[].games[]`, each game's JSON
with its keys sorted, as multisets. Every other relation is compared with
`--strict-columns`, excluding only the view's `payload` and `dates` (R6.3).
On BigQuery the view parses the same structure from the uploaded payload
(`bigquery__fo_captures`), so `bigquery_slice` builds it, and the slice comparison holds.

### The plan check (R4, ADR 0102)

`scripts/check_plan_shapes.py`, a gate step after "planted failures" (it reads the fixture
build's `dbt/ci.duckdb` and `dbt/target/manifest.json`), and the same step in CI.

- **Heavy endpoints** are the capture views that declare a structure: in the manifest, the
  model's source (`raw_code`) calls `fo_captures` with a third argument. Not the compiled
  SQL: an endpoint with no captures under the landing root compiles to a typed empty
  query with no file read (`duckdb__fo_captures`), so a structured endpoint CI holds no
  captures of would be missed. A new heavy endpoint is covered without a list to keep.
- **Readers** are the models and tests that reach a heavy capture view through views and
  ephemerals alone (a table between them was parsed when it was built).
- For each reader, `explain (format json)` of its compiled SQL. A **gathering operator** is
  a node of the plan whose name contains `DELIM_JOIN`, or is `CTE`. Its **endpoints** are
  those named by `endpoint='…'` filters on scans of `raw.captures` in its subtree, when
  the subtree also reads files. It fails when one is heavy.
- **Register**: `dbt/plan_shapes.yml`, entries of `node`, `operator`, `endpoint`, `reason`,
  `link` (an ADR) and `measured` (`threads`, `gb_2026`, `gb_all_seasons`, `on`). The
  check fails on an unregistered gathering operator, on a registered entry whose node no
  longer has it (so an entry cannot outlive its reason), and on an entry naming no node.
  It starts with the three nodes of the last row above.
- Every problem is printed, not just the first; exit 1 if any. The parts that take a plan
  and a manifest are pure functions, tested by pytest without dbt, as `check_plants.py`
  is.

### Documentation (R5)

AGENTS.md, *dbt gotchas*: one bullet on the two shapes and the check, and that the `dev`
profile is serial on purpose (ADR 0100). The probes of this spec stay in its `probes/`;
the ladder (`probes/ladder.sh`) is how the bar is checked.

## Test strategy

| Requirement | Test | Catches |
|---|---|---|
| R1.1 | the ladder on both roots (`probes/ladder.sh`, committed profile) | the profile not applied, or not enough |
| R2.1, R3.2, R6.3 | `scripts/compare_warehouses.py --strict-columns` against a warehouse of `main`, the schedule view's two columns excluded | a rewrite that changes a row or a column |
| R3.4 | the schedule view's games, canonical JSON, as multisets per capture, against `main` | the structure dropping or changing a game, which the comparison above cannot see in a JSON column |
| R2.2, R4.1 | `check_plan_shapes.py` in the gates, on fixtures | a gathering operator over a heavy read, now or later |
| R3.1 | `test_capture_glob.py` gains the schedule's structure; `stg_raw__capture_views_cover_the_manifest` | the structure dropping a capture or a field |
| R3.3 | `stg_mlb__games`' unit tests, mock rows in the new structure | the games read from `dates[].games[]` differently |
| R4.2, R4.3, R4.4 | pytest of the check's pure parts: a delim join over a heavy read fails; over a small one passes; a registered one passes; a stale entry fails; a CTE over a heavy read fails | the check passing what it should fail, or the reverse |
| R4.5 | the check run on the fixture build after the rewrites | the register holding more or fewer than the three exempt nodes |
| R3.5, R6 | the ladder and `dbt test` on both roots; `compare_bigquery_slice.py` | the bar, the known failures, BigQuery |

## Risks

- No streaming shape of `stg_espn__player_game_stats` gives today's rows — medium — it is
  0.25 → 0.5 GB at four threads (C6), under the 1 GB rung; it goes to the owner as a
  proposed exemption with that measurement.
- A DuckDB upgrade changes plans — likely over time — the check fails or passes without a
  SQL change; that is what the memory follows, so the register is reviewed at an upgrade
  (ADR 0102).
- Another node, hidden at 2 GB, fails eight seasons at 1 GB once the schedule streams —
  low (C21 found only the two schedule tests) — the bar is equality, so 2 GB for both
  still meets it; a new cause is measured and brought to the owner.
- The `dev` and `ci` targets differ in concurrency — low — no two nodes write one
  relation; CI keeps four threads for time.
- Unit tests mocking a nested column in dbt's YAML rows — unknown, not tried — if the rows
  format cannot express `dates`, the mock uses `format: sql`.
- The real-season build is slower (C20) — certain — accepted by the owner (ADR 0100).

## Open questions

- Why a streaming parse reserves about 0.1 GB per DuckDB thread (C8) → not traced; C10 rules
  out the JSON reader's object buffer. A report to DuckDB is the owner's choice.
- Whether eight seasons reaches 1 GB once the schedule streams → expected from C21 and
  C24, not yet measured end to end; the build's last task measures it.

## Review log

| Source | Finding | Resolution |
|---|---|---|
| design-review | F1 (P0): the schedule probe globbed landing files, against AGENTS.md's rule | changed: `probes/schedule_shape.py` lists captures with `LandingZone.iter_landed` and reads that list; re-run, same results (C24) |
| design-review | F2 (P1): the ladder inserted a second `settings:` into a profile that will have one (ADR 0100), losing the memory limit, and its thread edit could hit `ci` | changed: `probes/ladder.sh` edits the profile as YAML and asserts the limit and threads it set, and that every other target is unchanged; checked on today's profile and on ADR 0100's, and `dbt debug` reads the result |
| design-review | F3 (P1): the warehouse comparison cannot show the schedule view unchanged (JSON not compared; one-sided columns pass) | changed: R3.4 compares the view's games as canonical JSON multisets per capture; R6.3 uses `--strict-columns`, excluding only the view's `payload` and `dates` |
| design-review | F4 (P2): finding heavy views from compiled SQL misses an endpoint with no fixture captures | changed: heavy views are found from the model's source (`fo_captures` with a structure), R4.1 and *The plan check* |

## Amendments
- **2026-10-26, the shape of `stg_espn__player_game_stats` and of
  `stg_espn__matchup_player_lines_one_line_per_player` (task 6).** *Detailed design* left
  the shape to the build. Each delim join had one cause (C9): the WHERE on the game lines'
  struct fields, and `fo_unnest_pair`, a subquery DuckDB plans the same way. The game lines
  are now chosen before the unnest by a new dispatched macro, `fo_list_filter` (DuckDB
  `list_filter` with a lambda; BigQuery `array(select … where …)`), and a line's `stats`
  is declared in `stg_raw__espn_roster` as a map of JSON, unnested by `fo_map_entries` as
  the boxscore's players are. Only this model reads that field; the roster unit tests'
  `from_json` specs follow the declared type. On eight seasons: `stg_espn__player_game_stats`,
  `stg_espn__roster_entries` and `stg_espn__roster_entry_slots` identical to `main`
  (6,182,774, 437,227 and 2,348,532 rows, except-all 0 both ways); no gathering operator;
  0.5 GB alone at four threads for 2026 and for eight seasons, 3.4 s instead of 19.9 s.
  The test gives the same per-player line counts as before (343,691 groups, at most one
  line each, except-all 0 both ways) and no gathering operator; alone it needs 0.5 GB at
  four threads where it needed 0.25. Within the goals and no-goes.
- **2026-10-26, the schedule's expected values named the wrong count.** *Expected values*
  gave 20,780 as the schedule's "game entries". C24 counted distinct (game, state) pairs;
  the schedule holds 47,999 game entries over all captures of eight seasons, 20,342
  distinct games (one `stg_mlb__games` row each), both counted again on the baseline
  warehouse. The requirement is unchanged; the row and C24 now say which count is which.
- **2026-10-26, `int_fantasy__candidate_day_values` added to the rewrites (the owner's
  decision).** The branch's first ladder passed 2026 at 1 GB; eight seasons at 1 GB got
  through every heavy staging node and then aborted in this intermediate model (DuckDB's
  out-of-memory exception, uncaught, at 953.4 of 953.6 MiB). It parses no capture: its
  `day_parts` summed the replacement levels with an ordered sum (ADR 0046) per day, and an
  ordered aggregate holds every row it sums, so alone it needed 0.25 GB for 2026 and 1.5 GB
  for eight seasons, at four threads (without the ordering, 0.25 GB: the ordering is the
  cause). Of the 17 nodes with an ordered aggregate, measured alone the same way, no other
  needs more than 0.75 GB for eight seasons (`probes/node_memory.py`). The replacement sum
  depends on the league-season, side and day kind, not on the day, since every day of a
  side meets all its components; it is now summed once per kind and joined, with the same
  terms in the same order. On eight seasons the model and everything downstream are
  identical to `main` (198,363 rows; 62 relations, `probes/compare_bounded.py`), and it
  needs 0.5 GB alone. Reported to the owner, who chose to rewrite it here rather than in a
  separate issue or by narrowing the bar. `probes/compare_bounded.py` compares the
  relations exactly with columns held strict, without materializing the capture views,
  which `scripts/compare_warehouses.py` does and the real season cannot afford (19 GB).
