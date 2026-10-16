# 0071. A games-started limit is a per-day rate, and the day that reaches it finishes

- Status: proposed
- Date: 2026-10-16
- Spec: [0152-games-started-limit](../specs/0152-games-started-limit/design.md) · Issue: #152

## Context

ESPN league settings hold `rosterSettings.lineupSlotStatLimits`, an object keyed by slot
id: `{"22": {"statId": 33, "limitValue": 1.857142857}}` in this league from 2022 on (stat
33 is games started), 1.571 in 2018 and 2019, none in 2021. The models credit every start
in a pitcher slot. ESPN does not always: in 2023, matchup 110, team 7 has 14 starts in its
game lines and 13 in its total, and the one left out is the only start of the period's
last day (#83's investigation).

What the setting means is not documented; it is read from what ESPN did. In 2020, the one
rotisserie season, the same key holds 78.0 and a second entry holds stat 81 at 545.0:
season totals, not rates (spec 0152, C1, C2). ESPN reports a side's games started from
2019 on, and seven sides exceed the limit by ESPN's own count (C5).

## Decision drivers

- Reproduce ESPN's totals without breaking any value that matches today.
- Read the rule from each league-season's settings, so a tighter limit elsewhere is
  applied and a league-season with none is untouched.
- A setting the models cannot interpret fails loudly rather than being ignored.

## Considered options

1. **Per-day rate × the period's days; the day that reaches it finishes; starts only** —
   a start is not credited when the team's credited starts on earlier days of the
   matchup period already reach `limitValue × days`.
2. **The same, but the limit is cut on the day it is reached** — no day may take a team
   past it.
3. **The same as 1, but every pitcher-slot day past the limit is dropped**, relief
   included.
4. **A weekly whole number** (`round(limitValue × 7)`) applied to every period, whatever
   its length.

## Decision

Chosen by the owner on 2026-10-16, as recommended: **option 1**, because it is the only
reading that breaks nothing ESPN's totals confirm. Run against all eight seasons (spec
0152, C6 to C8): option 1 drops one start (2023-08-20) and makes the side's values equal
or explained; option 2 drops 25 starts and breaks 68 matching values, so ESPN does let the
reaching day finish (C5's seven sides); option 3 breaks one, so relief still counts.
Option 4 contradicts the setting: a per-day value is stored precisely so that periods of
8 to 19 days scale (C9).

The limit is compared exactly: `starts_before >= limitValue × days`, in floating point,
not rounded. For a 7-day period this is exactly 11 or 13 (C3). For a period whose limit
is not a whole number, how ESPN rounds is not observed in eight seasons; the exact
comparison is the literal reading.

The rule applies to an entry whose `statId` is 33, in a league-season whose scoring type
is head-to-head. The entry's key (22) is recorded and not interpreted. Any other entry of
a covered league-season, and any entry of a covered league-season that is not
head-to-head, fails the build by name.

## Consequences

- Good: 9 of #147's 133 unexplained values are resolved, and none of the 52,345 matching
  values moves.
- Good: a league with a tighter limit, or a manager who streams starters, is credited as
  ESPN credits.
- Bad / accepted cost: the rule rests on one league, seven sides past the limit and one
  start dropped. A different rule elsewhere would show as a side whose games started
  differ from ESPN's.
- Bad / accepted cost: rounding of a non-whole limit is a guess, the literal one.
- Follow-ups: rotisserie limits (season totals) are not modelled; a covered rotisserie
  league-season with one fails until they are.
