# Roster fixtures on the fixture days, with ESPN's game lines — requirements

Issue: #74 · Tier: M · Status: draft

## Problem

The CI fixture season is two days, 2026-04-29 and 2026-04-30: the MLB schedule and
boxscores are from those days, and since #73 so is ESPN's pro schedule (real scoring
periods 36 and 37, renumbered 1 and 2). The roster fixtures are not. They are built
from real periods 100 and 101, which are 2026-07-02 and 2026-07-03, and renumbered the
same way. Nothing shows the mismatch, because the roster fixtures also leave out ESPN's
per-game stat lines: `stg_espn__player_game_stats` has no rows in CI.

So three singular tests that compare those lines with something else have no input in
CI:

- `stg_espn__scoring_periods_agree_with_espn_game_lines` (#70),
- `stg_espn__player_game_stats_games_are_scheduled` (#73),
- `stg_espn__scoring_periods_have_game_lines_to_check` (#70), which exists to say so and
  warns with 2 rows on every CI run.

Adding lines from periods 100 and 101 would be wrong, not merely unhelpful: those games
are not in the fixture's pro schedule, and on fixture period 2 they are 13 games against
11 played in the MLB fixture.

A throwaway spike on 2026-10-07 (not committed) rebuilt the rosters from periods 36 and
37 with their game lines. Only the roster and id-map fixtures changed, every gate
passed, and CI's warnings fell from 6 to 3. The expected values below are from it.

## Goals

- Rosters, ESPN's game lines, ESPN's pro schedule and MLB's games in the fixtures all
  describe the same two real days.
- The three game-line tests compare real rows on every CI run.
- The warning that says they could not is gone from CI because it has nothing to report.
- Nothing about league members reaches the fixtures.

## No-gos

- **No change to any dbt model, macro, seed or test SQL.** Comments that say the tests
  have nothing to compare in CI are corrected; nothing else.
- **No change to the MLB fixture dates or to the number of fixture boxscores** (2 of the
  24 games).
- **No change to the matchup or transaction fixtures.** They are not from the fixture
  days either (see *Open questions* in the design) and are not made so here.
- **No change to the severity of `stg_espn__scoring_periods_have_game_lines_to_check`.**
  It stays a warning: in season it has a real reason to fire for a day or two.
- **No request to ESPN or MLB.** The fixtures are rebuilt from what is landed.
- **No change to the forbidden patterns of the privacy check.**

## Rabbit holes

- *Trimming each line's stats to the scored categories* → the whole `stats` map is kept,
  as `scoreByStat` already is in the matchup fixture: stat ids and numbers. (The owner,
  2026-10-07: general, not tailored to this league's settings.)
- *More fixture boxscores so the player-day reconciliation is quiet in CI* → out of
  scope; that table has no test in CI and its size there is recorded, not judged.
- *Making the matchup fixture span the same two days* → a real matchup's totals cover
  its whole 12-day span and cannot be cut to two days honestly.
- *A negative case in CI for each singular test* → dbt cannot unit-test a singular test.
  The cases run on the real season in #70 and #73 stand.
- *Why ESPN's period-36 roster carries a line for every rostered player and period 37's
  does not* → noted as an open question; the staging model already keeps only lines
  with stats.

## Requirements

### R1. One pair of source periods

- R1.1 THE SYSTEM SHALL build the roster fixtures and the pro schedule fixture from the
  same real scoring periods, named by one constant in `scripts/make_fixtures.py`: 36
  and 37.
- R1.2 THE SYSTEM SHALL fail fixture generation if the Eastern dates of those periods in
  the landed pro schedule are not exactly the MLB fixture dates, in order.
- R1.3 THE SYSTEM SHALL keep renumbering them 1 and 2 everywhere they appear.
- R1.4 THE SYSTEM SHALL take every ESPN fixture source from captures of season 2026
  only. Today the newest capture is chosen by path among all seasons, so a roster of
  period 36 landed for another season would be picked while the 2026 pro schedule still
  passed R1.2.
- R1.5 IF league captures of more than one league are landed for season 2026 THEN THE
  SYSTEM SHALL fail fixture generation, saying how many leagues it found, and SHALL NOT
  choose between them.

### R2. Game lines in the roster fixtures

- R2.1 THE SYSTEM SHALL copy, for each roster entry, the player's stat lines whose
  `statSourceId` is 0, whose `statSplitTypeId` is 5 and whose `scoringPeriodId` is the
  source period of that roster, and no other line.
- R2.2 THE SYSTEM SHALL rebuild each kept line from an allowlist of exactly
  `scoringPeriodId`, `statSourceId`, `statSplitTypeId`, `externalId` and `stats`, with
  `scoringPeriodId` renumbered as R1.3 says.
- R2.3 THE SYSTEM SHALL leave an entry with no such line without a `stats` key.
- R2.4 THE SYSTEM SHALL keep every other allowlisted roster field as it is today.

### R3. Regenerated fixtures

- R3.1 WHEN `scripts/make_fixtures.py` is run THE SYSTEM SHALL change, under
  `fixtures/landing/`, only the two roster payloads and the id-map payload.
- R3.2 WHEN `scripts/make_multi_fixtures.py` is run THE SYSTEM SHALL change, under
  `fixtures/landing_multi/`, only the six roster payloads and the id-map payload.
- R3.3 IF any other fixture file changes THEN the build SHALL stop and report the
  difference before committing anything.
- R3.4 THE SYSTEM SHALL keep the fixture privacy test passing unchanged.

### R4. What CI then checks

- R4.1 THE SYSTEM SHALL have `stg_espn__player_game_stats` hold rows for both fixture
  periods in CI.
- R4.2 THE SYSTEM SHALL have the three game-line tests pass in CI with those rows, and
  `stg_espn__scoring_periods_have_game_lines_to_check` return no row.
- R4.3 THE SYSTEM SHALL keep the tenant-isolation check at 0 differing pairs.

### R5. Tests and words

- R5.1 THE SYSTEM SHALL have a pytest of the committed roster fixtures: every stat line
  has exactly the five allowlisted keys, source 0 and split type 5, and its roster's own
  fixture period; every line's `externalId` is a game of that period in the committed
  pro schedule fixture; both periods have at least one line with stats.
- R5.2 THE SYSTEM SHALL have pytest of R1.2, R1.4 and R1.5 on a small made-up landing
  zone: a period on the wrong date; a newer capture of the same period for another
  season, which must not be chosen; two leagues in the season.
- R5.3 THE SYSTEM SHALL correct the header comments of the three game-line tests, and
  the comments in `scripts/make_fixtures.py`, that say the fixture rosters carry no game
  lines or are from other days.

## Expected values

From the spike of 2026-10-07 on the landing zone as it is, and from `main`. The build
regenerates; a number that differs is reported, not adjusted.

| Check | Now, on `main` | Expected |
|---|---|---|
| Fixture files changed, `fixtures/landing/` | — | 3: two roster payloads, the id map |
| Fixture files changed, `fixtures/landing_multi/` | — | 7: six roster payloads, the id map |
| Roster entries, periods 1 and 2 | 309 and (not recorded) | 307 and 306 |
| Stat lines kept, periods 1 and 2 | 0 and 0 | 307 lines over 15 games; 222 lines over 11 games, on 178 entries |
| Roster payload sizes | 122 KB each | 311 KB and 268 KB |
| `fixtures/landing` / `fixtures/landing_multi` on disk | 464 KB / 1.2 MB | 812 KB / 2.3 MB |
| `stg_espn__player_game_stats` in CI, per period | 0 rows | period 1: 5,743 rows, 137 players, 13 games; period 2: 4,654 rows, 97 players, 11 games |
| Played MLB games on the two fixture dates | 13 and 11 | 13 and 11: equal to ESPN's games with stats |
| (period, game) pairs in the lines that are scheduled on the same period | none to check | 24 of 24 |
| CI `dbt build` | `PASS=429 WARN=6 ERROR=0` | `PASS=432 WARN=3 ERROR=0` |
| CI warnings that go | — | `…have_game_lines_to_check` (2 rows), `stg_idmap__covers_started_players` (1), `dim_player_league_seasons_rostered_players_are_resolved` (1) |
| CI warnings that stay | — | `rec_espn__register_matchups_exist` (28), `rec_espn__every_side_is_verified` (4), `int_fantasy__started_player_days_inputs_all_verified` (1, was 2) |
| `rec_espn__player_day_differences` in CI | 21 rows | 308 rows: ESPN now has lines for players whose boxscore is not among the 2 in the fixtures. No test reads it in CI |
| `rec_espn__matchup_stat_differences` in CI | 96 `unverified` | 96 `unverified` |
| pytest | 641 passed | all pass, plus the new ones |
| Tenant isolation | 0 differing pairs | 0 |
| Real season | — | no model changes: the three tests return 0 rows and no warning, as today |
