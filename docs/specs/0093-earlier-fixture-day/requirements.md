# An earlier fixture day, so the start pool is not empty in CI — requirements

Issue: #93 · Tier: M · Status: draft

## Problem

Under ADR 0029 a free-agent start counts toward the start replacement level only when the
pitcher was a starter on his earlier appearances of the season. The CI fixture season is
two days, 2026-04-29 and 2026-04-30, so no start in it has an earlier appearance. In CI
today the start pool has 0 pitchers and 0 played days, its level is null, 16 rows of
`fct_player_category_value` and 2 of `fct_player_season_value` are null (the two fixture
starts in lineups), and `int_fantasy__replacement_pool_has_played_days` warns. CI no
longer computes a starter's value end to end.

The issue asks for a third, earlier fixture day carrying MLB data only, "unless the
scoring-date logic requires a roster for it: to be checked". It was checked, on the real
season and in a throwaway spike on 2026-10-09 (not committed):

- **The earlier day cannot sit outside the fixture season.** MLB's earliest game of a
  season must be the date of ESPN's first scoring period
  (`stg_espn__scoring_periods_start_on_opening_day`), and periods are consecutive
  calendar days counted from period 1 (ADR 0023,
  `stg_espn__scoring_periods_are_consecutive`). An MLB game before fixture period 1 fails
  the build. The earlier day has to become period 1.
- **It cannot be the day before.** Starters pitch in a rotation: a turn comes every
  fifth day, or every sixth when a team carries six starters. In 2026, 1,338 starts came
  5 days after the pitcher's previous one and 2,111 came 6 days after; 13 came within 3
  days, which is an opener or an emergency, not a starter's turn. So a fixture that
  holds a start and the same pitcher's previous turn spans at least six consecutive
  scoring periods, whichever days are chosen. (The owner, 2026-10-09: this is how
  baseball works, not a finding about these dates.)
- **One turn back from an existing fixture game is one new boxscore.** Both fixture
  boxscores (games 822821 and 822907) are from 2026-04-29. Pitcher 678394 started game
  822821 for Boston, was on no roster of the league that day, and had made five earlier
  appearances, all starts. His previous turn was Boston's game five days earlier, on
  2026-04-24: game 824854. That is real scoring period 31; the fixture days are
  36 and 37.

So the fixture season has to run from 2026-04-24 to 2026-04-30: seven periods, the six a
rotation turn needs plus the existing second day, with data on the first and the last
two. The four periods between are the days between two turns.

## Goals

- CI's start pool has a played day, and the two fixture starts in lineups have a value.
- `int_fantasy__replacement_pool_has_played_days` is gone from CI because it has nothing
  to report, and no other warning takes its place.
- Every fixture is still real data cut down, rebuilt from allowlists.
- The fixture cannot silently stop serving this purpose: generation fails if it does.

## No-gos

- **No change to any dbt model, macro, seed or test SQL.** Comments that describe the
  fixture as two days are corrected; nothing else.
- **No change to the two existing boxscore fixtures or the synthetic correction
  snapshot**: byte for byte.
- **No change to `scripts/make_multi_fixtures.py`.** If regeneration shows it needs one,
  that is a stop (R4.4).
- **No making `rec_fantasy__category_wins_added` non-empty in CI.** It is empty there
  because no fixture matchup is re-scorable (spec 0089: unverified inputs), not because of
  the start pool. See *Open questions* in the design.
- **No change to the matchup or transaction fixtures' sources**, the 2025 fixtures, the
  privacy patterns, or the severity of any test.
- **No request to ESPN or MLB.** Everything is rebuilt from what is landed.
- **No change to who counts as a starter** (#92).

## Rabbit holes

- *Rosters for all seven periods* → no: about 300 KB each, and four of them would carry
  no boxscore. Periods 2 to 5 are days of the season with nothing landed for them.
- *More boxscores so the player-day reconciliation is quiet* → out of scope, as in spec
  0074 (#81). Its size in CI is recorded, not judged.
- *A second pool pitcher (641778, whose earlier start is 2026-04-22)* → one is enough to
  exercise the rule; a second would stretch the season to nine periods.
- *Deriving the earlier game from the data instead of naming it* → named, with a check
  that it does its job (R3). A search would pick a different game when the landing zone
  changes and move every fixture with it.
- *Why the generator leaves stale capture directories behind* → it only writes. The
  build removes the old roster directories with `git rm`; changing the generator to
  delete is not in scope.

## Requirements

### R1. A seven-period fixture season

- R1.1 THE SYSTEM SHALL build the 2026 fixtures from real scoring periods 31, 36 and 37,
  named by one constant in `scripts/make_fixtures.py`, and from the dates 2026-04-24,
  2026-04-29 and 2026-04-30.
- R1.2 THE SYSTEM SHALL number a fixture period as its real period minus the first real
  period plus one, everywhere a source period is mapped (roster partitions and
  payloads, stat lines, pro schedule): 1, 6 and 7. The 2025 fixtures, whose source
  periods are 1 and 2, SHALL keep 1 and 2. Matchups are not mapped: see R1.3.
- R1.3 THE SYSTEM SHALL set the fixture settings' current, latest and final scoring
  period to the span, 7. The fixture matchups are the season's first two, as today;
  their own `pointsByScoringPeriod` keys are trimmed to 1 through the span, not offset,
  so they keep keys 1 to 7.
- R1.4 THE SYSTEM SHALL keep failing generation unless each source period's games in the
  landed pro schedule fall on exactly its fixture date (spec 0074, R1.2), now for three
  periods.
- R1.5 THE SYSTEM SHALL carry, in the MLB schedule fixture and the pro schedule fixture,
  the games of those three dates and periods only.

### R2. The earlier day's data

- R2.1 THE SYSTEM SHALL write a roster fixture for each of the three periods, by the
  existing allowlists, with the period's game lines (spec 0074, R2). (The owner,
  2026-10-09: a roster on the earlier day too; ADR 0030.)
- R2.2 THE SYSTEM SHALL choose the two existing boxscores as today, from the dates of the
  last two periods only, and SHALL add the boxscore of one named game of the first date:
  824854, the previous turn of a starter of game 822821.
- R2.3 THE SYSTEM SHALL rebuild that boxscore from the existing boxscore allowlists.
- R2.4 THE SYSTEM SHALL still write the synthetic correction snapshot for game 822821.

### R3. The fixture keeps its purpose

- R3.1 IF no pitcher (a) has `gamesStarted` in the named earlier boxscore, with outs
  recorded there and no more plate appearances than batters faced, (b) has
  `gamesStarted` in a later fixture boxscore, and (c) is absent from every fixture
  roster of that later boxscore's period (matched through the id-map fixture) THEN THE
  SYSTEM SHALL fail generation, before anything is written, saying which of the three
  failed. (a) is what `fo_replacement_group` reads to call one earlier start `SP`.
- R3.2 THE SYSTEM SHALL have a pytest of the committed fixtures asserting the same of the
  files as committed.

### R4. Regenerated fixtures

- R4.1 WHEN `scripts/make_fixtures.py` is run THE SYSTEM SHALL change, under
  `fixtures/landing/`, only: the 2026 MLB schedule (payload and sidecar), the 2026 pro
  schedule, settings and matchups payloads, the id map payload, the rosters (period 1
  rewritten; period 2 removed; periods 6 and 7 added), and the new boxscore.
- R4.2 THE SYSTEM SHALL leave the two existing boxscores, the correction snapshot, the
  teams and transactions fixtures and every 2025 fixture byte-identical.
- R4.3 WHEN `scripts/make_multi_fixtures.py` is run unchanged THE SYSTEM SHALL produce a
  tree whose 2027 season is one scoring period on 2027-04-23, with one boxscore, game
  1824854.
- R4.4 IF any file outside R4.1 changes under `fixtures/landing/`, or the multi script
  needs a change THEN the build SHALL stop and report before committing anything.
- R4.5 THE SYSTEM SHALL keep the fixture privacy test passing unchanged.

### R5. What CI then computes

- R5.1 THE SYSTEM SHALL have the start kind of the fixture league-season hold at least
  one pool player and one played day, with a non-null level, in CI.
- R5.2 THE SYSTEM SHALL have no null `scaled_value` in `fct_player_category_value` and no
  null `total_value` in `fct_player_season_value` in CI.
- R5.3 THE SYSTEM SHALL have the CI build pass with three warnings, the three it had
  before #89, and `int_fantasy__replacement_pool_has_played_days` return no row.
- R5.4 THE SYSTEM SHALL keep the tenant-isolation check at 0 differing pairs.

### R6. Tests and words

- R6.1 THE SYSTEM SHALL have pytest, on a made-up landing zone, of R1.2 (offset
  numbering, and 2025 unchanged), R2.2 (an earlier date's lower game id does not displace
  an existing boxscore) and R3.1: one case for each of (a), (b) and (c) failing, each
  checked by its message, and one for a start with no outs under (a).
- R6.2 THE SYSTEM SHALL update the three pytest that pin the committed fixtures to
  periods 1 and 2 so that they pin 1, 6 and 7 with their dates and game counts. They are
  tightened to the new shape, not loosened.
- R6.3 THE SYSTEM SHALL correct the comments that call the fixture two days or two
  periods: in `scripts/make_fixtures.py`, the three game-line test headers,
  `values_track_rescored_category_wins.sql`,
  `stg_espn__every_scoring_period_has_one_matchup.sql`, and the unit test description
  in `_intermediate__models.yml`.

## Expected values

"Now" is `main` at e4c3bf4. "Expected" is the spike of 2026-10-09 on the landing zone as
it is. The build regenerates; a number that differs is reported, not adjusted.

| Check | Now | Expected | How to verify |
|---|---|---|---|
| Fixture scoring periods, 2026 | 1–2: 04-29, 04-30 | 1–7: 04-24 to 04-30 | `stg_espn__scoring_periods` in `ci.duckdb` |
| MLB schedule fixture, games per date | 13, 11 | 14, 13, 11 (40 entries, 38 distinct `gamePk`) | `stg_mlb__games`; generator output |
| Pro schedule fixture, distinct games | 26 | 40, on periods 1, 6, 7 | generator output |
| Roster entries / with game lines | 307/307, 306/178 | period 1: 308/285; 6: 307/307; 7: 306/178 | generator output |
| `stg_espn__player_game_stats` per period | 5,743 and 4,654 rows | 1: 6,252 rows, 150 players, 14 games; 6: 5,743, 137, 13; 7: 4,654, 97, 11 | query |
| Boxscore player-days | 04-29: 56, 4 starts | 04-24: 26, 2 starts; 04-29: 56, 4 starts | `int_mlb__player_game_days` |
| Start pool | 0 players, 0 days, null | 1 player, 1 day, 11 outs | `int_fantasy__replacement_levels` |
| Relief pool / batting pool | 10 players, 10 days, 39 outs / (batting not recorded) | 12, 13, 61 / 12 players, 14 days, 57 PA | same |
| `fct_player_category_value` rows / null | 4,046 / 16 | 4,437 / 0 | query |
| `fct_player_season_value` rows / null | 238 / 2 | 261 / 0 | query |
| Started player-days | (to record) | 647 | `int_fantasy__started_player_days` |
| CI `dbt build` | `PASS=479 WARN=4` of 483 | `PASS=480 WARN=3 ERROR=0` of 483 | `.agentic/gates` |
| CI warnings that stay | — | `rec_espn__register_matchups_exist` (28), `rec_espn__every_side_is_verified` (4), `int_fantasy__started_player_days_inputs_all_verified` (1) | build log |
| `rec_espn__player_day_differences` in CI | 308 | 467: a third roster day against one more boxscore (#81). No CI test reads it | query |
| `rec_fantasy__category_wins_added` in CI | 0 rows | 0 rows | query |
| `fixtures/landing` / `fixtures/landing_multi` on disk | 852 KB / 2.3 MB | 1.2 MB / 2.9 MB | `du -sh` |
| 2027 period-1 date in the multi tree | 2027-04-28 | 2027-04-23 | multi generator output |
| Tenant isolation | 0 differing pairs | 0 | gate |
| pytest | all pass | all pass, with the three of R6.2 updated and the new ones | gate |
| Real season | — | no model changes: nothing to rebuild; start pool stays 153 pitchers, 1,290 days, 19,251 outs | `int_fantasy__replacement_levels` in `warehouse.duckdb`, unchanged |
