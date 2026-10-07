# 0021. A scoring period is dated from MLB's schedule, not from ESPN's period counter

- Status: proposed
- Date: 2026-10-07
- Spec: [0070-scoring-period-dates](../specs/0070-scoring-period-dates/design.md) · Issue: #70

## Context

ESPN keys rosters by scoring period and publishes no period-to-date mapping in anything
landed. `stg_espn__scoring_periods` derives one from an anchor: the newest settings
capture's `latestScoringPeriod` is taken to be the period of the Eastern date the capture
was fetched.

Measured on 2026: the counter stopped at 188 while the final period is 180. Captures of
2026-09-26 (186) and 2026-09-28 (188) imply period 1 = 2026-03-25; captures of 2026-10-06
and 2026-10-07 (both 188) imply 2026-04-02 and 2026-04-03. All five were taken after the
final period, so "the season was still in progress" does not separate the right ones
from the wrong ones. `standingsUpdateDate` in the same status block last moved at
2026-09-27 04:26 Eastern, and its earlier value is 04:32, so even a moving counter may
not turn over at midnight.

Two things landed do fix the mapping. MLB's regular season opens on 2026-03-25. And ESPN's
roster payloads carry one stat line per game per period: with period 1 on 2026-03-25,
the number of distinct ESPN games equals the number of played MLB games on all 177
periods that have any, and the 3 periods without one fall on days with no MLB game. At a
shift of one day either way, 47 periods match.

## Decision drivers

- A date must not depend on when, or how often, settings were fetched.
- It must work for a season first fetched after it ended (#57).
- The rule should be simple enough to read in the model, and checked by evidence it
  does not itself use.
- No new ingestion to fix a P1.

## Considered options

1. **MLB opening day**: period 1 is the season's first regular-season official date.
2. **The earliest settings capture** as the anchor instead of the newest.
3. **Only captures with `latest <= final`** as anchors; no dates without one.
4. **Fit the offset** at which ESPN's game lines match MLB's game days.
5. **A date ESPN publishes**, from an endpoint not yet landed.

## Decision

Proposed: **option 1**. Not yet decided by the owner.

Scoring period 1 of a league-season is the earliest official date among that season's
regular-season MLB games, and period *p* is *p* − 1 days later. The settings capture
supplies only how many periods there are. The mapping is tested on every build against
ESPN's game lines (the evidence of option 4), which the rule does not use.

Option 2 is right for 2026 only because the first capture happened to be taken while the
counter moved; it is wrong for any season first fetched later. Option 3 leaves 2026
with no dates at all. Option 4 is the strongest evidence but a poor rule: it needs every
roster parsed before any date exists, has no answer for a league-season with no rosters,
and hides a disagreement that should stop the build. Option 5 may be the proper source,
but it is new ingestion and unverified.

## Consequences

- Good: the two frozen captures, and any taken later, change nothing.
- Good: the same rule dates a season fetched years afterwards.
- Good: the check is stronger than the one it replaces, 177 periods instead of one.
- Bad / accepted cost: an ESPN staging model now reads an MLB staging model. No other
  staging model crosses sources.
- Bad / accepted cost: the opening-day test stops being independent evidence, since the
  model is now built from opening day.
- Bad / accepted cost: it assumes ESPN starts scoring on MLB's first regular-season game
  and scores one period per calendar day. Both hold for 2026. A season opened by
  international games played days before the rest is not verified; the game-line test
  would fail there, but only for a league-season with rosters landed.
- Bad / accepted cost: if every game of opening day were postponed, the earliest official
  date would be a day late. Not observed.
- Follow-ups: [ADR 0022](0022-espns-period-counter-is-not-a-date-after-the-final-period.md)
  for what the counter is still used for. Option 5 is worth verifying before #57.
