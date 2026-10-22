# The optimal lineup is chosen a matchup period at a time, within the games-started limit — requirements

Issue: #164 · Tier: M · Status: proposed

## Problem

The optimal lineup is solved one team-day at a time (ADR 0037) and ignores the league's
games-started limit. Spec 0152 applies the limit to the actual lineup only (ADR 0079),
because a limit applied after a per-day solve can leave the "optimal" lineup below the
actual one (design.md, C7: 2022 matchup period 18, team 1). So today the optimal lineup
can use more starts than the limit allows, and the gap then counts value no manager in
this league would have taken.

The owner's rule (2026-10-18, on #152): the optimal starts are the highest-scoring starts
of the week that stay within the limit. And (2026-10-21): the league has a gentleman's
agreement not to go past the limit, even though ESPN credits every start on the day that
reaches it (ADR 0071). That needs a solver that sees the matchup period.

## Goals

- The optimal lineup of a team-period uses at most the limit's starts, and is the best
  such lineup. Where the actual lineup went past the limit, the optimum may go as far as
  it did, and no further.
- The optimal lineup is never worse than the actual lineup over a team-period.
- Both lineups are credited by the same rule (ADR 0071), each counting its own starts.
- Nothing moves where the limit does not bind. A league-season with no limit is solved
  exactly as today.

## No-gos

- Changing who is a candidate, the role minimum (ADR 0037's "at least as many players who
  played"), the tie-break, or how a day is valued (`int_fantasy__lineup_options`).
- Changing the actual lineup's crediting, or the limit rule itself (ADRs 0071, 0072).
- Rotisserie (season-total) limits. They are not modelled (ADR 0071), and no covered
  league-season has one.
- Moving the solver to BigQuery. The Python model stays DuckDB-only (ADR 0039).
- Modelling roster moves, game-time locks or anything a manager could have known. It is
  still hindsight opportunity.

## Rabbit holes

- A general MIP solver for the period problem. → Its tolerances cannot be shown to keep
  the 1e-9 tie-break (ADR 0091). The problem is small enough to solve exactly by
  enumeration (C4, C11).
- Solving only the periods where the per-day lineup goes over the limit. → Not exact once
  a start past the limit counts 0 (the over-limit periods, R1.3). Solving every limited
  period costs seconds (C11), so there is no pruning.
- Relaxing the role minimum inside a sub-problem. → The prototype's first version did this
  by accident and found 1,893 spurious "gains" (C13). The minimum is always the actual
  lineup's, per day.

## Requirements

### R1. The period problem

The optimal lineups of a team's matchup period are chosen together.

- R1.1 THE SYSTEM SHALL choose, for each team and matchup period, one lineup per team-day
  such that:
  - every team-day's lineup satisfies spec 0012's R3.1 constraints: no player twice, slot
    counts, and the per-role minimum of players who played;
  - the lineups' starts over the period do not exceed the period's *start cap* (R1.3).

  The choice maximizes the period's summed **credited** value (R1.2), plus 1e-9 for each
  player left in his actual slot and each slot left idle, on every day.
- R1.2 THE SYSTEM SHALL credit a lineup's day by ESPN's rule (ADR 0071), counting that
  lineup's own starts:
  - a day is *open* when the lineup's starts on the earlier days of the period are below
    `int_fantasy__start_limits.start_limit`, compared exactly;
  - on an open day every option counts its `option_value`;
  - on a day that is not open, an option that is a start in a pitcher slot counts 0, and
    every other option its `option_value`.

  Under a cap of `floor(start_limit)` no optimal start is ever on a day that is not open.
  The rule matters only for the actual lineup, and for the optimum in the periods of R1.3's
  second case.
- R1.3 THE SYSTEM SHALL set a team-period's start cap to `floor(start_limit)`. Where the
  actual lineup's starts in the period exceed that, the cap is the actual lineup's starts
  (the owner, 2026-10-21). That is 8 team-periods of eight seasons (C18).
- R1.4 WHEN a league-season has no limit (`start_limit` null) THE SYSTEM SHALL solve each
  team-day alone, as today, and return the same rows as today.
- R1.5 THE SYSTEM SHALL solve R1.1 exactly. The period's credited value of the chosen
  lineups is within 1e-9 times the period's slot-days of the greatest possible.
- R1.6 WHEN the per-day lineups of a team-period are within its cap and score exactly as
  well as the best plan THE SYSTEM SHALL return them. Among optimal plans of equal score,
  the one returned is fixed by a stated order (design.md) and does not depend on input
  order (spec 0012, R3.6).
- R1.7 A start is a pitcher-slot option whose `day_kind` is `start`, and counts 1. A
  player has at most one start a day (C3).
- R1.8 IF an option value of a team-period is greater than 1,000 in magnitude THEN THE
  SYSTEM SHALL fail the build, naming the team-day (spec 0012, R3.7).

### R2. Unvalued periods

- R2.1 IF any team-day of a team-period is unvalued (an option with a null value) THEN THE
  SYSTEM SHALL return no optimal rows for any team-day of that team-period. Every
  `fct_lineup_decisions` row of the period then has `is_unvalued` true, and what rests on
  the solver is null (spec 0012, R4.6). The period's starts cannot be counted without that
  day.

### R3. Crediting the optimal lineup

- R3.1 THE SYSTEM SHALL credit `fct_lineup_decisions.optimal_value` by R1.2, counting the
  optimal lineup's own starts (`fo_days_past_start_limit` with `lineup = 'optimal'`), as
  it does `actual_value` for the actual lineup.
- R3.2 THE SYSTEM SHALL credit the `optimal` rows of `int_fantasy__lineup_category_totals`
  by the same rule, with the optimal lineup's starts. A start not credited contributes no
  pitching component.
- R3.3 THE SYSTEM SHALL keep `actual_pitcher_starts` and `optimal_pitcher_starts` as the
  starts each lineup fielded, credited or not (spec 0012, R4.9).
- R3.4 THE SYSTEM SHALL fail the build if a team-period's `optimal_pitcher_starts` sum
  exceeds its start cap (R1.3).

### R4. What is judged, per team-period

- R4.1 THE SYSTEM SHALL fail the build if a team-period's summed `value_gap`, in date
  order, is below −1e-9. This replaces spec 0012's R4.7 per team-day. A team-day's gap may
  be negative where the period gains.
- R4.2 THE SYSTEM SHALL still fail the build, per team-day, if fewer players are assigned
  in a role than the actual lineup had starters who played (spec 0012, R4.7's second rule).
- R4.3 WHEN a team-period's summed gap is below 5e-10 THE SYSTEM SHALL report no player
  brought in, sat or moved on any of its days. This replaces R4.8 per team-day.
- R4.4 THE SYSTEM SHALL credit the solver's plan, inside the solver, by the same rule the
  mart applies (R1.2 and R3.1): the period, the exact comparison with `start_limit`, and
  what counts as a start. The real build's `optimal_value` sums for the changed
  team-periods must equal the values the solver was prototyped to give (*Expected
  values*). That is the cross-check between the Python rule and the SQL one.

### R5. Proof

- R5.1 THE SYSTEM SHALL test the period solver with pytest on hand-built cases:
  - the cap binds and the best starts are kept;
  - a slot a start would have taken goes to a reliever or another player;
  - a non-whole limit (29.857 caps at 29);
  - the actual lineup past the limit: the cap is its starts, and a start past the limit
    counts 0;
  - a worse start taken today so that a worse one tomorrow counts 0, in an over-limit
    period (design.md, C16);
  - a near tie: a plan better by less than 5e-10 is still chosen over the per-day plan
    (Review log, round 2 F1);
  - no limit gives today's per-day lineups;
  - ties keep the actual lineup;
  - input order does not change the result;
  - random small periods against a brute-force search of every plan.
- R5.2 THE SYSTEM SHALL show R3.4, R4.1 and R4.3 failing on planted rows (spec 0174)
  where CI cannot hold a failing case.
- R5.3 THE SYSTEM SHALL pass `.agentic/gates`, the tenant-isolation check included.

## Expected values

Real season (eight seasons, `data/warehouse_main_ac0e2ac.duckdb`'s inputs), from the exact
prototype (design.md, C9). The build's numbers must match.

| Check | Expected | How to verify |
|---|---|---|
| Team-periods whose `optimal_value` sum changes | 16 (C9's list, today → new) | `scripts/compare_warehouses.py`, then a query on `fct_lineup_decisions` |
| Team-days whose `optimal_value` changes | 19 (C9's list) | same |
| Team-days whose optimal lineup changes | 18: C9's 19 days but 2023-08-20 (team 7), whose lineup stays and whose start past the limit is credited 0 | `int_fantasy__optimal_lineups` before and after |
| Every other row of `fct_lineup_decisions`, and every row of `int_fantasy__optimal_lineups` outside those 18 team-days | unchanged | `scripts/compare_warehouses.py` |
| `fct_lineup_decision_categories` | `optimal` totals change only on the matchup sides of the 16 team-periods | same |
| Team-periods over their start cap | 0 | R3.4's test |
| Team-periods with a summed gap below −1e-9 | 0 | R4.1's test |
| Team-days with a negative gap | 0 | query |
| Unvalued team-days | 0 (C5) | query |
| `int_fantasy__optimal_lineups` build time | within a minute of today's | dbt timing |
