# 0029. The start pool is every free-agent start by a pitcher who was a starter at the time

- Status: proposed
- Date: 2026-10-09
- Spec: [0089-starter-replacement-level](../specs/0089-starter-replacement-level/design.md) · Issue: #89
- Amends: [0001](0001-replacement-level-is-the-free-agent-pool.md), [0009](0009-a-pitching-pool-is-ranked-by-appearances.md), for the start kind only

## Context

ADR 0009 ranks each pitching pool by appearances of its kind while unrostered and keeps
the top N. For relievers that finds one-inning relievers, as intended. For starters it
finds the pitchers who started all year and whom nobody rostered: 306 starts at a 5.41
ERA. ADR 0001 named the bias and called it slight.

Measured on 2026: free-agent starts by pitchers who were starters up to that day number
1,290, by 153 pitchers, at 14.92 outs, a 4.90 ERA and a 1.403 WHIP. The ERA is 4.87 to
4.93 whether 3, 5 or 10 earlier starts are required, and 4.91 and 4.90 in the two
halves of the season. Rostered starts in lineups: 16.39 outs, 3.89.

Re-scoring every matchup with each player swapped for replacement showed pitching
categories giving 53% of category wins above replacement against 47% of the categories,
ERA and WHIP the largest of all seventeen; and the same real wins per unit of value for
starters as for hitters, so the level, not the arithmetic, is what tilts.

## Decision drivers

- Replacement should mean something a manager could actually have had (ADR 0001).
- The pool should hold the players doing that job, at the size of outing of that job
  (ADR 0009).
- No hindsight, and nothing taken from managers' moves beyond who was unrostered (owner,
  2026-10-08).
- Stable under its parameters, or without any.

## Considered options

1. **Keep the top N by free-agent starts.**
2. **Every free-agent start by a pitcher who was a starter at the time**, unranked.
3. **The best free agents each day**, ranked on their season to date.
4. **The most-used free agents each matchup period.**
5. **Players the league added and dropped**, over all their games.
6. **The tier beyond the league's demand.**

## Decision

Chosen by the owner on 2026-10-09: **option 2, for the start kind only.** The detail is
proposed here.

The start pool of a league-season is every start, on one of its scoring dates, by a
player on none of its rosters that date whose `fo_replacement_group` over his MLB days
of the season before that date is `SP`. It is not ranked and has no size. The relief
and batting pools stay as ADRs 0001 and 0009 have them.

Option 1 is half a run too lenient. Option 3 selects nobody among about 11 free-agent
starters a day and admits openers; applied to relievers it lengthens the outing. Option
4 shows usage to be adversely selected for starters: ERA 5.88, 5.17 and 4.97 for the top
6, 12 and 24. Option 5 rests on managers' moves and on streaks. Option 6 ranks with
hindsight.

Why only starts: a starter's quality as a free agent does not depend on how much he has
pitched, so no ranking is needed and the only filter is the job. For relievers and
hitters the unranked pool is not the players doing the job.

## Consequences

- Good: the start level is what was available, with the length of a real start and no
  parameter. Its pool is four times larger.
- Good: pitching categories fall from 53% to 50% of category wins above replacement.
- Bad / accepted cost: 2026's starters lose value: median 1.58 to 1.14; the top 20 goes
  from 11 starters and 9 hitters to 9 and 11.
- Bad / accepted cost: the three kinds no longer share one rule, and the other two keep
  whole-season hindsight.
- Bad / accepted cost: a pitcher's first appearance of a season is never in the pool,
  and early in a season the pool is thin.
- Bad / accepted cost: on a two-day fixture the pool is empty.
- Follow-ups: whether the relief and batting pools should be decided at the time.
