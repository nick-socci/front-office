# A league's games-started limit is applied to credited production — requirements

Issue: #152 · Tier: M · Status: draft

## Problem

ESPN league settings can cap how many games started a team is credited with in a matchup
(`rosterSettings.lineupSlotStatLimits`, stat 33). The models credit every start in a
pitcher slot, so a start that ESPN leaves out of a side's totals is counted by us.
Measured on all eight seasons (design.md, *Claims ledger*), the limit binds once: 2023,
matchup 110, team 7, where Max Fried's start of 2023-08-20 is credited by us and not by
ESPN. That one start leaves 9 of the 133 values that `fct_matchup_scores_match_espn`
fails on (#147). The rule is also a league setting that any league can set tighter, and
a league in which it binds often would have its matchup totals, player value and
transaction impact overstated with no test saying so.

The owner chose on 2026-10-16 to spec it at M, applied to credited production only, with
the lineup solver left as ADR 0037 has it.

## Goals

- A start ESPN does not credit is not credited by the models, in every model that sums
  credited production.
- The rule is read from each league-season's settings, never assumed: a league-season
  with no limit is unchanged, and one with a tighter limit gets the tighter rule.
- A limit the models do not know how to apply fails the build by name, instead of being
  ignored.
- #147's unexplained values fall from 133 to 124, and nothing that matches ESPN today
  stops matching.

## No-gos

Explicitly out of scope. Work that drifts here is escalated, not done.

- The lineup solver does not enforce the limit: each team-day is still solved alone
  (ADR 0037). How the optimal lineup's *totals* are credited is decided here (R4); how
  the lineup is *chosen* is not. (Amended 2026-10-18: the optimal lineup is not limited
  until a solver chooses a period's lineups within the limit, #164; ADR 0079.)
- No other row of #147 is investigated: 2018's 67 values, the other seasons' 57 and the
  2023 slope question stay on #147.
- No new landing and no new ESPN request: every settings capture is already landed.
- The lineup solver's inputs (`int_fantasy__candidate_day_values`) are not limited: a day
  value is what the player's day was worth, and whether it counts is the lineup's
  business.
- Rotisserie scoring is not modelled. A covered rotisserie league-season with a limit
  fails the check of R1.4; what such a limit means is not settled here.
- Slot 22 is not given a meaning. It is the key ESPN files the limit under, recorded as
  read.

## Rabbit holes

Places this could sink time, and the decision already taken to avoid them.

- Rounding a limit that is not a whole number (a 12-day period at 13 a week is 22.29
  starts) → the rule of ADR 0071 compares exactly, with no rounding, and the open
  question is recorded. No period in eight seasons tests it (C9).
- Enforcing the limit in the solver couples a week's days into one problem → out of
  scope (no-go 1); the owner kept ADR 0037.
- A start and a relief outing by one pitcher on one day (a doubleheader) → the day's
  pitching is one row already (`int_mlb__player_game_days`); a day with a start is a
  start day, and all of that day's pitching is uncredited when the start is. No such
  day is past a limit in eight seasons.

## Requirements

### R1. The limits are read from the settings

- R1.1 THE SYSTEM SHALL hold one row per league-season and limit entry of
  `settings.rosterSettings.lineupSlotStatLimits`, from the newest settings capture of
  that league-season, with the entry's key as `lineup_slot_id`, its `statId` as
  `stat_id` and its `limitValue` as `limit_value`, read as ESPN gives them.
- R1.2 WHEN a league-season's settings hold no limit entry THE SYSTEM SHALL hold no row
  for it.
- R1.3 THE SYSTEM SHALL give every matchup period of every covered league-season
  (ADR 0026) one row with the number of its days and its start limit: the games-started
  `limit_value` times those days for a head-to-head league-season, and null when the
  league-season sets no games-started limit (ADR 0071).
- R1.4 IF a covered league-season holds a limit entry whose `stat_id` is not 33, holds
  more than one entry whose `stat_id` is 33, or holds any limit entry while its scoring
  type is not head-to-head, THEN THE SYSTEM SHALL fail the build, naming the
  league-season and the entries.

### R2. A start past the limit is not credited

- R2.1 WHEN a team's credited starts on the earlier days of a matchup period already
  reach that period's start limit THE SYSTEM SHALL credit no pitching component of any
  started player-day of that team, on any later day of the period, on which the player
  started a game in a pitcher slot (ADR 0071).
- R2.2 THE SYSTEM SHALL credit every start of the day on which the limit is reached,
  however far past the limit that day takes the team.
- R2.3 THE SYSTEM SHALL keep crediting a relief appearance (a pitcher-slot day with no
  game started) on any day, past the limit or not.
- R2.4 THE SYSTEM SHALL count toward the limit only credited starts: games started in a
  pitcher slot, on days not past the limit.
- R2.5 THE SYSTEM SHALL keep every started player-day as a row, with
  `is_over_start_limit` saying whether its start was left uncredited, and every pitching
  column of such a row zero, `games_pitched` and `games_started` included, so that it is
  not a played started day either (ADR 0072). Its batting columns, `played` and
  `input_status` are unchanged.
- R2.6 WHILE a league-season sets no games-started limit THE SYSTEM SHALL credit exactly
  what it credits today.

### R3. The reconciliation still compares like with like

- R3.1 THE SYSTEM SHALL leave a started player-day whose start was left uncredited out of
  the player-day comparison with ESPN's game lines: ESPN's line for that day holds the
  start that ESPN's side total does not (ADR 0072).
- R3.2 THE SYSTEM SHALL compare each matchup side's credited totals, with the limit
  applied, against ESPN's `scoreByStat` as today, with no new status.

### R4. The actual lineup's totals and values are credited by the same rule

The lineup solver's inputs, the day values of `int_fantasy__candidate_day_values`, are
unchanged: the solver still chooses each team-day alone (ADR 0037).

- R4.1 THE SYSTEM SHALL credit the actual lineup's totals in
  `int_fantasy__lineup_category_totals` by the rule of R2, so that they still equal the
  scored totals exactly (`lineup_category_totals_reproduce_the_actual_totals`).
- R4.2 THE SYSTEM SHALL credit the optimal lineup's totals as the solver chose the lineup,
  without the limit (ADR 0079, superseding 0073: amended 2026-10-18, design.md
  *Amendments*). A limit applied after the per-day solve can leave the optimal lineup
  below the actual one; a limit-aware optimal lineup is #164.
- R4.3 THE SYSTEM SHALL count, in `fct_lineup_decisions.actual_value` and so `value_gap`,
  the day value of a start that the actual lineup's own starts put past the limit as 0;
  `optimal_value` is not limited (ADR 0079). `actual_pitcher_starts` and
  `optimal_pitcher_starts` stay the starts the lineups made, limited or not.
- R4.4 THE SYSTEM SHALL compare, in `candidate_day_values_add_back_to_season_value`, each
  pair's season value with the day values of its started days that are not
  `is_over_start_limit`.

## Expected values

How correctness is checked against real data, not just fixtures. Counted on
`data/warehouse_150.duckdb` (eight seasons, #150's build) on 2026-10-16; recounted at
build time.

| Check | Expected | How to verify |
|---|---|---|
| Limit rows (R1.1) | 9: one each for 2018, 2019 and 2022 to 2026 (slot 22, stat 33); two for 2020 (slot 21 stat 81; slot 22 stat 33); none for 2021 | count by season |
| Per-day values | 1.5714285714285714 in 2018 and 2019; 1.8571428571428572 in 2022 to 2026 | the rows |
| Start limit of a 7-day period | exactly 11 (2018, 2019), exactly 13 (2022 to 2026); null in 2021 | the period rows |
| R1.4 on the real data | passes: 2020 is rotisserie with two limits, and is not covered | the singular test |
| Started player-days past the limit | exactly 1: 2023-08-20, team 7, Max Fried, slot SP; its pitching components 0 | `is_over_start_limit` |
| Started player-day rows | unchanged in number | count before and after |
| `fct_player_season_value`, Fried, 2023, team 7 | `played_started_days` one fewer; `total_value` less that day's value; every other pair unchanged | compare with the saved table |
| `rec_espn__matchup_stat_differences` statuses | match 52,345 → 52,352; explained_by_game_lines 424 → 425; explained_by_component 269 → 270; unexplained 133 → 124; registered 31 and bye 366 unchanged | count by status |
| 2023, matchup 110, team 7 | stats 33, 34, 37, 39, 48, 41, 49 match; 45 explained_by_game_lines (our 41, ESPN 42, game-line difference −1); 47 explained_by_component | the side's rows |
| Every other side and stat | the same status and our_value as before | compare with the saved table |
| `fct_matchup_results_match_espn` | 79 failing rows, unchanged (that matchup's category results already agree) | the test |
| `rec_espn__player_day_differences_are_registered` | 18 → 17: 2023 m110 t7's ER key leaves, being `explained_by_game_lines` (ADR 0064; amended 2026-10-18) | the test |
| Optimal lineups (R4.2) | no optimal row changes (amended 2026-10-18). The optimal lineups go over the limit in 22 team-periods; on 4 of them (2018 1, 2019 3, 2022 1, 2023 1) the day-based rule would leave 6 of their starts uncredited, which is what the gap overstates (ADR 0079) | the lineup totals before and after |
| `fct_lineup_decisions` values (R4.3) | `actual_value` and `value_gap` change on 1 team-day (2023-08-20, team 7); `optimal_value` on none (amended 2026-10-18); `fct_lineup_decisions_are_never_worse_than_the_actual_lineup` passes | compare with the saved table |
| `candidate_day_values_add_back_to_season_value` (R4.4) | passes | the test |
| Settings captures | 21, and within each season every capture holds the same limits | read every capture |
| `lineup_category_totals_reproduce_the_actual_totals` | passes | the test |
