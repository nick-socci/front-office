# Past seasons' rosters and boxscores, with what a covered season needs — requirements

Issue: #83 · Tier: M · Status: draft

## Problem

Spec 0085 landed the matchup totals of 2018 to 2025 and left those seasons without
rosters, so no value is computed for them (ADR 0026). It restricted two tests to
league-seasons with rosters and noted on #83 that both come due the day a past season's
rosters are landed:

- **A scored category with no rule.** 2018, 2019 and 2021 score complete games (ESPN
  stat 62), and `int_fantasy__stat_components` has no rule for it.
- **No day-to-matchup mapping.** `stg_espn__matchup_periods` reads each matchup's
  `pointsByScoringPeriod`. Only 2025 and 2026 carry a full one; 2018 carries one key per
  matchup period; 2019 and 2021 to 2024 carry none.

A probe on 2026-10-11 (ten authenticated requests, approved by the owner) found that
ESPN still serves a per-day roster with game lines for 2018, 2021 and 2023; that a
matchups request for one scoring period marks the matchup period that day belongs to;
and that the transaction log of a past season is not served (404 for 2023 and 2025, 200
for 2026). So the seasons can be covered, the mapping has a source at ESPN, and a covered
past season will have no transaction log.

The owner chose on 2026-10-11 to land all seven played seasons: 2018, 2019 and 2021 to
2025. A landed previous season also gives #92 a second MLB season to measure its rule on.

## Goals

- The seven played past seasons hold rosters, teams and MLB boxscores, and are covered:
  values, matchup scores and lineup decisions are computed for them.
- Every scoring period of every covered league-season belongs to exactly one matchup
  period, from what ESPN reports, with no season-specific rule.
- Complete games is computed from MLB's boxscores and reconciles with ESPN's totals.
- Our totals for the past seasons reconcile with ESPN's, or each difference is in the
  register with its evidence, or is traced exactly to ESPN's own game lines (ADR 0064).
  *Amended 2026-10-14 by the owner's decision (design.md, Amendments).*
- Nothing about the 2026 season changes.
- A covered league-season with no transaction log is stated as such in data.

## No-gos

- **No change to who is a starter (ADR 0031).** A role carried over from the previous
  season is made possible by this data and is a separate decision, specced on its own.
- **No change to how a boxscore settles (ADR 0019).** That ADR accepted that a season
  backfilled after it ended needs a second pass at least seven days later.
- **No reconstruction of past transactions** from day-to-day roster differences.
- **No 2020.** The league did not play; it stays loaded with settings and no matchups.
- **No season before 2018.**
- **No change to the audit's findings.** It reads the landing zone, not dbt.
- **No new fixture season, and no change to an existing fixture file.** The owner chose
  unit tests for the new paths (design.md, *CI coverage*).
- **No change to the grain or name of an existing model.** Columns are added only as
  R2.6, R3.1 and R4.2 say, and `formula_checked` and `game_line_difference` on
  `rec_espn__matchup_stat_differences` (ADRs 0063, 0064); none is removed or changed.
  *Amended 2026-10-14 by the owner's decision.*
- **No narrowing or weakening of a test to get a past season through.** One exception,
  the owner's decision of 2026-10-14: `stg_espn__scoring_periods_agree_with_espn_game_lines`
  counts an ESPN game only if a line in it scores something, because ESPN's 2019 lines
  list postponed games with a starter flag or a games count alone. The check still fails
  on 588 periods with the date mapping shifted by one day.

## Rabbit holes

- *A calendar rule for matchup periods* (Monday to Sunday, short weeks folded in) → not
  used. It reproduces 2018, 2025 and 2026 and gets 2019's period count wrong (C6).
- *Why ESPN drops `pointsByScoringPeriod` for some seasons* → not chased.
- *A smaller ESPN response for the marker* → one bounded check in the build (R1.6), not
  an exploration.
- *Past seasons' differences from ESPN, one by one* → the build registers what it can
  evidence and stops for the owner on the rest (R6.4); it does not tune a model to a
  season.
- *Build time with eight covered seasons* → measured and reported (R6.6); making the
  build faster is not this spec.
- *Rules of the 2021 seven-inning doubleheaders for complete games* → whatever MLB
  credits is the component; a difference from ESPN is a reconciliation finding.

## Requirements

### R1. Fetch a past season's rosters and its day-to-matchup markers

- R1.1 WHEN `front-office backfill espn --season <year> --only rosters` runs THE SYSTEM
  SHALL land, under the run's one stamp, the league's settings, teams and the roster of
  every scoring period up to the season's last, as a full run does, and SHALL NOT
  request the transaction log, the matchups or the pro schedule.
- R1.2 WHEN `front-office backfill espn --season <year> --only matchup-days` runs THE
  SYSTEM SHALL land, for every scoring period from the first to the final one of the
  newest committed settings capture of that league-season, one response of the league
  resource requested with that `scoringPeriodId`, under endpoint `matchup_days` with
  partitions `season`, `league_id` and `scoring_period`.
- R1.3 THE SYSTEM SHALL skip, in a `--only matchup-days` run, a scoring period that
  already has a committed capture, unless `--refresh` is given; and SHALL exit non-zero,
  after trying every period, if any request failed, naming the periods.
- R1.4 IF no settings capture is committed for the league-season THEN `--only
  matchup-days` SHALL make no request and exit non-zero saying so.
- R1.5 THE SYSTEM SHALL leave a full `backfill espn` run, `--only pro-schedule` and
  `--only matchups` as they are, and SHALL refuse an unknown `--only` value.
- R1.6 THE SYSTEM SHALL request the marker with the views `mMatchupScore` and
  `mScoreboard`, which the probe showed carry it. The build MAY first try `mMatchupScore`
  alone on one scoring period; it is used instead only if the response carries
  `rosterForCurrentScoringPeriod` on the same matchup period.
- R1.7 THE SYSTEM SHALL keep credentials out of every capture, sidecar and log line of
  the new paths, as the existing ones do.

### R2. Every scoring period has a matchup period

- R2.1 THE SYSTEM SHALL provide `stg_espn__matchup_days`: one row per (`league_id`,
  `season`, `scoring_period`, `matchup_period`) such that, in the newest capture of that
  scoring period, a matchup of that matchup period has a side carrying
  `rosterForCurrentScoringPeriod`.
- R2.2 THE SYSTEM SHALL keep `stg_espn__matchup_periods` as it is.
- R2.3 THE SYSTEM SHALL build `int_fantasy__matchup_periods` from both: a scoring period
  that `stg_espn__matchup_periods` maps keeps that row; any other takes its row from
  `stg_espn__matchup_days`.
- R2.4 IF a scoring period is mapped by both sources to different matchup periods THEN
  THE SYSTEM SHALL fail the build.
- R2.5 IF a capture of `matchup_days` marks no matchup period, or more than one, or its
  payload's `scoringPeriodId` differs from the one requested THEN THE SYSTEM SHALL fail
  the build.
- R2.6 THE SYSTEM SHALL add to `int_fantasy__matchup_periods` a column `mapping_source`,
  `points_by_scoring_period` or `matchup_day_marker`, not null.
- R2.7 THE SYSTEM SHALL hold the tests that every scoring period of a covered
  league-season has exactly one matchup period, that matchup periods are contiguous, and
  that they use their own league-season's scoring periods, against the combined mapping.

### R3. Complete games

- R3.1 THE SYSTEM SHALL carry `complete_games` as a pitching component, from MLB's
  boxscore `completeGames`. Every existing model that takes its pitching columns from
  `fo_pitching_columns` gains a `complete_games` column; the build lists them on the
  issue before the change (among them `int_fantasy__started_player_days` and
  `int_fantasy__matchup_side_totals`).
- R3.2 THE SYSTEM SHALL compute ESPN stat 62 as the sum of `complete_games`, credited to
  a team by the rule every pitching component follows.
- R3.4 THE SYSTEM SHALL compute a stat's value for a matchup side only where the host
  reports that stat for at least one side of that league-season. A stat with a rule that
  the host reports nowhere in the league-season has no row in
  `int_fantasy__matchup_stat_values`, and so none in the reconciliation. `missing_espn`
  keeps its meaning: the host reports the stat in the league-season and not for this
  side. *Added 2026-10-11 by the owner's decision (design.md, Amendments).*
- R3.3 THE SYSTEM SHALL keep `int_fantasy__scored_categories_have_a_component_rule`
  unchanged, and it SHALL return no rows with every played season covered.

### R4. A covered season with no transaction log

- R4.1 THE SYSTEM SHALL build a league-season with rosters and no transaction log, with
  no row for it in `int_fantasy__transactions` or `fct_transaction_impact`.
- R4.2 THE SYSTEM SHALL add to `int_fantasy__league_seasons` a boolean
  `has_transaction_log`, not null: true when a transaction-log response is loaded for
  the league-season, whether or not it holds a transaction. It is read from a new
  staging model, `stg_espn__transaction_logs`, one row per (`league_id`, `season`) with
  a loaded log.
- R4.3 THE SYSTEM SHALL fail the build if `fct_transaction_impact` holds a row for a
  league-season whose `has_transaction_log` is false.
- R4.4 THE SYSTEM SHALL say in the description of `fct_transaction_impact` that a
  league-season with `has_transaction_log` false has no log landed, which is not the same
  as a landed log with no transaction in it.

### R5. Tests

- R5.1 THE SYSTEM SHALL test the two new `--only` values with a fake transport: what is
  requested and in what order; that no transaction, matchup or pro-schedule request is
  made by `rosters`; the skip and `--refresh` of R1.3; the failure paths of R1.3 and
  R1.4.
- R5.2 THE SYSTEM SHALL have dbt unit tests for `stg_espn__matchup_days`: a response
  marking one period gives one row; two captures of one scoring period give the newer;
  two leagues and two seasons stay apart.
- R5.3 THE SYSTEM SHALL have dbt unit tests for `int_fantasy__matchup_periods`: a period
  only in the marker source is filled; a period in both keeps the existing source's
  row; `mapping_source` says which.
- R5.4 THE SYSTEM SHALL have a dbt unit test that a started pitcher's complete game
  reaches his team's stat 62, and a benched one's does not.
- R5.5 THE SYSTEM SHALL have dbt unit tests for `has_transaction_log`, and singular tests
  for R2.4, R2.5 and R4.3.

### R6. The landed seasons

- R6.1 THE SYSTEM SHALL land `matchup_days` for 2025 and 2026 before any other season,
  and compare them with `pointsByScoringPeriod` for all 368 scoring periods. IF any
  period differs THEN the build SHALL stop and take it to the owner before landing
  anything else.
- R6.2 WHEN the build lands the seven seasons THE SYSTEM SHALL have, for each: one teams
  capture; a roster capture for every scoring period up to its final one; a
  `matchup_days` capture for every scoring period; MLB's player list; and a boxscore
  for every game its MLB schedule lists as played.
- R6.3 THE SYSTEM SHALL build and test clean on the real warehouse with the eight played
  seasons covered, the 2026 warning unchanged.
  *Not met at merge, by the owner's decision of 2026-10-14:* the real build needs DuckDB's
  memory and threads held down (README), two tests run out of memory (#146), and values
  ESPN's own lines do not account for stay `unexplained` (the games-started limit, #152,
  among them). Listed on the PR; #83 stays open.
- R6.4 IF a past season fails a test, or our totals differ from ESPN's in a way the
  register does not already explain THEN the build SHALL stop and take it to the owner
  with the season, the test and the rows. A row is added to
  `espn_reconciliation_residuals.csv` only with its evidence and the owner's agreement.
  A difference whose size equals the sum of the side's player-day differences against
  ESPN's own game lines is explained without a register row, and a rate ESPN gives no
  components for is compared directly (ADRs 0064, 0063). *Amended 2026-10-14 by the
  owner's decision (design.md, Amendments).*
- R6.5 WHEN the build stops under R6.4 THE SYSTEM SHALL first have landed and built
  every season it can, so that every season with a problem is reported together. It
  SHALL NOT exclude a season to get past one. A stop under R6.1 is immediate: nothing
  else is landed first.
- R6.6 THE SYSTEM SHALL record, on the issue: requests made per command; bytes landed
  per endpoint; the real build's wall time and peak memory before and after. IF the real
  build cannot complete on the owner's machine THEN the build SHALL stop for the owner.
- R6.7 THE SYSTEM SHALL NOT change or remove a row of any model for the 2026
  league-season: over the columns each model had before, every 2026 row it had is still
  there, unchanged. The columns R2.6, R3.1 and R4.2 add are left out of that comparison
  and checked on their own. Rows may be added for 2026 only where a model holds one row
  per component and the row's component is `complete_games`; the build lists them.
  *Amended 2026-10-11 by the owner's decision (design.md, Amendments).*
- R6.8 THE SYSTEM SHALL record `front-office audit --season <year>` for each past
  season. The findings expected are the missing transaction log and, until the second
  pass, boxscores not yet settled; any other is R6.4.
- R6.10 THE SYSTEM SHALL request the transaction log once for each of 2018, 2019, 2021,
  2022 and 2024, the seasons the probe did not try, before `--only rosters` is run for
  any season. IF ESPN serves one THEN the build SHALL stop and take it to the owner:
  that season's log can be landed, and ADR 0056 is reread before it is accepted.
- R6.9 WHEN at least seven days have passed since the first boxscore pass THE SYSTEM
  SHALL run the second pass (ADR 0019) and record, per season, how many boxscores
  changed and whether any model row moved.

## Expected values

Known on 2026-10-11 from the real warehouse and the probe (design.md, *Claims ledger*).
Where a value is not known the build records what it finds.

| Check | Expected | How to verify |
|---|---|---|
| Every row of every model, 2026 league-season, existing columns | every earlier row still there, unchanged; rows added only for the component `complete_games` (`int_fantasy__replacement_levels`: 48 to 50; `int_fantasy__stat_components`, which has no season: 30 to 31) | `EXCEPT ALL` both ways against a copy, `season = 2026` |
| `int_fantasy__league_seasons` | 9 rows; `has_rosters` true for all but 2020; `has_transaction_log` true for 2026 only | query |
| Marker against `pointsByScoringPeriod` | equal for 188 periods of 2025 and 180 of 2026 | R6.1's query; R2.4's test |
| Marker against 2018's 24 period starts | each start's marker is that matchup period, and the day before it the one before | query |
| Marker, 2023 period 60 / 2019 period 15 | matchup period 8 / matchup period 1 | `stg_espn__matchup_days` |
| Scoring periods mapped, per season | 2018: 179 · 2019: 187 · 2021: 179 · 2022: 182 · 2023: 179 · 2024: 195 · 2025: 188 · 2026: 180 | `int_fantasy__matchup_periods` |
| Matchup periods, per season | 24 · 24 · 24 · 24 · 24 · 26 · 25 · 24 | the same |
| Length of matchup period 1 | 2018: 11 days · 2025: 13 · 2026: 12 · 2019: at least 15 · others recorded | the same |
| `mapping_source` | `points_by_scoring_period` for every row of 2025 and 2026 and 24 rows of 2018; the marker otherwise | the same |
| ESPN's complete games, summed over sides | 2018: 33 · 2019: 29 · 2021: 37 | `stg_espn__matchup_category_results`, stat 62 |
| Our stat 62 against ESPN's, per side | no difference, or each one registered with evidence | `rec_espn__matchup_stat_differences` |
| Scored categories with no rule, covered seasons | 0 rows | R3.3's test |
| `fct_transaction_impact` | 737 rows, all 2026 | query; R4.3's test |
| Side totals | 2,324, one per matchup side: 286 for 2026 and 2,038 for the seven seasons | `int_fantasy__matchup_side_totals` |
| ESPN ids on the probed rosters found in the id map | 288 of 288 (2018) · 292 of 292 (2021) · 300 of 300 (2023); whole seasons recorded | `dim_player_league_seasons_rostered_players_are_resolved` |
| Real build | passes; the one warning it has today | `dbt build` |
| CI | passes; warnings unchanged at 3; isolation 0 differing pairs over 5 league-seasons | `.agentic/gates` |
| ESPN requests | `rosters`: 1,303 (7 settings, 7 teams, 1,289 rosters) · `matchup-days`: 1,469 · R6.10: 5 | the runs' output |
| MLB requests, first pass | about 17,012 boxscores (2,432 games in 2018; 2,430 in each of the six others, less any not played) and 7 player lists | the runs' output |
