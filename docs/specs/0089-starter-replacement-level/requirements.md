# The replacement level for a start, and a standing check of values against re-scored matchups — requirements

Issue: #89 · Tier: M · Status: proposed 2026-10-09

## Problem

The owner asked on 2026-10-08 why starting pitchers take half of the top 20 by
`total_value` when published rankings do not, and whether the model overvalues them.
#89 supposed the cause was that value is counted per played day and a starter's slot
sits idle four days in five. Measured on 2026, read-only:

**It is not idle slot-days.** Pitcher slots are filled (8,619 of 8,640 SP slot-days) and
their occupants pitch on 24% to 33% of them, against 77% to 85% for hitters; but whoever
replaced a starter in that slot would also pitch every fifth day. Teams used 8.4 starts
a week against a cap of 13 (reached in 2% of team-weeks), and benched 278 of 2,802
rostered starts.

**It is not the model's arithmetic.** Every 2026 matchup was re-scored with one player's
started production swapped for replacement production, and the category results that
changed were counted. A unit of `total_value` bought 0.405 real category wins for
starters, 0.385 for hitters and 0.388 for relievers; theory gives 0.40.

**It is the level a start is measured against.** The start pool is the 12 unrostered
pitchers with the most free-agent starts over the season (ADR 0009): pitchers nobody
wanted all year. Free-agent starts by pitchers who were starters at the time are a
larger and better group:

| Starts | Starts | Pitchers | Outs | ERA | WHIP | K/9 |
|---|---|---|---|---|---|---|
| Started in a fantasy lineup | 2,524 | 178 | 16.39 | 3.89 | 1.226 | 8.84 |
| **Free agent that day, a starter up to then** | 1,290 | 153 | 14.92 | 4.90 | 1.403 | 7.40 |
| — with 3+ / 5+ / 10+ earlier starts | 1,091 / 907 / 554 | | 14.97 / 15.02 / 15.02 | 4.93 / 4.90 / 4.87 | 1.398 / 1.389 / 1.371 | |
| — before / from 2026-06-25 | 623 / 667 | | 15.13 / 14.73 | 4.91 / 4.90 | 1.412 / 1.394 | |
| **Today's start pool** | 306 | 12 | 14.98 | 5.41 | 1.483 | 7.51 |
| Free agent that day, a reliever up to then (openers) | 465 | 154 | 9.39 | 4.69 | 1.390 | |

Today's pool has the right length of outing and is half a run too lenient. Under it,
the re-scoring shows pitching categories giving 53% of all category wins above
replacement while being 8 of the 17 categories (47%), with ERA and WHIP the two largest
sources of all.

**Ranking free-agent starters does not help.** By season-to-date performance, there are
about 11 free-agent starters a day, so any cut near the number of teams is all of them,
openers included (13.4 outs). By usage, the existing principle, the most-used free-agent
starters each week are the worst: ERA 5.88 for the top 6, 5.17 for the top 12, 4.97 for
the top 24. Their quality does not depend on how established they were (ERA 4.80 to
4.92 from 0 to 15+ earlier starts); only the length of the outing does.

**For hitters and relievers no such gap was found.** Six other definitions of the pool
put the relief ERA between 3.30 and 4.24 against today's 3.48, and batting total bases a
game between 1.14 and 1.53 against today's 1.36.

## Goals

- A start is measured against what a manager could have had: a free-agent start by a
  pitcher who was a starter at the time.
- The 2026 values move by what this document says and no more.
- That values track real category wins, equally for each group of players, is checked
  on every build and no longer a one-off measurement.

## No-gos

- **No change to the batting pool or the relief pool** (ADRs 0001 and 0009), to N, or to
  what a played day or a kind of day is (ADR 0008).
- **No ranking of the start pool, by performance or by usage, and no pool size for it.**
- **No use of managers' transactions** to say who is replacement level.
- **No change to value per played day** (ADR 0002), to the category scales (ADRs 0010,
  0027), or to the SQL of the three value facts.
- **No hitter pools by position.**
- **No new mart.** The re-scored wins are a reconciliation model, not a published fact.
- **No new ingestion.**

## Rabbit holes

- *The best free agents available each day, ranked on their season to date* → built and
  measured: the top 20 does not change, and the relief pool it gives has outings of 3.7
  outs against a rostered reliever's 3.0, the fault ADR 0009 exists to prevent.
- *Players the league both added and dropped* → rejected by the owner: replacement should
  not rest on managers' moves.
- *The marginal tier beyond the league's demand* → ranked with hindsight, and lifted by
  stars who missed half a season.
- *Making the batting and relief pools point-in-time too* → no measured gap to correct.
- *Why relievers' value converts to real wins less steadily* (R3.5) → recorded, not
  chased.
- *Matching published rankings* → they are forecasts for leagues of another shape. Nine
  of the top 20 remain starters here.

## Requirements

### R1. The start pool

- R1.1 THE SYSTEM SHALL take as the start pool of a league-season every MLB player-day
  that is a start (`fo_pitching_day_kind`), on one of the league-season's scoring dates,
  by a player on none of its rosters that date, whose `fo_replacement_group` over all
  his MLB player-days of that season strictly before that date is `SP`.
- R1.2 THE SYSTEM SHALL NOT rank or cap the start pool.
- R1.3 THE SYSTEM SHALL compute the start level as today: each component summed over the
  pool's days and divided by their number.
- R1.4 THE SYSTEM SHALL report `pool_players` for the start kind as the number of
  distinct pitchers with a day in the pool, and `pool_played_days` as its days.
- R1.5 THE SYSTEM SHALL leave the batting and relief rows of
  `int_fantasy__replacement_levels` unchanged, and its grain and columns.
- R1.6 IF a league-season has no day in the start pool THEN THE SYSTEM SHALL keep the
  start rows with a null level, as an empty pool has today.
- R1.7 THE SYSTEM SHALL NOT use a player-day of another season, a roster of another
  league, or any day on or after the date in deciding whether a pitcher was a starter.

### R2. The value facts

- R2.1 THE SYSTEM SHALL NOT change the SQL of `fct_player_category_value`,
  `fct_player_season_value` or `fct_transaction_impact` beyond header comments.

### R3. Values against re-scored matchups

- R3.1 THE SYSTEM SHALL provide `rec_fantasy__category_wins_added` with one row per
  (`platform`, `league_id`, `season`, `platform_player_id`, `fantasy_team_id`) that has a
  started day inside a re-scorable matchup of a league-season with rosters. A matchup is
  re-scorable when `fct_matchup_results` gives it a winner and
  `has_unverified_inputs` is false: a result resting on a missing boxscore or an
  unresolved player is not a real result to re-score.
- R3.2 THE SYSTEM SHALL, for each such pair and matchup, recompute the pair's side with
  the pair's started production removed and replacement production put in its place
  (the level of each kind of day times the pair's played days of that kind), recompute
  every scored category by the rules of `int_fantasy__stat_components`, and compare with
  the opponent's actual value as `fct_matchup_category_scores` does.
- R3.3 THE SYSTEM SHALL draw replacement production as whole numbers: each component's
  expected amount is rounded down, and up with probability equal to its fraction, by a
  draw that is a fixed function of the pair, the matchup, the component and the draw's
  number. It SHALL average over 20 draws. A fraction of a win or a steal would otherwise
  break every tie in its category.
- R3.4 THE SYSTEM SHALL carry `matchups_rescored`, `category_wins_added` (a win 1, a tie
  one half) and `matchup_wins_added` (the same, for the matchup by most categories).
- R3.5 THE SYSTEM SHALL fail the build when, for a league-season and a judged
  replacement group, the slope through the origin of `category_wins_added` on
  `total_value` is outside 0.34 to 0.47. A group is judged when it has at least 100
  pairs and the correlation of the two measures over them is at least 0.75. A
  league-season with fewer than 100 re-scorable matchups is not judged. Chosen by the
  owner on 2026-10-09 over one looser band for every group.
- R3.9 THE SYSTEM SHALL report every group's pairs, slope and correlation, judged or not,
  in a model or a test's output that the run evidence can quote, so that a group left
  unjudged is seen and not forgotten.
- R3.6 THE SYSTEM SHALL give the same result on every build of the same data.
- R3.7 IF the level of a kind of day the pair played in a re-scorable matchup is null
  (an empty pool) THEN THE SYSTEM SHALL give the pair null `category_wins_added` and
  `matchup_wins_added`, as the value facts give it a null value, and SHALL still carry
  its row and `matchups_rescored`.
- R3.8 IF a group of at least 100 pairs holds a pair with a null `total_value` or a null
  `category_wins_added` THEN THE SYSTEM SHALL fail the build for that group as not
  checkable, and SHALL NOT compute a slope from the rest.

### R4. Tests

- R4.1 THE SYSTEM SHALL have dbt unit tests for R1: a free-agent start by a pitcher with
  earlier starts is in the pool; his first start of the season is not; a rostered
  pitcher's start is not; an opener (a reliever up to then) is not; a start counts by
  what the pitcher had done before that date and not after; more pitchers than teams
  are all in; a pitcher rostered in another league is a free agent here; another
  season's starts do not make a starter.
- R4.2 THE SYSTEM SHALL keep the existing unit tests of the batting and relief pools
  with their expectations unchanged, and revise those that assert the start pool's
  ranking or size.
- R4.3 THE SYSTEM SHALL restrict `int_fantasy__replacement_pool_is_at_most_n` to the
  batting and relief kinds.
- R4.4 THE SYSTEM SHALL keep
  `fct_player_category_value_the_replacement_pool_is_worth_zero` unchanged and passing.
- R4.5 THE SYSTEM SHALL have dbt unit tests for R3: a player whose production is exactly
  replacement adds nothing; a win that becomes a loss without him adds 1 and a tie that
  becomes a loss adds one half; a lower-is-better category is judged the right way; a
  matchup won 9 to 8 with him and lost 8 to 9 without adds one matchup win; an
  undecided matchup and a bye are not re-scored; a matchup with a winner and unverified
  inputs is not re-scored; a pair with a start in a league-season whose start level is
  null has null wins added and keeps its row.

### R5. The real season

- R5.1 THE SYSTEM SHALL build and test clean on the real warehouse, with the warning it
  has today and no new one.
- R5.2 THE SYSTEM SHALL leave every existing model's rows unchanged except the start
  rows of `int_fantasy__replacement_levels` and `value_over_replacement`, `scaled_value`,
  `total_value` and the columns derived from them in the three value facts.
- R5.3 IF a level, a count or a ranking figure differs from *Expected values* beyond the
  rounding shown, or a re-scored share or slope by more than the tolerance stated, OR a
  model outside R5.2 changes, THEN the build SHALL stop and take it to the owner, having
  first finished every other check. A CI test failing on the fixture's null
  starts is such a stop. It SHALL NOT change a test, a tolerance or an expected value to
  get past one. Agreed by the owner on 2026-10-09.

## Expected values

The owner accepted the 2026 movements below on 2026-10-09.

Measured on 2026-10-09, read-only, on the real warehouse after #90. The values were
recomputed from `int_fantasy__started_player_days` by the facts' own arithmetic, which
reproduces `fct_player_season_value` with today's level to 7e-15.

**The start level** (`int_fantasy__replacement_levels`, `day_kind = 'start'`):

| | Today | After |
|---|---|---|
| `pool_players` / `pool_played_days` | 12 / 306 | 153 / 1,290 |
| `outs_recorded` | 14.9804 | 14.9233 |
| `earned_runs` | 3.0000 | 2.7101 |
| `hits_allowed` | 5.5523 | 5.0566 |
| `pitcher_walks` | 1.8529 | 1.9225 |
| `pitcher_strikeouts` | 4.1667 | 4.0915 |
| `wins` / `losses` | 0.2320 / 0.3954 | 0.2519 / 0.3682 |
| ERA / WHIP / K/9 | 5.41 / 1.483 / 7.51 | 4.90 / 1.403 / 7.40 |

Batting and relief rows: unchanged (pools of 12; 1,690 and 833 days).

**The 2026 values**, `fct_player_season_value`, 580 pairs:

| Check | Expected |
|---|---|
| Rank correlation of `total_value`, before against after | 0.9957 |
| Top 20 by group | 11 SP, 9 hitters, 0 RP → 9 SP, 11 hitters, 0 RP |
| Into / out of the top 20 | Arozarena (21 → 17), Rice (24 → 19) / Skubal (19 → 23), Wheeler (20 → 24) |
| Top 50 by group | 20 / 27 / 3 → 18 / 29 / 3 |
| First six | Crow-Armstrong 35.99, Misiorowski 33.76, Ohtani 32.82, Schlittler 31.29, Alvarez 30.79, Luzardo 26.31 |
| Largest change in `total_value` / median | 2.29 / 0.00 |
| Largest move in rank, top 50 / overall | 9 / 169 |
| Median `total_value` by group | hitter 1.32 → 1.32 · SP 1.58 → 1.14 · RP 0.92 → 0.92 |
| Sum of `total_value` by group | hitter 1,150.1 → 1,149.1 · SP 960.0 → 804.8 · RP 305.4 → 294.6; all 2,415.51 → 2,248.55 |
| Best reliever | 29th → 27th |
| Rows of each value fact | unchanged: 9,860 · 580 · 737 |

A hitter's value changes only if he also made a started start (Ohtani).

**The re-scoring** (`rec_fantasy__category_wins_added`, 2026). The prototype drew with a
different function from the one the model will use, so these are expected within the
tolerance shown, not to the digit.

| Check | Today's level | After | Tolerance |
|---|---|---|---|
| Category wins added: SP / hitters / RP | 389 / 443 / 119 | 326 / 443 / 114 | ±10 each |
| Shares | 41% / 47% / 12% | 37% / 50% / 13% | ±2 points |
| Pitching categories' share of category wins added | 53% | 50% | ±2 points |
| ERA / WHIP, category wins added | 101 / 106 | 70 / 76 | ±8 each |
| Matchup wins added: SP / hitters / RP | 44 / 48 / 15 | 33 / 48 / 14 | ±4 each |
| Slope of category wins on `total_value`: SP / hitters / RP | | 0.43 / 0.40 / 0.33 | ±0.03 |
| Judged under R3.5 | | SP and hitters, both inside 0.34 to 0.47; RP not judged (correlation 0.69) | |
| Correlation with `total_value`: SP / hitters / RP | 0.86 / 0.81 / 0.69 | 0.85 / 0.81 / 0.69 | ±0.03 |

| Check | Expected |
|---|---|
| Real build | passes, 1 warning as today |
| CI | passes. Expected warnings: 4, the three it has and `int_fantasy__replacement_pool_has_played_days` for the start kind: two fixture days cannot hold a pitcher's earlier start, so the fixture start pool is empty and fixture starts have a null value. Anything else new is R5.3. The R3.5 test judges no fixture league-season |
| Tenant isolation | 0 differing pairs over 5 league-seasons |
