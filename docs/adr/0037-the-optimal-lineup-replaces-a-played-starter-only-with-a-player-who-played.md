# 0037. The optimal lineup replaces a played starter only with a player who played

- Status: accepted
- Date: 2026-10-09
- Spec: [0012-lineup-decisions](../specs/0012-lineup-decisions/design.md) · Issue: #12

## Context

#12 compares each team-day's actual lineup with the best one available in hindsight.
The owner set the scalar on 2026-10-04: value in matchup margins (ADR 0010, blended by
ADR 0027), summed over the scored categories. "Best" still needs a definition, and the
issue's review asked that empty slots be handled and the result be called hindsight
opportunity, not manager skill.

Measured on 2026 with a prototype:

- A day's value on that scale is negative for 10,097 of the 21,120 started player-days
  that had a game. Free to leave slots empty, the best lineup sits 10,152 played
  starters and leaves 6,609 slots empty; its gap is 3,762 margins against 2,246 of
  actual value.
- Required to field at least as many players who played, per role, as the actual
  lineup did, the gap is 1,468 on 1,540 of 2,160 team-days, never negative, and 620
  team-days are unchanged.
- Under that requirement, measuring a count from zero instead of from replacement
  moves the gap to 1,546.
- 240 injured-list-slot days had an MLB appearance; as candidates they add 86.
- The league limits pitcher starts (`lineupSlotStatLimits`, stat 33, 13 a week). The
  actual lineups reach 14 once in a seven-day period; the optimal ones exceed 13 in 2
  of 264 seven-day team-periods.

What the number means is the owner's decision.

## Decision drivers

- The gap should count choices a manager makes: who to start among those available.
- Never worse than the actual lineup, as the issue requires.
- One scalar with the player facts, so a team-day's actual value is the sum of its
  players' values.
- Exactly solvable as one assignment per team-day.

## Considered options

1. **Replace a played starter only with a player who played**: per role, at least as
   many assigned players as the actual lineup had starters who played.
2. **Unrestricted hindsight**: any slot may be left empty.
3. **Fill-first**: field the most players who played, then the most value.
4. **Fill empty and off-day slots only**: a played starter is never replaced.

On who is a candidate: starting and bench slots; or injured-list slots too. On the
starts limit: ignore it; or enforce it, which couples the days of a week.

## Decision

Recommended, for the owner to decide: **option 1**; candidates are players in starting
and bench slots, **not injured-list slots**; the **starts limit is not enforced**.

The optimal lineup of a team-day is the legal assignment of that day's candidates to
the league's starting slots with the greatest summed day value, where a player's day
value in a slot is the scaled value over replacement of what the slot's role credits,
and where each role fields at least as many players who played as it actually did. When
the actual lineup is as good as any, it is the optimal lineup.

Option 2 is mostly days that went badly; its size depends on where zero is put. Option
3 can be worse than the actual lineup. Option 4 leaves out the commonest decision. A
player in an injured-list slot needs a roster move before he can be started, which is
not a lineup choice. Enforcing the starts limit would turn 2,160 small problems into
weekly ones for 2 of 264 team-periods, on a setting whose meaning is inferred. That it
rarely binds is a fact about a limit of 13; so that a league with a tighter one is not
misread, each team-day carries the pitcher starts of the actual and of the optimal
lineup, and the limit itself is not interpreted.

## Consequences

- Good: the gap is made of swaps, fills and moves, each a choice between players.
- Good: `actual_value` is on the facts' scale; summed over a season it is
  `sum(total_value)`.
- Bad / accepted cost: it is still hindsight. Starting the bench player who happened to
  have the better day counts in full, and no manager could know it.
- Bad / accepted cost: it is not a model of winning the matchup. A margin counts the
  same in a category already won (ADR 0010).
- Bad / accepted cost: a starter's ruinous day cannot be avoided by the optimal lineup
  unless someone who played can take the slot, so the true hindsight optimum is higher.
- Bad / accepted cost: 2 team-periods' optimal lineups hold more pitcher starts than
  the league allows in a week. The counts on each team-day show where; nothing stops
  it.
- Bad / accepted cost: game-time locks, and a bench player activated from the injured
  list mid-day, are ignored.
- Follow-ups: #83 remains the test of whether the scalar predicts winning.
