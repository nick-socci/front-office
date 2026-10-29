# A tie where a ranking cuts stops the build — requirements

Issue: #141 · Tier: M · Status: draft

## Problem

AGENTS.md rule 5 asks every keep-one-row step for a deterministic tie-break, and nothing
holds it. The BigQuery spike (#130) found two steps whose order was not total: MLB listed
games twice under one `game_pk`, and the id map listed a two-way player twice. DuckDB happened
to pick the same row in every build, so the ties were invisible until BigQuery picked the
other one. Both were fixed by the owner's tie-breaks (design.md, C13).

The same kind of tie is in the real season today. The id map lists ESPN id 5214984 twice, as
Jonah Tong and as Michael Tonkin, both `P`, in one capture. `stg_idmap__players`' order
(`fetched_at desc, POS desc`) cannot choose between them (C2, C3). DuckDB keeps Tong, the
player the league rostered 51 times in 2025 and 2026 (C4). A warehouse that kept Tonkin would
give Tong's league days to a retired reliever, and no test would notice.

A tie only matters where a ranking cuts. When rows tie inside a group that is kept whole, or
inside a group that is dropped whole, the result does not depend on which tied row came
first. When the tied rows sit on both sides of the cut, the result depends on row order.

## Goals

- A ranking whose order ties where it cuts stops the build that meets the tie, on DuckDB and
  on BigQuery, and the error names the node and the partition.
- No ranking in a model, test or macro can be written without that check, unless a comment
  says why ties cannot change its result.
- Today's ties are resolved by stated rules, and the real-season warehouse is unchanged.

## No-gos

- No winner changes on the real season (R5.2), except as ADR 0109 states. Under it,
  ESPN id 5214984 leaves the id map, and Tong resolves to the same MLB id
  by name. Only the resolution label of his rows changes.
- Null ordering is not in scope. DuckDB sorts nulls last in both directions, and BigQuery
  sorts them first when ascending, so `order by x` over a nullable `x` can choose
  differently with no tie at all. That is a separate check, proposed as a follow-up issue
  (task 10).
- No data test and no plant. The check lives in the build (ADR 0107), so `dbt/plants/` and
  `check_plants.py` are untouched.
- No proof from SQL text alone that an order is total, by declaring unique keys. Whether an
  order ties depends on the data.
- `fo_latest_boxscore_responses` is unchanged. It keeps every capture of a game at the
  newest `fetched_at`, by design. If two such captures exist, the batting and pitching
  steps meet the tie and stop.
- The order of elements in an `array_agg` (the solver's input, ADR 0104) is not in scope.
- No BigQuery build of real rows is required. The check is shown on BigQuery over literal
  rows (R4.2), and the selector is held by the `--empty` run (R4.3).

## Rabbit holes

- **A harmless tie fails like a harmful one.** If the tied rows are identical in every
  column the step keeps, the order does not matter, but the check cannot see that without
  the output columns. `dim_players.latest_game_names` has 514 such rows: a pitcher's batting
  and pitching lines for one game (C5). → Such rows are made distinct before the ranking. No
  "equal rows may tie" mode is added to the macro.
- **The check's cost.** A second window could double the sort, and some of these steps rank
  parsed captures (ADR 0102). → `rank()` goes over the same window as `row_number()`, and
  DuckDB computes both in one WINDOW operator (C8). On the heaviest step, time and peak
  memory are within run-to-run noise (C9). The plan-shapes gate runs on the build branch.
- **Error functions differ by warehouse.** → They don't here. DuckDB and BigQuery both have
  `error(string)`, and both evaluate it only for the rows that reach the `CASE` branch (C8,
  C10).

## Requirements

### R1. A tie at the cut stops the build

The macros that every ranking goes through.

- R1.1 THE SYSTEM SHALL provide `fo_keep_first(partition_by, order_by, rows=1)`, a `QUALIFY`
  clause. In each partition of `partition_by` (a list, possibly empty), ordered by
  `order_by`, it keeps the rows in places 1 to `rows`. `rows` may be a column expression,
  provided it has one value in each partition.
- R1.1a IF `rows` is not an integer literal and takes more than one value in a partition
  THEN THE SYSTEM SHALL fail the statement with the same error, since the partition then
  has no single cut and a tie could pass unseen.
- R1.2 IF the row in place `rows` + 1 of a partition ranks no lower than place `rows` (a tie
  across the cut) THEN THE SYSTEM SHALL fail the statement. The error names the node, the
  place, and the partition's key values.
- R1.3 WHEN no partition ties across its cut THE SYSTEM SHALL keep exactly the rows that
  `qualify row_number() over (…) <= rows` keeps.
- R1.4 THE SYSTEM SHALL keep `fo_latest_by_entity(partition_by, order_by)` with its
  signature, rendered through `fo_keep_first(partition_by, order_by, 1)`.
- R1.5 THE SYSTEM SHALL provide `fo_row_number(partition_by, order_by)`, an expression equal
  to `row_number()` over that window. IF any two rows of a partition tie THEN it SHALL fail
  the statement, with the same error.
- R1.6 THE SYSTEM SHALL render both macros as one SQL text for DuckDB and BigQuery (no
  dispatch). Both warehouses SHALL raise on a tie and return identical rows otherwise.

### R2. Every order-dependent window goes through them

- R2.1 THE SYSTEM SHALL fail the gates when a model, singular test or macro calls
  `row_number`, `lag`, `lead`, `first_value`, `last_value`, `nth_value` or `ntile` outside
  the bodies of `fo_keep_first` and `fo_row_number`, unless a `tie-exempt:` comment with a
  reason stands on that line or directly above it. `rank`, `dense_rank`, `percent_rank` and
  `cume_dist` give tied rows equal values, and aggregates are held by ADR 0046, so neither
  is checked.
- R2.2 THE SYSTEM SHALL read SQL as `test_dbt_ordered_aggregate_rule.py` does: comments and
  string literals blanked, and the marker alone, or the marker inside a string, exempting
  nothing.
- R2.3 THE SYSTEM SHALL convert every call site in design.md's *Call sites* table to the
  form given there.
- R2.4 AGENTS.md rule 5 SHALL say that a ranking goes through `fo_keep_first` or
  `fo_row_number`, and that a tie where a ranking cuts stops the build.

### R3. Today's ties are resolved by stated rules

- R3.1 WHEN the id map's newest capture lists one ESPN id with more than one distinct MLB
  id THE SYSTEM SHALL leave that id out of the map, so the crosswalk's name fallback
  decides (ADR 0109). The model's comment SHALL say why.
- R3.2 THE SYSTEM SHALL choose the id map's newest capture by `fetched_at desc, file_path
  desc`. `file_path` is unique per capture (C12).
- R3.3 THE SYSTEM SHALL make `dim_players`' game-name candidates distinct before ranking
  them.
- R3.4 A dbt unit test of `stg_idmap__players` SHALL show R3.1 on rows that are not the
  real season's. It covers:
  - a new ESPN id listed with two MLB ids, which is left out;
  - an ESPN id listed twice with one MLB id under two positions, which keeps one row;
  - an older capture that lists an id with another MLB id, while the newest capture lists
    it with one, which is mapped as the newest capture says.

  Like the model's existing unit test, it feeds a `payload` and so cannot run on BigQuery
  (#138).

### R4. The check is shown to fire

- R4.1 A pytest SHALL run `dbt show --inline --target ci` over literal rows, through both
  macros. It SHALL show that:
  - `fo_keep_first` with `rows=1` raises on a tie at place 1 and does not raise on a tie
    at places 2 and 3;
  - with `rows=2` it raises on a tie between places 2 and 3, and not on a tie at place 1;
  - with no partition, a column expression for `rows`, and a partition with a null key
    value, it raises as above, and the error holds the node, the place and the key values;
  - with a column expression for `rows` that differs within a partition, it raises (R1.1a);
  - `fo_row_number` raises on a tie at any place, and numbers a total order 1 to n.

  The CI fixtures hold no tie anywhere (C6), so this test is what proves the check in CI.
- R4.2 The same cases SHALL be run once on BigQuery over literal rows (no table read,
  nothing billed), and the result recorded on #141.
- R4.3 `dbt run --empty` and `dbt test` on the `bigquery` selector into suffixed datasets
  SHALL pass (AGENTS.md, dbt gotchas), except for
  `int_fantasy__started_days_match_the_starting_slots`, which fails over no rows by design
  (AGENTS.md). The other tests SHALL give the same result as on `main` (amended
  2026-10-29).

### R5. The real season

- R5.1 WHEN the real season is built from the branch THE SYSTEM SHALL complete with no tie
  error.
- R5.2 THE SYSTEM SHALL leave every relation identical to a `main` build of the same raw
  data, except the rows ADR 0109 changes (*Expected values*). Use
  `scripts/compare_warehouses.py`, or the bounded comparison if it runs out of memory.
- R5.3 IF the id map's tie-break (R3.1) is removed on a copy of the branch THEN the
  real-season build of `stg_idmap__players` SHALL fail with an error that names ESPN id
  5214984.

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| Real-season build from the branch | completes, no `ties for place` error | `dbt build` on a real-season copy (task 9) |
| Rows differing from a `main` build on the same raw data | only those below for ESPN id 5214984 | `scripts/compare_warehouses.py` or the bounded comparison |
| `stg_idmap__players` for ESPN id 5214984 | no row (ADR 0109) | query (C3) |
| `stg_idmap__players` rows | 3,656 (3,657 less 5214984) | `count(*)` (C14) |
| ESPN 5214984 in `int_fantasy__roster_days`, `int_fantasy__started_player_days`, `dim_player_league_seasons` | 51, 42 and 2 rows, `mlbam_player_id` 804636 as before, `player_resolution` `unambiguous_name` (was `crosswalk_id`) | query (C4) |
| `stg_idmap__players` without R3.1's tie-break | fails, naming 5214984 | R5.3 |
| CI fixtures build | passes; the fixtures hold no tie (C6) | `.agentic/gates` |
| Rule test on `main` before the conversion | flags every hand-written site in the *Call sites* table | R2.1 test, run before task 5 |
| BigQuery literal rows | raises on the tie cases, returns the same rows as DuckDB otherwise | R4.2, comment on #141 |
