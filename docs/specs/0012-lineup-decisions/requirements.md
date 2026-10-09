# Lineup decisions: what was left on the bench — requirements

Issue: #12 · Tier: M · Status: draft

## Problem

The marts say what a team's started players produced and what each was worth. Nothing
says what the team could have had from the players it held and did not start, which is
the question a manager asks every morning and the last blocker of #13.

The issue as filed (2026-09) asks for the optimal daily lineup by an assignment solver,
and for actual against optimal totals per team-day and per matchup. Three things have
changed or been measured since, all read-only on the real 2026 season on 2026-10-09:

- **The scalar** is the matchup-margin scale, not z-scores (owner, 2026-10-04, #55;
  ADR 0010, blended by ADR 0027). A day's value on that scale adds up: summed over the
  2,160 team-days it gives 2,245.53, which is the sum of
  `fct_player_season_value.total_value` to the last digit shown.
- **An unrestricted hindsight optimum is mostly noise.** Allowed to leave any slot
  empty, the best lineup sits 10,152 of the 21,120 started player-days that had a game,
  because nearly half of single days are below replacement. Its gap is 3,762 margins
  against 2,246 of actual value, and almost all of it is "your starters had bad days".
  That is not a lineup decision.
- **Eligibility in the 2026 backfill is as of the fetch**, not of the day (#52). A
  "could have started" reading allows moves that were not legal on the day.

Also measured: 55,653 roster days over 2,160 team-days; 18 starting slots; 21 to 23
candidates a team-day once injured-list slots are left out; 3,373 bench days with a
batting appearance and 251 with a pitching one. The league's settings carry a limit on
games started by pitchers (`lineupSlotStatLimits`, stat 33, 1.857 a day, 13 a week) that
the issue does not mention.

## Goals

- For every team and day, the best lineup the team could have set from the players it
  held, under a rule that counts lineup choices and not bad luck, with its value on the
  scale the player facts use.
- The same comparison in the league's own currency: for each matchup and category, the
  team's total with those lineups, against the opponent's actual total.
- Exact, repeatable and tested: an assignment solver, never a greedy pass.
- Labelled as hindsight opportunity, not manager skill.

## No-gos

- **No change to any existing model's rows or columns**, other than one added column on
  the `espn_lineup_slots` seed (R1.1).
- **Not a model of winning the matchup.** The lineup maximises summed day value; it
  does not know which categories were in play that week (ADR 0010's accepted cost; #57
  measured the scale and left the linear form standing).
- **No foresight model.** Nothing here estimates what a manager could have known in
  the morning. Game-time locks are ignored.
- **No add or drop.** Only players on the roster that day are considered.
- **Injured-list slots are not candidates** (ADR 0037).
- **The games-started limit is not enforced** (ADR 0037). Each team-day carries the
  pitcher starts of both lineups (R4.9), so a period over a league's limit can be seen;
  the limit itself is not read or interpreted.
- **No reconstruction of a day's true eligibility** for backfilled seasons (ADR 0038).
- **No BigQuery port of the Python model.** Its header says what porting would take;
  the choice belongs to sub-project 3.
- **No pandas or pyarrow.** The Python model returns a DuckDB relation.
- **The current warehouse is not replaced or deleted by an agent.**

## Rabbit holes

- *Solving the week instead of the day* (the starts limit couples days) → out; the
  limit is not modelled; the optimal lineups exceed it in 2 of 264 seven-day
  team-periods (expected values).
- *An optimizer for category wins* → out; it needs a model of the opponent and of the
  week, and the scalar was the owner's decision.
- *Deciding which of several equally good lineups is "the" optimum* → one rule: keep
  the actual occupant where that costs nothing (R3.4).
- *Floating-point totals that differ between builds* → the Python model returns only
  who goes where; every sum is made in SQL, in a fixed order, as #28 required.
- *A unit test of the Python model in dbt* → dbt cannot unit-test a Python model. The
  solver is a plain function tested with pytest; the model that calls it is covered by
  singular tests on its output.

## Requirements

### R1. Candidates and their day's value

Who could have been started, and what each did that day in the facts' own unit.

- R1.1 THE SYSTEM SHALL treat as a candidate every roster day whose slot is a starting
  slot or a bench slot that is not an injured-list slot. The `espn_lineup_slots` seed
  gains `is_injured_list_slot` to say which, from its generator.
- R1.2 THE SYSTEM SHALL hold, in `int_fantasy__candidate_day_values`, one row per
  candidate and side (`batting`, `pitching`) on which he has an MLB appearance that
  date, with the kind of day (`batting`; `start` or `relief` by
  `fo_pitching_day_kind`) and its `day_value`.
- R1.3 THE SYSTEM SHALL compute `day_value` as the sum, over the league-season's scored
  categories on that side and in category order, of the scaled value over replacement
  of that one day's line, by the `fo_value_over_replacement` and `fo_scaled_value`
  macros with one played day, the day's kind's replacement level, and the scales of
  `int_fantasy__category_scales`.
- R1.4 IF any of those categories' scaled values is unknown (a null replacement level)
  THEN THE SYSTEM SHALL leave `day_value` null.
- R1.5 THE SYSTEM SHALL fail the build if, for any (player, team) pair, the sum of the
  day values of his started days on his slot's side differs from
  `fct_player_season_value.total_value` by more than 1e-9, or is null where the other
  is not.

### R2. Lineup options

Every legal (player, slot) pair of a team-day, which is all the solver reads.

- R2.1 THE SYSTEM SHALL hold, in `int_fantasy__lineup_options`, one row per candidate
  and starting slot such that the league uses the slot (`slot_count > 0`), ESPN lists
  the player as eligible for it in that period's roster of that team, and the slot's
  role credits a side he played that day; with `option_value`, the day value of that
  side, and `day_kind`, the kind of that side's day (R1.2).
- R2.2 THE SYSTEM SHALL mark `is_actual` on the option whose slot the player sat in.
- R2.3 THE SYSTEM SHALL carry `eligibility_fetched_at`, the fetch time of the roster
  the eligibility was read from.
- R2.4 THE SYSTEM SHALL fail the build if a started player who played on his slot's
  side has no `is_actual` option, or more than one.

### R3. The optimal lineup

- R3.1 THE SYSTEM SHALL choose, for each team-day, the set of options that maximises
  the summed `option_value` plus 1e-9 for each player left in his actual slot and
  for each slot left idle, such that no player has two slots, no slot holds more players
  than the league's count for it, and, for each of the hitter and pitcher roles, at
  least as many players are assigned as the actual lineup had starters who played on
  that role's side.
- R3.2 THE SYSTEM SHALL solve R3.1 exactly, as an assignment problem. The 1e-9 terms are
  the tie-break of R3.4 made part of the objective; a slot earns at most one of them,
  so the chosen lineup's summed
  `option_value` is within 1e-9 times the number of starting slots (1.8e-8 for 18) of
  the greatest possible.
- R3.3 THE SYSTEM SHALL hold the result in `int_fantasy__optimal_lineups`, one row per
  team-day and assigned player, with his slot.
- R3.4 WHEN the actual lineup attains the greatest summed `option_value` THE SYSTEM
  SHALL return the actual lineup; among lineups of equal value it returns one that
  changes the fewest slots, a slot being changed when its actual occupant is not in
  it or when it was idle and is filled. The two kinds count the same, and which of
  several such lineups is returned is fixed only by R3.6. Any lineup that differs
  from the actual one gives up at least one 1e-9 term, so it is chosen only for a
  gain of at least 1e-9.
- R3.5 IF a team-day has an option whose value is null THEN it is *unvalued* and THE
  SYSTEM SHALL return no rows for it. A team-day with no options at all is not
  unvalued: its optimal lineup is the empty one, with value 0. The two are told apart
  from the options, never from the absence of rows.
- R3.6 THE SYSTEM SHALL return the same rows whatever the order of its input, and read
  only the rows of the team-day it is solving.
- R3.7 IF an option value of a team-day is greater than 1,000 in magnitude THEN THE
  SYSTEM SHALL fail the build, naming the team-day. The 1e-9 terms of R3.1 are lost
  in a floating-point sum of far larger values; 1,000 is well inside where they hold
  (about 25,000 for 18 slots) and far above a day value (of order 0.01 to 5).

### R4. `fct_lineup_decisions`

- R4.1 THE SYSTEM SHALL hold one row per team and scoring date on which the team has a
  roster, with the actual lineup's value, the optimal lineup's value and their gap.
- R4.2 THE SYSTEM SHALL count, per row, the players brought in (assigned, not started),
  sat (started and played on their slot's side, not assigned) and moved (started and
  assigned to a different slot).
- R4.3 THE SYSTEM SHALL name the largest missed start: the brought-in player with the
  greatest `option_value`, lowest platform player id on a tie, by
  `platform_player_id` and `mlbam_player_id` (the convention of ADR 0034), with his
  slot and value; null when nobody was brought in.
- R4.4 THE SYSTEM SHALL carry `matchup_period` on every row and `matchup_id` where the
  team has a matchup in that period, null where it does not.
- R4.5 THE SYSTEM SHALL set `has_unverified_inputs` when any candidate of the team-day
  rests on a missing boxscore or an unresolved player.
- R4.6 THE SYSTEM SHALL carry `is_unvalued` (R3.5) on every row. IF it is true THEN
  THE SYSTEM SHALL leave null what rests on the solver: `optimal_value`, `value_gap`,
  `optimal_starters`, the three counts of R4.2, `optimal_pitcher_starts` and the
  missed start. `candidates`, `played_starters` and `actual_pitcher_starts` do not
  rest on it and are never null. `actual_value` is null when any actual option of the
  team-day has a null value, since a sum would skip it and report a part as the
  whole, and is never null otherwise. On a row that is not unvalued none of the
  values or counts is null.
- R4.7 THE SYSTEM SHALL never report a gap below zero (to within 1e-9 for the order of
  a floating-point sum), nor fewer assigned players than
  played starters in either role; a singular test fails on either.
- R4.8 WHEN the gap is below 5e-10 THE SYSTEM SHALL report no player brought in, sat
  or moved; a singular test fails otherwise. By R3.4 a lineup that differs from the
  actual one gains at least 1e-9; the threshold is half of that, to leave room for
  the order of a floating-point sum. It is not R3.2's bound: a changed lineup with a
  gap between 1e-9 and 1.8e-8 is a correct result.
- R4.9 THE SYSTEM SHALL carry `actual_pitcher_starts` and `optimal_pitcher_starts`: the
  number of players in a pitcher-role slot of the actual lineup, and of the optimal
  one, whose day is a `start` (R1.2). The first is never null; the second is null on
  an unvalued row (R4.6).

### R5. `fct_lineup_decision_categories`

- R5.1 THE SYSTEM SHALL hold one row per matchup side and scored category, with the
  team's actual total, its total had it set the optimal lineup on every day of the
  matchup period, the opponent's actual total, and the result of each against the
  opponent's (`WIN`, `LOSS`, `TIE`, as `fct_matchup_category_scores` words them).
- R5.2 THE SYSTEM SHALL hold, in `int_fantasy__lineup_category_totals`, one row per
  matchup side, scored category and lineup (`actual`, `optimal`), with the numerator,
  denominator and value of the category under that lineup, both lineups computed by
  the same statements from credited components by the rules of
  `int_fantasy__stat_components`, a player credited by the role of the slot the lineup
  puts him in. The mart's optimal total is that model's `optimal` row.
- R5.3 THE SYSTEM SHALL fail the build if the value of an `actual` row of
  `int_fantasy__lineup_category_totals` differs from
  `fct_matchup_category_scores.team_value`, or if a side and category of that fact
  has no `actual` row.
- R5.4 IF any team-day of the side's matchup period is unvalued (R4.6) THEN THE SYSTEM
  SHALL leave the `optimal` row's numerator, denominator and value null, and with them
  the mart's optimal total and its result. A day on which nobody was
  assigned contributes zero.
- R5.5 THE SYSTEM SHALL set `has_unverified_inputs` when
  `fct_matchup_category_scores` has it set for the row, or any team-day of the side's
  matchup period has it set in `fct_lineup_decisions`; the descriptions say that a
  result on such a row rests on incomplete production.

### R6. Proof and safety

- R6.1 THE SYSTEM SHALL test the solver with pytest on hand-built cases: a player
  eligible at two slots that a greedy pass double-assigns; a slot with a count above
  one; a starter with a bad day and no replacement, who stays; the same starter with a
  bench player who played, who replaces him; a starter with no game displaced by a
  bench player with one; a two-way player; a tie, which keeps the actual lineup; a bench player worth 0, and one worth less than
  1e-9, beside a slot the actual lineup left idle, neither of whom is brought in; values at the bound of R3.7, which never make an ineligible pair preferable and
  whose tie still keeps the actual lineup, with the actual players in reverse order
  of id; a value above the bound, which raises; two lineups of equal value that each
  change two slots, either of which is accepted and the same one returned for
  shuffled input; a
  team-day with no options; input rows in shuffled order; and, on random small cases,
  a summed value within R3.2's bound of the maximum found by trying every legal
  lineup.
- R6.2 THE SYSTEM SHALL fail the build if an optimal lineup holds a player twice, fills
  a slot beyond its count, or holds a (player, slot) pair that is not an option.
- R6.3 THE SYSTEM SHALL pass `.agentic/gates`, the tenant-isolation check included,
  with no warning CI does not have today.
- R6.4 THE SYSTEM SHALL say, in the header of every new model and in the marts'
  descriptions, that the figures are hindsight opportunity under the rule of R3.1, and
  what the eligibility they rest on is.

## Expected values

Real 2026 season. Measured on 2026-10-09 with a throwaway prototype of R1 to R5
(SciPy's solver, read-only on the warehouse; not committed). The build reproduces each.

| Check | Expected | How to verify |
|---|---|---|
| `fct_lineup_decisions` rows | 2,160 (12 teams × 180 dates) | count |
| `candidates` per row | 21 to 23 (91 rows at 21, 130 at 22, 1,939 at 23) | min, max, group by on `fct_lineup_decisions` |
| Sum of `actual_value` | 2,245.53, equal to the sum of `fct_player_season_value.total_value` | R1.5's test; query |
| Sum of `optimal_value` / of `value_gap` | 3,713.74 / 1,468.21 | query |
| Team-days with a gap above 1e-6 / at most 1.8e-8 / below zero | 1,540 / 620 / 0 | query |
| Gap per team-day | median 0.478, 90th percentile 1.699, greatest 4.444 | query |
| Season gap per team | from 59.4 to 202.6 | group by team |
| Players brought in / sat / moved, season | 2,533 / 2,427 / 585 | sums |
| Team-days starting more played players than the actual lineup | 101 | query |
| Greatest single missed start | 2.462, an `OF` slot, 2026-07-11 | max |
| Team-days with a gap at most 1.8e-8 and any change of lineup | 0 of 620 | query; R4.8's test covers those below 5e-10 |
| Rows with `has_unverified_inputs` | 0 | count |
| Rows with `is_unvalued` | 0 | count |
| `fct_lineup_decision_categories` rows | 4,862 (286 sides × 17) | count |
| `int_fantasy__lineup_category_totals` rows | 9,724 (4,862 × 2 lineups) | count |
| `actual` rows equal to `fct_matchup_category_scores.team_value` | 4,862 of 4,862 | R5.3's test |
| Results, actual → with the optimal lineups | LOSS→LOSS 1,764 · LOSS→TIE 83 · LOSS→WIN 453 · TIE→LOSS 5 · TIE→TIE 141 · TIE→WIN 116 · WIN→LOSS 6 · WIN→TIE 2 · WIN→WIN 2,292 | group by |
| Sides that gain / lose category wins; net wins gained | 216 / 1 of 286; 561 | query |
| Sum of `optimal_pitcher_starts` / of `actual_pitcher_starts` | 2,639 / 2,524 | sums |
| Team-periods of seven days whose optimal lineups hold more than 13 pitcher starts | 2 of 264 (the actual lineups: 1); none above 14 | the two columns summed by team and matchup period |

Sensitivity, measured with the same prototype and not built: with injured-list slots
as candidates the season gap is 1,553.98; with eligibility cut back to slots a player
had already occupied, 1,357.58; without the rule against sitting a played starter,
3,762.12; with a count's value measured from zero instead of from replacement,
1,545.78.

CI (fixtures: 3 dates, 12 teams; measured with the same prototype on the warehouse the
gates built on 2026-10-09, applying the macros' rule that a null or zero scale is
worth 0, which holds for 6 of the fixtures' 17 scales):

| Check | Expected | How to verify |
|---|---|---|
| `fct_lineup_decisions` rows | 36 | count |
| Candidate days / with an MLB appearance | 824 / 32 | count |
| Rows with `has_unverified_inputs` | 36 (every fixture date lacks boxscores) | count |
| `fct_lineup_decision_categories` rows | 68 (4 sides × 17) | count |
| Sum of `actual_value` / `optimal_value` / `value_gap` | 17.3729 / 26.8169 / 9.4440 | the last task |
| Team-days with a gap | 4 of 36 | the last task |
| Players brought in / sat / moved | 4 / 2 / 0 | the last task |
| Rows with `is_unvalued` | 0 | the last task |
| `int_fantasy__lineup_category_totals` rows | 136 (68 × 2 lineups) | count |
| Sum of `actual_pitcher_starts` | 2 (measured on the fixture warehouse, 2026-10-09) | the last task |
| Sum of `optimal_pitcher_starts` | at most 2: no benched pitcher started a game on a fixture date. The exact figure was not measured and is recorded in the last task | the last task |
| CI `dbt build`, isolation | no error, today's three warnings, 0 differing pairs | `.agentic/gates` |
