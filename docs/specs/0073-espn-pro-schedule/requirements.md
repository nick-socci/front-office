# ESPN's pro schedule: every scoring period is dated by ESPN's own games — requirements

Issue: #73 · Tier: M · Status: draft

## Problem

A scoring period's date is the bridge between ESPN rosters and MLB game logs. Since #70
(ADR 0021) it is a rule about ESPN read off MLB's schedule: period 1 is MLB's first
regular-season official date, and each later period is the next day. The rule is right
for 2026, but it is our inference, it makes `stg_espn__scoring_periods` the one staging
model that reads another source's staging model, and it means an ESPN league-season
cannot be dated unless MLB's schedule for that season is landed too (#57 would need one
per past season).

ESPN publishes the answer. Its game-level season resource, with
`view=proTeamSchedules_wl`, lists every pro game with its start time and its scoring
period. It needs no league id and no credentials. Checked on 2026-10-07 with four
requests that were not landed: in 2026, 2025, 2024 and 2018 every period with a game
falls on one Eastern date, on a line of one period per day from period 1. Against the
2026 warehouse: all 2,339 distinct (period, game) pairs in ESPN's roster stat lines are
in the schedule, each with the same period.

## Goals

- A scoring period is dated from ESPN's own schedule, and the model that does it reads
  only ESPN data again.
- MLB's opening day goes back to being evidence from an independent source.
- Every ESPN per-game stat line can be tied to a scheduled game and its date.
- The model can date a league-season from ESPN data alone. (Whether a build with no MLB
  season loaded should pass is not decided here: see R4.1.)
- The 180 scoring dates of 2026 do not move.

## No-gos

- **No fetch for any season but 2026.** The command takes `--season`, but past seasons
  are #57's.
- **No league credentials on this request.** The resource is public; the cookies are not
  sent to it.
- **No mapping of ESPN pro teams or games to MLB teams or `game_pk`.** The staged
  columns keep ESPN's ids; matching them to MLB is not needed to date a period.
- **No staging of `statsOfficial`, `validForLocking`, `startTimeTBD` or `byeWeek`.** What
  they mean is not established (see *Open questions*).
- **No change to the roster re-check rule** (#75), though this lands the data it wants.
- **No ESPN game lines in the roster fixtures** (#74).
- **No change to the grain, name or columns of `stg_espn__scoring_periods`.**
- **No change to how MLB games are staged.**

## Rabbit holes

- *Dating a period with no game from its neighbours* → no neighbour logic. Every game
  implies a date for period 1 (its own date minus its period, plus one); all of them
  must agree, and every period is counted from that one date.
- *Entity-grain history of the schedule* (a game as of each capture) → the schedule is
  read whole, from its newest capture. A game that ESPN removes should disappear.
- *Explaining why ESPN lists 2,458 games where MLB has 2,430* → postponed games stay
  listed on their original day. Nothing here counts ESPN's games against MLB's.
- *Matching ESPN's game to MLB's to compare dates game by game* → needs a team map and a
  rule for doubleheaders. The count comparison of #70 stays as the cross-source check.
- *Reading `currentScoringPeriod` from the bare season resource* → that is the counter
  that stops (ADR 0022). Not landed.

## Requirements

### R1. The pro schedule is landed

- R1.1 WHEN the pro schedule is fetched for a season THE SYSTEM SHALL request ESPN's
  game-level season resource with `view=proTeamSchedules_wl` and land the response
  unchanged as a capture of source `espn`, endpoint `pro_schedule`, with the single
  partition `season`.
- R1.2 THE SYSTEM SHALL make that request with a client that carries no cookies, and
  SHALL NOT read ESPN credentials in order to make it.
- R1.3 WHEN `front-office backfill espn --season <year>` runs THE SYSTEM SHALL land the
  pro schedule before the league's own captures, under the run's stamp.
- R1.4 WHEN `front-office backfill espn --season <year> --only pro-schedule` runs THE
  SYSTEM SHALL land the pro schedule alone and SHALL succeed with no `.env` present.
- R1.5 THE SYSTEM SHALL treat the pro schedule as a snapshot: every run lands a new
  capture, and none is skipped because an earlier one exists.
- R1.6 IF the response is not a JSON object with a `settings.proTeams` list THEN THE
  SYSTEM SHALL land no capture and treat the pro schedule as failed.
- R1.7 (The owner, 2026-10-07.) IF the pro schedule fails in a full `backfill espn` run,
  by R1.6 or because the request kept failing, THEN THE SYSTEM SHALL report it, go on to
  fetch the league's captures, and exit non-zero at the end, as it does for an
  incomplete transaction log. With `--only pro-schedule` the failure ends the run.

### R2. Scheduled games are staged

- R2.1 THE SYSTEM SHALL provide `stg_espn__pro_games` with one row per (`season`,
  `espn_game_id`), read from the newest pro schedule capture of each season.
- R2.2 THE SYSTEM SHALL give each row: `season`, `espn_game_id` (text, as in
  `stg_espn__player_game_stats`), `scoring_period`, `game_start_at_utc`, `game_date`
  (the US/Eastern date of the start), `home_pro_team_id`, `away_pro_team_id` and
  `fetched_at`.
- R2.3 THE SYSTEM SHALL keep one row for a game although ESPN lists it under both of its
  teams. The two listings are identical in every staged column; if they ever differ, the
  uniqueness test of R2.4 fails, which is the wanted outcome.
- R2.4 THE SYSTEM SHALL fail the build if (`season`, `espn_game_id`) is not unique, or
  if any staged column is null.
- R2.5 THE SYSTEM SHALL fail the build for every game whose `game_date` is not the date
  of period 1 of its season plus its `scoring_period` minus one, period 1's date being
  the earliest such date any game of the season implies.
- R2.6 THE SYSTEM SHALL project the payload away before any `unnest` (AGENTS.md rule 1).

### R3. Scoring periods are dated from the pro schedule

- R3.1 THE SYSTEM SHALL date scoring period 1 of a league-season with the date its
  season's games imply (R2.5), and period *p* with the date *p* − 1 days later.
- R3.2 THE SYSTEM SHALL keep the grain, the four columns and the row set of
  `stg_espn__scoring_periods`: one row per period from 1 to the league-season's own
  `final_scoring_period`.
- R3.3 THE SYSTEM SHALL NOT read `stg_mlb__games`, `latest_scoring_period` or any
  capture stamp in deriving a scoring date.
- R3.4 IF a league-season has no pro schedule of its season loaded THEN THE SYSTEM SHALL
  keep its rows with a null `scoring_date`, so that the `not_null` test fails the build.
- R3.5 WHEN two seasons are loaded THE SYSTEM SHALL date each league-season from its own
  season's pro schedule, and two leagues of one season from the same one.

### R4. The checks

- R4.1 THE SYSTEM SHALL keep `stg_espn__scoring_periods_start_on_opening_day`, SQL
  unchanged, with a header saying it is again a comparison of two independent sources.
  It still fails for a league-season with no MLB season loaded, so a build of such a
  season does not pass although its periods are dated. Whether that case becomes a
  warning is left to #57, the first work that would load one; a test is not relaxed
  here for a case that does not exist yet.
- R4.2 THE SYSTEM SHALL keep the two game-line tests of #70 unchanged.
- R4.3 THE SYSTEM SHALL fail the build for every ESPN per-game stat line whose game is
  not in `stg_espn__pro_games` for its season, or is there with another scoring period.
- R4.4 THE SYSTEM SHALL keep the consecutive-dates, own-final-period and
  one-period-per-date tests unchanged.

### R5. The audit

- R5.1 THE SYSTEM SHALL have the audit report an error for an ESPN league-season with no
  committed pro schedule capture of its season, because its periods cannot be dated.
- R5.2 THE SYSTEM SHALL have the audit take period 1's date from the newest pro schedule
  capture by the model's rule (R2.5), and compare in-progress settings captures (ADR
  0022) with that date, where it compares them with MLB opening day today.
- R5.3 WHEN period 1's date differs from MLB opening day THE SYSTEM SHALL report an
  error naming both; IF no MLB schedule is landed THEN THE SYSTEM SHALL report, in the
  `espn` section, a warning that there is nothing to confirm the date against, where it
  reports an error that periods cannot be dated today.
- R5.4 IF games of the newest pro schedule imply more than one date for period 1 THEN
  THE SYSTEM SHALL report an error with the dates and a count of games for each; IF it
  holds no game with a usable `date` and `scoringPeriodId` THEN THE SYSTEM SHALL report
  an error that the capture dates nothing.
- R5.5 THE SYSTEM SHALL leave the audit's other findings as they are. That includes the
  `mlb` section's own error for a season with no committed MLB schedule: a season audited
  with ESPN data alone still ends with that error, as R4.1's test still fails for it.

### R6. Fixtures and isolation

- R6.1 THE SYSTEM SHALL add a pro schedule fixture for 2026, generated by
  `scripts/make_fixtures.py` from the landed capture by allowlist: each pro team's `id`
  and, for real scoring periods 36 and 37 only (2026-04-29 and 2026-04-30, the MLB
  fixture dates), each game's `id`, `date`, `scoringPeriodId`, `homeProTeamId` and
  `awayProTeamId`, with the periods renumbered 1 and 2.
- R6.2 THE SYSTEM SHALL have `scripts/make_multi_fixtures.py` derive the 2027 pro
  schedule from the 2026 fixture, as it derives the rest of 2027: one scoring period, on
  the shifted calendar.
- R6.3 THE SYSTEM SHALL have the tenant-isolation check give each single league-season
  build its season's pro schedule, and SHALL keep it at 0 differing pairs.
- R6.4 THE SYSTEM SHALL keep the fixture privacy test passing with no change to the
  forbidden patterns.

### R7. Tests

- R7.1 THE SYSTEM SHALL test the fetch with a fake transport: the URL and view; that no
  cookie is sent; the capture's source, endpoint and partition; that a malformed
  response lands nothing; that `--only pro-schedule` works with no credentials set; and
  that a full run whose pro schedule fails still lands the league's captures and exits
  non-zero.
- R7.2 THE SYSTEM SHALL have dbt unit tests for `stg_espn__pro_games`: a game listed
  under both teams is one row; a start at 02:05 UTC belongs to the previous Eastern
  date; only the newest capture of a season is read; two seasons stay apart.
- R7.3 THE SYSTEM SHALL replace the unit tests of `stg_espn__scoring_periods` that give
  it `stg_mlb__games` with ones that give it `stg_espn__pro_games`: dates do not depend
  on the settings capture; a period with no game (a gap) is still dated; each season
  from its own schedule; no schedule gives null dates; each league to its own final
  period.
- R7.4 THE SYSTEM SHALL have audit tests for R5.1 to R5.4, including a capture with an
  empty `proTeams` list.

## Expected values

Measured on 2026-10-07 from the response fetched that day (not landed) and the real
warehouse, read-only. The build lands a new capture; a number that differs is reported,
not adjusted.

| Check | Expected | How to verify |
|---|---|---|
| Pro teams in the response | 31, one of them (id 0) with no games | landed payload |
| Team-game entries / distinct games, 2026 | 4,916 / 2,458 | `stg_espn__pro_games` row count 2,458 |
| Periods with a game | 184, from 1 to 187; none in 111, 112, 113 | query |
| Dates implied for period 1 by the 2,458 games | one: 2026-03-25 | R2.5's test returns 0 rows |
| Games whose UTC date is not their Eastern date | 583 | query; shows the Eastern conversion matters |
| Games in periods after 180 | 92, in 7 periods | query |
| `stg_espn__scoring_periods` | the same 180 rows as today: `EXCEPT` both ways is empty | against rows saved before the change |
| MLB opening day | 2026-03-25, equal to period 1 | `stg_espn__scoring_periods_start_on_opening_day` passes |
| ESPN stat lines: distinct (period, game) | 2,339, all in the schedule with the same period | R4.3's test returns 0 rows |
| Scheduled games in periods 1 to 180 | 2,366, of which 2,339 appear in stat lines | query |
| R4.3's query with every scheduled period moved by one | 2,339 rows: every line is on another period | one-off query; shows the period comparison bites |
| R4.3's query with one game removed from the schedule | as many rows as that game has (league, period) pairs in the lines, at least 1 | one-off query; shows the missing-game branch bites |
| The two game-line tests of #70 | 0 rows each on the real season | `dbt build` |
| Built tables other than the new one | all 36 identical apart from `fetched_at` | multiset comparison with a copy taken before |
| Audit | 0 errors, 0 warnings; one pro schedule capture reported | `uv run front-office audit --season 2026` |
| Fixture: games in periods 1 and 2 | 15 and 11, on 2026-04-29 and 2026-04-30 | fixture payload |
| CI | passes; periods 1 and 2 = 2026-04-29 and 2026-04-30; warnings unchanged at 6 | `dbt build --target ci` |
| Tenant isolation | 0 differing pairs | `.agentic/gates` |
