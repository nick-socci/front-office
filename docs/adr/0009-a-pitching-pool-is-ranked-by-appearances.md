# 0009. A pitching pool is ranked by appearances

- Status: proposed
- Date: 2026-10-03
- Spec: [0052-pitcher-replacement-by-outing](../specs/0052-pitcher-replacement-by-outing/design.md) · Issue: #52

## Context

[ADR 0001](0001-replacement-level-is-the-free-agent-pool.md) ranks free agents "by
playing time": plate appearances for hitters, outs for pitchers. For relievers, outs
selects the wrong players. The twelve unrostered relievers with the most outs are long
men and swingmen; the twelve with the most appearances are one-inning relievers, which is
what a rostered reliever is.

Measured on 2026 with pools split by kind of outing
([ADR 0008](0008-a-pitchers-day-is-measured-against-the-same-kind-of-outing.md)):

| Relief pool ranked by | Outs / app. | SV+HD / app. | ERA | Reliever-only pairs, median value |
|---|---|---|---|---|
| Outs | 4.20 | 0.201 | 3.35 | −0.56 |
| Appearances | 2.80 | 0.256 | 3.49 | +0.57 |

Rostered pitchers' relief appearances while started: 3.01 outs, 0.452 SV+HD, ERA 3.37.
So ADR 0008 alone does not fix relievers; this choice does.

## Decision drivers

- The pool should hold the players a manager would pick up to do that job.
- The ranking should use the same unit the level is expressed in: the played day.
- It must not select on a scored category.
- Deterministic, and stable when N is halved or doubled.

## Considered options

1. **Appearances of that kind** — free-agent start days for the start pool, relief days
   for the relief pool.
2. **Outs in that kind of outing** — ADR 0001's rule, applied per kind.
3. **Saves plus holds** — the relievers a manager adds for the category they are added for.

## Decision

Chosen: **appearances**. Ties are broken by outs recorded in those appearances, then by
`mlbam_player_id`. The tie-break matters: four relievers share the 10th to 13th most
appearances (66), and breaking that tie by id alone would be arbitrary.

Outs rewards the length of an outing, which is the very thing being measured, so the pool
drifts to the longest relievers and charges everyone else for not being one. Saves plus
holds selects the pool on a scored category, and produces a floor better than the
players it is a floor for (#52: ERA 2.83 against 3.47).

For the start pool the two rankings pick nearly the same players (14.98 outs a start by
appearances, 15.13 by outs); appearances is used for both so there is one rule.

## Consequences

- Good: the relief level is stable in the size of an outing: 2.68 / 2.80 / 2.83 outs at
  N = 6 / 12 / 24.
- Bad / accepted cost: the relievers managers use most are good ones, so replacement ERA
  (3.49) is about what rostered relievers post (3.37). A reliever's value then comes
  almost entirely from saves, holds and strikeouts. That is arguably true of a fantasy
  reliever, but it is a strong floor.
- Bad / accepted cost: relief ERA still moves with N (3.18 / 3.49 / 3.58).
- The hitter pool keeps ADR 0001's ranking by plate appearances; this ADR supersedes only
  "outs for pitchers".
- Follow-ups: none.
