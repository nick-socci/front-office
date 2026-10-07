# Scoring-period dates: a period is dated from MLB's schedule, not from ESPN's period counter — requirements

Issue: #70 · Tier: M · Status: draft

## Problem

`stg_espn__scoring_periods` gives every fantasy scoring period its calendar date. It is
the only bridge between ESPN rosters (keyed by period) and MLB game logs (keyed by
date). It derives the dates from one anchor: the newest settings capture's
`status.latestScoringPeriod` is taken to be the period current on the Eastern date that
capture was fetched.

That holds only while ESPN's counter advances a period a day. It has stopped. Five
settings captures of the 2026 league are landed:

| Settings capture | Fetched (Eastern) | `latestScoringPeriod` | `finalScoringPeriod` | Implied date of period 1 |
|---|---|---|---|---|
| `20260926T162307Z` | 2026-09-26 | 186 | 180 | 2026-03-25 |
| `20260926T173627Z` | 2026-09-26 | 186 | 180 | 2026-03-25 |
| `20260928T225612Z` | 2026-09-28 | 188 | 180 | 2026-03-25 |
| `20261007T011005Z` | 2026-10-06 | 188 | 180 | 2026-04-02 |
| `20261007T171657Z` | 2026-10-07 | 188 | 180 | 2026-04-03 |

The warehouse is loaded up to the third. Loading the last two makes `fo_espn_latest`
select the newest, and every scoring date moves 9 days later: period 1 becomes
2026-04-03 and period 180 becomes 2026-09-29, two days after MLB's last regular-season
game. Rosters stop lining up with game logs and every mart built on started player-days
is wrong. #70 therefore holds the real warehouse at its current load, which also keeps
back the 27 boxscores that settle #30.

All five captures were taken after the league's final period. The three that agree with
each other do so because the counter was still moving on those days, which nothing in a
capture says. A season fetched for the first time after it ended (#57) has no capture
that agrees with anything.

## Goals

- A scoring period's date does not depend on when a settings capture was taken, or on
  how many were taken.
- The real warehouse can take every landed capture again, with the 180 scoring dates of
  2026 unchanged.
- The mapping is checked against evidence that does not come from the rule that
  produced it, on every build of a league-season whose rosters carry ESPN's game lines,
  and a league-season that cannot be checked says so.
- The audit stops reporting an error for a counter that has merely stopped, and still
  reports one for a counter that disagrees while the season is in progress.

## No-gos

- **No new ingestion and no request to ESPN.** A date ESPN publishes itself (option E in
  the design) is not landed, and whether it exists is not verified.
- **No change to the grain, name or columns of `stg_espn__scoring_periods` or
  `stg_espn__league_settings`.** `latest_scoring_period` stays a column; only its
  description changes.
- **No change to how a roster period is settled** (ADRs 0016 to 0018). That rule reads
  the same counter for a different purpose; see *Open questions* in the design.
- **No historical seasons.** #57 is not built here. The design must not make it harder.
- **No change to any fixture or seed.** The fixture season keeps its two dates.
- **No capture is deleted, moved or skipped by the loader.** The two frozen captures are
  loaded like any other.
- **No change to the Eastern-day boundary** used for transaction dates.

## Rabbit holes

- *Working out when ESPN's counter stops and why* → nothing landed shows it, and the
  rule no longer needs it. Recorded as an open question.
- *Fitting the period-to-date offset from the data on every build* (option D) → the same
  evidence is used as a test instead, where a disagreement fails the build.
- *Proving period 1 is MLB's first game in every past season* (international openers) →
  only 2026 is landed with rosters. The test in R3 answers it for any season that is.
- *Deriving dates from transaction timestamps* → transactions carry an instant and no
  period; they are dated by this mapping, not the other way round.
- *Moving the model to the intermediate layer because it now reads two sources* → a
  rename through two models and five tests for no change in behaviour. Left for the
  owner as a separate choice.

## Requirements

### R1. A scoring period is dated from MLB's schedule

- R1.1 THE SYSTEM SHALL take as a season's opening day the earliest `official_date`
  among that season's regular-season games (`game_type = 'R'`) in `stg_mlb__games`.
- R1.2 THE SYSTEM SHALL give scoring period 1 of a league-season its season's opening
  day, and scoring period *p* the date *p* − 1 days later.
- R1.3 THE SYSTEM SHALL produce one row for every scoring period from 1 to that
  league-season's own `final_scoring_period`, at the grain and with the columns the
  model has today: `league_id`, `season`, `scoring_period`, `scoring_date`.
- R1.4 THE SYSTEM SHALL NOT use `latest_scoring_period`, `fetched_at` or the number of
  settings captures in deriving a scoring date.
- R1.5 IF a league-season has no regular-season MLB game of its season loaded THEN THE
  SYSTEM SHALL keep its rows with a null `scoring_date`, so that the existing `not_null`
  test fails the build.
- R1.6 WHEN two seasons are loaded THE SYSTEM SHALL date each league-season from its own
  season's opening day.

### R2. The settings model says what the counter is

- R2.1 THE SYSTEM SHALL describe `latest_scoring_period` in the model's YAML as ESPN's
  own counter, which stops after the season and is not a date.
- R2.2 THE SYSTEM SHALL fail the build when `final_scoring_period` is null, since a
  league-season without one would get no scoring periods at all.

### R3. The mapping is checked against ESPN's own game lines

ESPN's roster payloads record, for each scoring period, one stat line per game a
rostered player appeared in. They are a record of which games ESPN scored on which
period that the opening-day rule does not use.

- R3.1 THE SYSTEM SHALL fail the build for every scoring period in which the number of
  distinct ESPN games in `stg_espn__player_game_stats` exceeds the number of played MLB
  games on that period's `scoring_date`.
- R3.4 THE SYSTEM SHALL warn, without failing the build, of every scoring period of a
  league-season with roster entries whose `scoring_date` has a played MLB game and which
  has no ESPN game line: for that period R3.1 checked nothing.
- R3.5 THE SYSTEM SHALL describe R3.1 as a count comparison, a partial signal. The
  player-level evidence is `rec_espn__player_day_differences`, which is read in the
  real-season verification and not turned into a test here.
- R3.2 THE SYSTEM SHALL keep `stg_espn__scoring_periods_start_on_opening_day`, with a
  header that says what it now catches: an error in the arithmetic of R1.2 and a
  league-season with no MLB season loaded. It no longer claims two independent sources.
- R3.3 THE SYSTEM SHALL keep the consecutive-dates, own-final-period and
  one-period-per-date tests unchanged.

### R4. The audit judges only a counter that can be judged

- R4.1 THE SYSTEM SHALL treat a settings capture as *in progress* when its
  `latestScoringPeriod` is at most its `finalScoringPeriod`, and as *past the final
  period* otherwise.
- R4.2 WHEN an in-progress capture implies a date for period 1 other than MLB opening
  day THE SYSTEM SHALL report an error naming the capture, the implied date and opening
  day.
- R4.3 THE SYSTEM SHALL NOT compare a capture past the final period with opening day or
  with any other capture, and SHALL report the number of such captures as information.
- R4.4 IF no MLB schedule is landed for the season THEN THE SYSTEM SHALL report an
  error, because scoring periods cannot be dated without one.
- R4.7 THE SYSTEM SHALL have the audit take opening day by the model's rule (R1.1): the
  earliest official date among all regular-season games of the newest landed schedule,
  played or not. Today it takes the earliest played game, so a schedule landed before
  the season starts has no opening day.
- R4.8 IF a settings capture's status lacks a usable `latestScoringPeriod` or
  `finalScoringPeriod` THEN THE SYSTEM SHALL report a warning naming the capture, and
  SHALL count it neither as in progress nor as past the final period.
- R4.5 WHEN every in-progress capture implies opening day THE SYSTEM SHALL report that as
  information, with the number of captures.
- R4.6 THE SYSTEM SHALL leave the audit's roster-finality and transaction findings as
  they are.

### R5. Tests

- R5.1 THE SYSTEM SHALL replace the unit test
  `scoring_period_dates_use_the_eastern_day_boundary`, which asserts the anchor rule,
  with a unit test in which the settings row has `latest_scoring_period` 188, a
  `fetched_at` of 2026-10-07 and a final period of 3, and MLB's first regular-season
  game is 2026-03-25: periods 1 to 3 must be 2026-03-25 to 2026-03-27.
- R5.2 THE SYSTEM SHALL give `scoring_periods_run_to_each_leagues_own_final_period` the
  MLB input it now needs, with its expectation unchanged.
- R5.3 THE SYSTEM SHALL have unit tests for: two seasons each dated from their own
  opening day; a game of another `game_type` earlier than the first regular-season game,
  which must not move opening day; and a league-season with no MLB game, whose rows keep
  a null date.
- R5.4 THE SYSTEM SHALL replace the audit tests that assert every settings capture must
  imply one date with tests of R4.1 to R4.5, R4.7 and R4.8 (a schedule with no game
  played yet still gives an opening day; a status with no final period is a warning),
  including the 2026 situation itself: three
  captures past the final period that imply opening day and two that do not, audited
  without an error.

## Expected values

Measured on 2026-10-07, read-only, on the real warehouse (loaded up to settings capture
`20260928T225612Z`) and the real landing zone.

| Check | Expected | How to verify |
|---|---|---|
| `stg_espn__scoring_periods` before the change | 180 rows; period 1 = 2026-03-25, period 180 = 2026-09-20 | query, recorded as the starting point |
| Regular-season MLB games loaded | 2,430, of which 2,429 played, on 184 dates from 2026-03-25 to 2026-09-27 | `stg_mlb__games` |
| The model after the change, same load | the same 180 rows: `EXCEPT` both ways against the kept copy is empty | query against `data/warehouse_pre70.duckdb` |
| The model after `front-office load` takes both frozen runs | the same 180 rows | the same query |
| What the old model gives after that load | period 1 = 2026-04-03, period 180 = 2026-09-29 | arithmetic from the table above; not built |
| Periods with ESPN game lines | 177 of 180; 2,339 distinct ESPN games, summed over periods | `stg_espn__player_game_stats` |
| Distinct ESPN games equal played MLB games on the period's date | 177 of 177 periods | R3.1's query, with `=` in place of `>` |
| The 3 periods with no ESPN game line | all fall on dates with no MLB game | the same |
| Rows from the R3.1 test | 0 | `dbt build` |
| Rows from the R3.4 warning, real season | 0: all 177 periods with a played MLB game have ESPN lines | `dbt build` |
| Rows from the R3.4 warning, CI | 2: the fixture rosters carry no game lines, so CI gains one warning | `dbt build --target ci` |
| `rec_espn__player_day_differences`, same load | 22 rows before and after: every started player-day still meets the same ESPN line | query against the kept copy |
| Rows from the R3.1 test if dates were shifted by −1, +1, +8, +9 days | 69, 63, 64, 69 periods | one-off query; shows the test bites |
| Captures loaded by `front-office load` | 12 ESPN, 27 MLB boxscores, 1 MLB schedule | `front-office audit` before; no "not in raw.api_responses" line after |
| Audit, `espn` section, after the change | no "imply different dates" error; 5 captures past the final period reported as information | `uv run front-office audit --season 2026` |
| Audit total after the load | 0 errors, 0 warnings | the same |
| Fixture season in CI | periods 1 and 2 = 2026-04-29 and 2026-04-30, as today | `dbt build --target ci` |
| Files changed under `fixtures/` or `dbt/seeds/` | none | `git diff --stat main` |

Mart numbers after the load are not expected to be identical to today's: the load also
brings new roster captures of periods 179 and 180, a new matchups and transactions
capture and 27 corrected boxscores. What moves, and whether it reconciles, is reported
for the owner to judge; this spec claims only that no scoring date moves.
