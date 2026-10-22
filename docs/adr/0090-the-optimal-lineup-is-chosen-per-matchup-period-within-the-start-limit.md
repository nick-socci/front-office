# 0090. The optimal lineup is chosen per matchup period, within the start limit

- Status: accepted
- Date: 2026-10-21
- Spec: [0164-optimal-lineup-per-matchup-period](../specs/0164-optimal-lineup-per-matchup-period/design.md) · Issue: #164
- Supersedes: [0079](0079-only-the-actual-lineup-is-credited-under-the-limit-until-the-optimal-one-is-solved-a-week-at-a-time.md)
- Amends: [0037](0037-the-optimal-lineup-replaces-a-played-starter-only-with-a-player-who-played.md), for the grain of the solve and the starts limit

## Context

ADR 0037 solves each team-day alone and does not enforce the games-started limit. ADR 0079
credits only the actual lineup under the limit, because a limit applied after a per-day
solve can leave the optimal lineup below the actual one (spec 0164, C7: 2022 p18 t1). So
today the optimal lineup can use more starts than the limit allows. The owner asked
(2026-10-18) for the highest-scoring starts of the week that stay within the limit.

ESPN credits every start on the day that reaches the limit, and none after it (ADR 0071).
The league has a gentleman's agreement not to go past the limit, even so (the owner,
2026-10-21). In 8 team-periods of eight seasons the actual lineup did go past it (C18).

## Decision drivers

- The optimum is a lineup a manager in this league would set.
- It is never worse than the actual lineup.
- Both lineups are credited by one rule.
- Nothing moves where the limit does not bind.

## Considered options

What "within the limit" means:
1. **As ESPN credits.** A lineup's starts are credited by ADR 0071's rule; the day that
   reaches the limit finishes, and a start after it counts 0.
2. **As ESPN credits, with no uncredited start.**
3. **At most the limit.** The period's starts may not exceed `floor(start_limit)`.

Where the actual lineup went past the limit, under option 3:
4. **The cap is the actual lineup's starts.**
5. **No optimum** for that team-period.
6. **Relax ADR 0037's minimum** so that a lineup within the limit exists.

## Decision

Chosen by the owner on 2026-10-21: **option 3, with option 4**.

The optimal lineups of a team's matchup period are chosen together:
- **The cap:** they use at most `floor(start_limit)` starts. Where the actual lineup's
  starts in the period are more, the cap is that count.
- **Crediting:** they are credited by ADR 0071's rule, counting their own starts. Under
  the plain cap, no optimal start is ever past the limit.
- **Each day** keeps ADR 0037's constraints, its minimum of players who played and its
  tie-break.
- **A league-season with no limit** is solved per day, as before.

- **3 over 1 and 2:** options 1 and 2 count starts that the league's managers agree not
  to take.
- **4 over 5 and 6:** with option 3 alone, 7 of the 8 over-limit periods have no lineup
  that meets ADR 0037's minimum (C8). Option 5 leaves those periods without a gap.
  Option 6 changes a rule this spec does not own, and lets the optimum fall below the
  actual lineup. Option 4 lets the optimum go as far as the manager did, and no further.

## Consequences

- Good: the optimum never goes past the agreement unless the manager did. It changes on
  16 team-periods of eight seasons (19 team-days, 18 with a new lineup; C9), and never
  falls below the actual lineup.
- Good: the actual and optimal lineups are credited alike again, as ADR 0073 intended,
  without its failure.
- Bad / accepted cost: a manager who went past the limit is compared with an optimum
  allowed the same excess. The gap there measures choices within those starts, not the
  cost of breaking the agreement.
- Bad / accepted cost: in those 8 periods the optimum may field a start that counts 0,
  when that beats a reliever with a negative day (C12).
- Follow-ups: when accepted, 0079's `Status` becomes `superseded by` this ADR, and 0037's
  `amended by` names it too.
