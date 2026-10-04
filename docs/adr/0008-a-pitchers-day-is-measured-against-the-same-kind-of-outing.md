# 0008. A pitcher's day is measured against the same kind of outing

- Status: accepted
- Date: 2026-10-03
- Spec: [0052-pitcher-replacement-by-outing](../specs/0052-pitcher-replacement-by-outing/design.md) · Issue: #52

## Context

[ADR 0001](0001-replacement-level-is-the-free-agent-pool.md) put every pitcher in one of
two groups, `SP` or `RP`, and measured all his pitcher-slot days against that group's
pool. A group is a property of the player; a day's innings are a property of the outing.
The two disagree often: 46 rostered pitchers are eligible at both `SP` and `RP`, and they
made 348 starts and 204 relief appearances while started. Measured on 2026, an
`RP`-default swingman's start is compared with a reliever's day and a reliever's inning
with a swingman's.

Per-day eligibility cannot settle it. The roster payload for a scoring period carries the
player's eligibility when it was fetched: three pitchers show `P,SP` in the 2026-09-21
capture and `P,SP,RP` in the 2026-09-26 capture of the same periods (one of them on every
period from 1 to 180), and no player's eligibility changes once across the 180 periods of
one capture.

What "value" means here is the owner's decision.

## Decision drivers

- A played day must be compared with a like played day, because the unit is the played
  day ([ADR 0002](0002-value-is-measured-per-played-day.md)).
- Built from data that is true for the day it describes.
- Lineup construction is #12's subject, not player value's.
- Free agents must be classifiable by the same rule as rostered players.

## Considered options

1. **Three groups by eligibility** — `SP` only, `RP` only, `SP` + `RP`, each rostered
   pitcher against his own group's pool.
2. **By slot** — an `SP`-slot day against a replacement start, an `RP`-slot day against a
   replacement relief appearance, a `P`-slot day by the kind of outing.
3. **By kind of outing** — a start against a replacement start, a relief appearance
   against a replacement relief appearance, whatever the slot or eligibility.

## Decision

Chosen: **by kind of outing**. A pitched day is a `start` if he started any game that
date, otherwise a `relief` appearance; each kind has its own free-agent pool and level.
It is the only option that compares like with like under a per-played-day unit, and it
needs no eligibility.

Option 1 needs eligibility on the day, which does not exist, and free agents have none at
all, so their pool would be grouped by an imitation of ESPN's thresholds. It also still
mixes kinds: its swingman pool is 700 days of which 89 are starts. Option 2 differs from
option 3 on 130 of 5,254 started pitching days (18 starts in an `RP` slot, 112 relief
appearances in an `SP` slot). On those it credits a start about 12 outs for being
compared with a reliever's day, while charging nothing for the four days the slot then
sits empty. That is a slot-day question, which ADR 0002 gave to #12.

This supersedes ADR 0001's two pitcher groups and the 2026-10-03 amendment to spec 0011
that added `pitcher_slot_replacement_group`. ADR 0001's decision that replacement is the
free-agent pool, and its hitter group, stand.

## Consequences

- Good: reliever-only pairs move from a median of −0.52 to +0.57 (with
  [ADR 0009](0009-a-pitching-pool-is-ranked-by-appearances.md)); a two-way player's
  starts are measured as starts with no special rule.
- Good: a player's `SP`/`RP` label no longer changes any number.
- Bad / accepted cost: the real advantage of dual eligibility, a starter's innings from an
  `RP` slot, earns nothing here.
- Bad / accepted cost: an opener's one-inning day is charged a full replacement start.
- Bad / accepted cost: with every pitcher measured against his own kind, innings spread
  far less (standard deviation 25.4 outs, from 115.6), so a standard deviation of innings
  is cheaper and starters take 15 of the top 20 total values, from 9.
- Follow-ups: on acceptance ADR 0001's status becomes `accepted; pitcher groups superseded
  by 0008 and 0009`. #12 must not assume per-day eligibility from the 2026 backfill.
