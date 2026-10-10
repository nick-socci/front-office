# The register of known differences names its league and season — requirements

Issue: #99 · Tier: M · Status: approved 2026-10-09

## Problem

`dbt/seeds/espn_reconciliation_residuals.csv` is the register of known differences from
ESPN (a seed is a small CSV kept in the repo, which `dbt seed` loads as a table). Its key
is `matchup_id`, `team_id`, `stat_id`. ESPN starts matchup ids and team ids again in every
league and every season, so that key identifies a residual only while one league-season is
being reconciled. Four things join it by that key: `rec_espn__matchup_stat_differences`
(twice), `rec_espn__player_day_residuals`, and the singular tests
`fct_matchup_scores_match_espn` and `rec_espn__register_matchups_exist`.

Measured on 2026-10-09, read-only, on `data/warehouse.duckdb` and `dbt/ci.duckdb`:

- **The collision already exists in the real warehouse and is only masked.** The register
  holds 31 rows on 31 distinct keys over 13 matchups, all about 2026. The same
  (matchup, team, stat) exists in ESPN's totals of other seasons of the same league for
  24 of the 31 in 2025, 24 in 2024, 11 in 2023, 8 in 2022, 8 in 2021, 6 in 2019 and 4 in
  2018. Those seasons have `has_rosters = false` (ADR 0026), so they are not compared and
  nothing shows. The day one of them gains rosters, 2026's register rows apply to it.
- **CI already applies the real season's register to the fixture league.** Three register
  rows (matchup 2, team 3) attach to fixture league 111111: 3 of the 96 rows of the CI
  table carry a `registered_difference`. They do no harm only because every fixture side
  is `unverified`.
- **One league-season has rosters**: 1 league, 9 seasons (2018 to 2026), rosters in 2026
  alone. Its reconciliation is 6,816 `match`, 48 `bye`, 31 `registered`,
  17 `explained_by_component`, nothing `unexplained`.
- **#81's alarm is in place**: `rec_espn__player_day_residuals` reports
  `ambiguous_register` on every key once two league-seasons have player-day differences.
  It has 22 rows on the real season, none with a problem, and 0 rows in CI.
- **The seed is not generated.** `scripts/make_espn_seeds.py` writes the lookup seeds from
  the `espn-api` package's constants and does not mention this one. The register is kept
  by hand, each row with its evidence. `AGENTS.md` says all seeds are generated.
- **The real league id is already in this public repo**: as `LEAGUE_ID` in five files
  under `ingestion/tests/`, and in five commits. It is not among the privacy patterns of
  `front_office/privacy.py`, which cover members' names and ESPN account GUIDs.

## Goals

- A register row says which league and season it is about, and applies to no other.
- A league-season's reconciliation depends only on its own register rows (ADR 0013).
- `ambiguous_register`, the alarm of #81, is gone because it can no longer be needed.
- The real 2026 season reconciles exactly as it does now, row for row.
- The rule "a register row must explain something" has a test that can fail in CI.

## No-gos

- **No alias, hash or local mapping for the league.** The owner decided on 2026-10-09
  that a row names its league by the real ESPN league id (ADR 0040).
- **No change to the real league id in `ingestion/tests/` or in history.** The owner was
  offered that follow-up on 2026-10-09 and did not take it.
- **No new, removed or reworded register row.** 31 rows before and after; `matchup_id`,
  `team_id`, `stat_id`, `expected_difference`, `cause` and `evidence` are untouched.
- **No `platform` column.** The seed is ESPN's by name and by content.
- **No change to a status, its order or its meaning** in
  `rec_espn__matchup_stat_differences`, and none to `rec_espn__player_day_differences`.
- **No change to a test's severity.** `rec_espn__register_matchups_exist` stays a warning.
- **No register rows for the fixture leagues, and no fixture change.** In CI the register
  describes a league that is not loaded; the unit tests are what exercise the joins there.
- **No generator for this seed.** It is evidence written by a person.

## Rabbit holes

- *Making the "matchup absent" warning an error where the league-season is loaded, and
  silent where it is not* → attractive, because CI's warning is always noise; it is a
  severity and scope change of its own, and is not made here.
- *A register row for a past season with no rosters* → nothing of ours exists to compare,
  so such a row explains nothing and fails the build, as a stale row does. Not special-cased.
- *A view row for every register row, loaded or not* → the isolation gate counts any row
  of another league in a single build as a leak, rightly, and the real league's 31 rows
  would be that in every fixture build. The view holds loaded league-seasons only (R4.1).
- *Proving register isolation with the four-league-season gate* → the gate's fixture
  leagues have no register rows and no real differences, so it can only show that nothing
  leaks; the unit tests of R5 show two league-seasons reconciling apart.
- *Folding register-only rows into `rec_espn__matchup_stat_differences`* → changes that
  table's grain and statuses (no-go).

## Requirements

### R1. A register row names its league and season

- R1.1 THE SYSTEM SHALL carry two more columns in `espn_reconciliation_residuals.csv`,
  first in the file: `league_id`, then `season`, followed by the six existing columns in
  their present order.
- R1.2 THE SYSTEM SHALL type `league_id` as `varchar` and `season` as `bigint` in the
  seed's `column_types` (the YAML setting that fixes a seed column's type; without it dbt
  would read a league id as a number, and every model holds it as text).
- R1.3 THE SYSTEM SHALL give each of the 31 existing rows the real league's ESPN league id
  and `2026`, and change nothing else in them.
- R1.4 THE SYSTEM SHALL test `league_id` and `season` `not_null`, and test the seed unique
  on (`league_id`, `season`, `matchup_id`, `team_id`, `stat_id`) in place of the present
  three-column uniqueness test.

### R2. Every join to the register uses the full key

- R2.1 WHEN `rec_espn__matchup_stat_differences` decides `registered_difference` and
  `registered_cause` THE SYSTEM SHALL join the register on league, season, matchup, side
  and stat.
- R2.2 WHEN `rec_espn__matchup_stat_differences` shifts ESPN's components by their
  registered differences to compute `implied_value` THE SYSTEM SHALL join the register on
  league, season, matchup, side and component stat.
- R2.3 WHEN `rec_espn__player_day_residuals` looks up `expected_difference` THE SYSTEM
  SHALL join the register on league, season, matchup, side and stat.
- R2.4 THE SYSTEM SHALL leave every column of both relations, its name, order and type,
  as it is.

### R3. `ambiguous_register` is removed

- R3.1 THE SYSTEM SHALL set `problem` in `rec_espn__player_day_residuals`, in this order,
  to `unregistered` WHEN the key has no register row, `wrong_size` WHEN the sum differs
  from the registered difference by more than 1e-9, and null otherwise.
- R3.2 THE SYSTEM SHALL remove the `ambiguous_register` branch, the count of
  league-seasons that fed it, its accepted value, and the unit test
  `player_day_residuals_refuse_a_register_that_cannot_tell_seasons_apart`.
- R3.3 THE SYSTEM SHALL bring up to date every comment and description that mentions
  `ambiguous_register` or a register that "names a matchup and no season": the view's
  header and YAML, and the header of `rec_espn__player_day_differences_are_registered`.

### R4. The register's own checks are held where a unit test can reach them

Proposed in ADR 0041; a new model, so the owner's to approve. If declined, R4.1, R4.2
and R5.3 go, and R4.3 to R4.5 are met by the same joins written in the two test files.

- R4.1 THE SYSTEM SHALL have a view, `rec_espn__register_rows`, with one row per register
  row whose league-season is loaded (it is a row of `int_fantasy__league_seasons` for
  platform `espn`, with or without rosters), and no row for any other: `league_id`, `season`, `matchup_id`, `team_id`, `stat_id`, `expected_difference`,
  `cause`, `reconciliation_status` (the `status` of the row of
  `rec_espn__matchup_stat_differences` with the same league, season, matchup, side and
  stat; null if there is none) and `problem`.
- R4.2 THE SYSTEM SHALL set `problem`, in this order, to `matchup_absent` WHEN
  `stg_espn__matchup_category_results` has no row of that league, season and matchup;
  `explains_nothing` WHEN `reconciliation_status` is null or is neither `registered` nor
  `unverified`; and null otherwise.
- R4.3 THE SYSTEM SHALL have `fct_matchup_scores_match_espn` fail on every register row
  whose problem is `explains_nothing`, and keep its first branch (statuses `unexplained`,
  `missing_ours`, `missing_espn`, `formula_mismatch`) as it is.
- R4.4 THE SYSTEM SHALL have `rec_espn__register_matchups_exist` return, at severity
  `warn` and with a `finding` column saying which, every register row whose league-season
  is not loaded (`league_season_not_loaded`, read from the seed) and every row of the view
  whose problem is `matchup_absent`.
- R4.5 THE SYSTEM SHALL return `league_id` and `season` in every row of both tests, so a
  failure names its league-season.

### R5. Two league-seasons reconcile independently, shown by unit tests

A unit test gives a model made-up input rows and compares its output with expected rows,
without touching the warehouse. Each case below uses three league-seasons that share one
(matchup, side, stat): league 1 in 2026, league 1 in 2027, league 2 in 2026, so both the
season and the league must be in the join for it to pass.

- R5.1 THE SYSTEM SHALL have a unit test of `rec_espn__matchup_stat_differences` in which
  all three are off on hits: league 1 / 2026 by 1 with a register row of 1 (`registered`,
  and its AVG `explained_by_component`); league 1 / 2027 by 1 with no register row
  (`unexplained`, and its AVG `unexplained`); league 2 / 2026 by 2 with a register row of
  2 (`registered`, AVG `explained_by_component`).
- R5.2 THE SYSTEM SHALL have a unit test of `rec_espn__player_day_residuals`, replacing
  the one removed by R3.2, in which all three have a difference of 1 on the same key:
  league 1 / 2026 with a register row of 1 (no problem); league 1 / 2027 with none
  (`unregistered`); league 2 / 2026 with a register row of 2 (`wrong_size`).
- R5.3 THE SYSTEM SHALL have a unit test of `rec_espn__register_rows` with one case each
  for: a row whose key is `registered` (no problem); one whose key is `unverified` (no
  problem); one whose key is `match` (`explains_nothing`); one whose matchup exists but
  whose side and stat do not (`explains_nothing`, status null); one whose key is
  `registered` in another league-season only (`explains_nothing`); one whose matchup
  exists in another league-season only (`matchup_absent`); one whose league-season is not
  loaded (no row).
- R5.4 THE SYSTEM SHALL give `league_id` and `season` on every register row of the two
  existing unit tests that supply the register, with their expected rows unchanged.

### R6. The documents say what the register is

- R6.1 THE SYSTEM SHALL bring the seed's YAML description up to date: the key, that a row
  applies to one league-season, and that the file is kept by hand.
- R6.2 THE SYSTEM SHALL correct the `dbt/seeds/` line of `AGENTS.md` to say that the
  lookup seeds are generated by `scripts/make_espn_seeds.py` and never hand-edited, and
  that `espn_reconciliation_residuals.csv` is the exception: a register kept by hand,
  each row with its evidence.
- R6.3 THE SYSTEM SHALL bring the header comments of the changed models and tests up to
  date, including the first line of the status list where it names the seed.

## Expected values

Real season: `data/warehouse.duckdb`, read-only, 2026-10-09. CI: `dbt/ci.duckdb` of the
same day and the CI run of commit `263923d` on `main`.

| Check | Now | Expected | How to verify |
|---|---|---|---|
| Seed rows / distinct full keys | 31 / 31 (three-column key) | 31 / 31 | uniqueness test; `count(*)` |
| Seed rows by league-season | none named | 31 in the real league, 2026 | `group by league_id, season` |
| Seed: the six old columns | — | identical for all 31 rows | `git diff --word-diff` shows only two leading fields added per row |
| Real: `rec_espn__matchup_stat_differences` by status | 6,816 `match`, 48 `bye`, 31 `registered`, 17 `explained_by_component` | the same; no `unexplained` | `group by status` |
| Real: the same table, every column | 6,912 rows; 31 `registered_difference` not null; 1,152 `implied_value` not null | identical for all 6,912 rows | `except` both ways against a copy taken before the build: 0 rows |
| Real: `rec_espn__player_day_residuals` | 22 rows, every `problem` null | identical in every column | `except` both ways against a copy: 0 rows |
| Real: `rec_espn__register_rows` | — | 31 rows, all `reconciliation_status = 'registered'`, every `problem` null | query |
| Real: `fct_matchup_scores_match_espn` | 0 rows | 0 rows | build |
| Real: `rec_espn__register_matchups_exist` | 0 rows | 0 rows | build |
| Real: register rows whose key exists at ESPN in another season | 24 in 2025, 24 in 2024, 11, 8, 8, 6, 4 | not joined: the counts above are unchanged | the status counts |
| CI: `rec_espn__matchup_stat_differences` | 96 rows, all `unverified`; 3 with `registered_difference` | 96 `unverified`; 0 with `registered_difference` | query of `ci.duckdb` |
| CI: `rec_espn__register_matchups_exist` | warns, 28 rows | warns, 31 rows, all `league_season_not_loaded` | build log |
| CI: `rec_espn__register_rows` | — | 0 rows: the real league is not loaded | query |
| CI, once and not committed: a register row for league 111111, 2026, matchup 1, with a stat ESPN lacks | — | `fct_matchup_scores_match_espn` fails with that one row | the last task's probe |
| CI: `rec_espn__player_day_residuals` | 0 rows | 0 rows | query |
| CI `dbt build` | `PASS=641 WARN=3 ERROR=0` | the same three warnings, no error; PASS 648 if nothing else has merged (see design) | `.agentic/gates` |
| `ambiguous_register` in `dbt/` | 8 mentions in 2 files | 0 | `git grep -c ambiguous_register -- dbt` |
| Tenant isolation | 0 differing pairs | 0; the view holds no row of a league that is not loaded, in any of the five builds | gate |
