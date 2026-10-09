# A player-day difference says whether its inputs were verified — requirements

Issue: #81 · Tier: M · Status: draft

## Problem

`rec_espn__player_day_differences` holds one row per started player-day and stat where
our credited number and ESPN's own per-game line disagree. It is the evidence behind the
matchup residuals. It compares every started player-day, whatever its `input_status`, so
a player-day whose boxscore is not loaded is compared as zero against ESPN's line and
reported as a difference.

`int_fantasy__started_player_days` already says whether a row's numbers can be trusted
(`played`, `verified_off`, `missing_boxscore`, `unresolved_player`, #25), and the
matchup-level table, `rec_espn__matchup_stat_differences`, acts on it: a side resting on
unverified inputs has the status `unverified` and is not judged. The player-day table
has no such case.

Measured on 2026-10-09:

- **Real 2026 season: no effect today.** 38,665 started player-days: 21,120 `played`,
  17,545 `verified_off`, none unverified. The table has 22 rows over 12 player-days, all
  `played`.
- **CI, on the fixtures of #93** (spec 0093; regenerated in a throwaway spike with that
  branch's generator, not committed): 647 started player-days, every one
  `missing_boxscore`, because the fixtures hold 3 of the 38 boxscores of their three
  data days and the flag is set for the whole date. The table has 467 rows over 99
  player-days, all of them on unverified inputs. Not one is a difference in the sense
  the table's description gives.
- **In season:** a started player whose game's boxscore has not landed appears as a
  difference until it does.

The table also has no test. On the real season its 22 rows fall on 22 (matchup, side,
stat) keys, and on each the differences sum to exactly the difference recorded for that
key in the `espn_reconciliation_residuals` seed (a seed is a small CSV kept in the repo
and loaded as a table). Nothing holds it to that.

## Goals

- A row of the table says whether it is a difference or a comparison that proves nothing.
  (A label can only be on a row that exists: an unverified player-day whose two numbers
  happen to agree has none. That inputs are complete is still what
  `int_fantasy__started_player_days_inputs_all_verified` and
  `rec_espn__every_side_is_verified` report.)
- The 22 rows of the real 2026 season come out the same, in every existing column.
- A verified player-day difference that the register does not account for fails the build.
- The rule is written down once, in the model, and held by a unit test.

## No-gos

- **No change to `input_status`** or to how a date is judged complete (#25). That every
  resolved player on an incomplete date is flagged, including the 25 fixture player-days
  that do appear in a loaded boxscore, is that model's deliberate caution.
- **No change to the table's grain or to which stats it compares**: one row per started
  player-day and single-component stat where the two numbers differ.
- **No change to `rec_espn__matchup_stat_differences`, the register seed, or any
  fixture.** The seed has no league or season column, and the matchup-level table joins
  it by matchup, side and stat alone. Adding them is a change to the seed's columns and
  to that table; here the new test fails closed instead (R3.2).
- **No census.** Rows where the numbers agree are not added.
- **No new warning in CI.** The unverified sides and player-days are already reported by
  `rec_espn__every_side_is_verified` and
  `int_fantasy__started_player_days_inputs_all_verified`.

## Rabbit holes

- *Replacing the model's own "single-component stat" CTE with the
  `fo_single_component_stats` macro* → the two say the same thing today; folding them
  together is a separate, mechanical change and is not made here.
- *Judging a player who appears in a loaded boxscore as verified even when another game
  that date is missing* → that is a change to `input_status` (no-go).
- *Explaining register rows that have no player-day evidence* → 9 of the 31: 8 are
  `espn_total_inconsistent`, which by definition no player line shows, and 1 is SVHD,
  a two-component stat this table does not compare. The test runs from the player-days
  to the register, not back.
- *More fixture boxscores so CI compares something* → out of scope, as in specs 0074 and
  0093.

## Requirements

### R1. Every row says what its inputs were

- R1.1 THE SYSTEM SHALL carry, on every row of `rec_espn__player_day_differences`, the
  `input_status` of its started player-day, taken from
  `int_fantasy__started_player_days`.
- R1.2 THE SYSTEM SHALL carry a `status`: `difference` WHEN `input_status` is `played`
  or `verified_off`, and `unverified` otherwise.
- R1.3 THE SYSTEM SHALL keep a row only where the two numbers differ by more than 1e-9,
  as today, whatever its status.
- R1.4 THE SYSTEM SHALL leave every existing column, its name, order and value,
  unchanged; the two new columns come last.

### R2. What counts as a difference

- R2.1 WHEN a player-day is `verified_off` and ESPN has a line with a non-zero stat for
  it THE SYSTEM SHALL report a row with status `difference`: we say he did not play and
  every game that date is loaded; ESPN says he did.
- R2.2 WHEN a player-day is `played` and ESPN has no line for it THE SYSTEM SHALL
  compare against zero and report a `difference`, as today.
- R2.3 WHEN a player-day is `missing_boxscore` or `unresolved_player` THE SYSTEM SHALL
  report its rows as `unverified`, with both numbers kept.

### R3. The table is held to the register

- R3.1 THE SYSTEM SHALL have a view, `rec_espn__player_day_residuals`, with one row per
  (`league_id`, `season`, `matchup_id`, `fantasy_team_id`, `stat_id`) that has at least
  one `difference` row: the sum of those rows' differences, the `expected_difference`
  of that (matchup, side, stat) in `espn_reconciliation_residuals` (null if none), and
  a `problem` column, null when the key is accounted for.
- R3.2 THE SYSTEM SHALL set `problem`, in this order, to: `ambiguous_register` WHEN
  `difference` rows exist for more than one league-season (the register names a matchup
  and not a season, so it cannot say whose residual it is); `unregistered` WHEN the key
  has no register row; `wrong_size` WHEN the sum differs from the registered difference
  by more than 1e-9.
- R3.3 THE SYSTEM SHALL NOT count `unverified` rows in the view.
- R3.4 THE SYSTEM SHALL have a singular test (a SQL file under `dbt/tests/` that fails
  the build when its query returns any row),
  `rec_espn__player_day_differences_are_registered`, returning the view's rows whose
  `problem` is not null, at the default severity, error.
- R3.5 THE SYSTEM SHALL have a dbt unit test of the view with one case each for: a key
  equal to its register row; `unregistered`; `wrong_size`; two differences that cancel
  on one key with no register row (`unregistered`, sum 0); a key with only `unverified`
  rows (no row); `difference` rows in two league-seasons (`ambiguous_register`).

### R4. The rule is tested and described

- R4.1 THE SYSTEM SHALL have a dbt unit test of `rec_espn__player_day_differences` (a
  unit test gives a model made-up input rows and compares its output with expected
  rows, without touching the warehouse) with one case each for: `played` and equal (no row); `played` and
  different; `played` with no ESPN line; `verified_off` with an ESPN line;
  `verified_off` with none (no row); `missing_boxscore` with an ESPN line;
  `unresolved_player` with an ESPN line; a pitcher slot, whose batting is not compared.
- R4.2 THE SYSTEM SHALL test both new columns `not_null`, and `status` and
  `input_status` for their accepted values.
- R4.3 THE SYSTEM SHALL have a uniqueness test on (`league_id`, `season`,
  `scoring_period`, `fantasy_team_id`, `platform_player_id`, `stat_id`).
- R4.4 THE SYSTEM SHALL bring the model's header comment and its YAML description up to
  date: the statuses, R2, and that `unverified` rows are not evidence of anything.

## Expected values

Real season: `data/warehouse.duckdb`, read-only, 2026-10-09. CI: the spike named above,
which is the fixture set of #93. **This spec is built after #93 merges**; if it is built
before, the CI row count is 308 and its split by status is not measured.

| Check | Now | Expected | How to verify |
|---|---|---|---|
| Real: rows / player-days | 22 / 12 | 22 / 12 | `count(*)` |
| Real: existing 15 columns | — | identical for all 22 rows | `except` both ways against a copy of the table taken before the build: 0 rows |
| Real: `status`, `input_status` | — | 22 `difference`, 22 `played` | `group by` |
| Real: `verified_off` player-days with an ESPN line | 0 of 17,545 | 0 | query in the design |
| Real: `played` player-days with no ESPN line | 0 of 21,120 | 0 | same |
| Real: `rec_espn__player_day_residuals` | 22 keys of 22 sum to their register row (not tested) | 22 rows, every `problem` null; the test returns 0 rows | `dbt build --select rec_espn__player_day_differences+` |
| Real: league-seasons with `difference` rows | 1 | 1 | `count(distinct (league_id, season))` |
| Real: register rows with no player-day rows | 9 of 31 | 9: not judged | query |
| Real: uniqueness on the R4.3 key | 22 distinct of 22 | test passes | test |
| CI after #93: rows / player-days | 467 / 99 | 467 / 99 | query of `ci.duckdb` |
| CI after #93: by status | — | 467 `unverified`, all `missing_boxscore`; 0 `difference` | `group by` |
| CI after #93: `rec_espn__player_day_residuals` | — | 0 rows; the test passes having judged none | query; build log |
| CI `dbt build` | `PASS=480 WARN=3` after #93 | the same three warnings, no error; PASS grows by the new tests | `.agentic/gates` |
| `rec_espn__matchup_stat_differences` | 6,816 match, 48 bye, 31 registered, 17 explained | unchanged | `group by status` |
| Tenant isolation | 0 differing pairs | 0 | gate |
