# 0055. A scoring period's matchup period is the one ESPN attaches that day's rosters to, where the matchup does not list its days

- Status: proposed
- Date: 2026-10-11
- Spec: [0083-past-season-rosters](../specs/0083-past-season-rosters/design.md) · Issue: #83

## Context

Daily production is summed to a matchup through a mapping from scoring period to
matchup period. It is read from each matchup's `pointsByScoringPeriod`, whose keys are
the days the matchup covers. ESPN carries that in full for 2025 and 2026 only: 2018 has
one key per matchup period, its first day, and 2019 and 2021 to 2024 have none (spec
0083, C1, C2). ADR 0026 let those seasons build without the mapping while they had no
rosters. #83 lands their rosters.

Nothing in the landed settings or rosters gives the mapping (C3, C4). A probe on
2026-10-11 found that a matchups request made with a `scoringPeriodId` returns the whole
schedule with `rosterForCurrentScoringPeriod` on the sides of one matchup period only:
period 8 for 2023's scoring period 60, period 1 for 2019's scoring period 15 (C9). A
calendar rule fitted to 2018, 2025 and 2026 predicts 25 matchup periods for 2019, which
has 24 (C6).

## Decision drivers

- A day belonging to the wrong matchup produces totals that look reasonable and do not
  reconcile.
- What ESPN reports, not what we infer: general across leagues and matchup lengths.
- No rule or list per season.
- The 2026 season must not move, and a running season must not come to depend on a
  second request per day.
- Requests to an undocumented API, and disk.

## Considered options

1. **ESPN's marker, one capture per scoring period**: 1,469 requests, about 1.5 GB.
2. **ESPN's marker at both ends of each calendar week**, the days between inferred.
3. **A calendar rule**, checked only by reconciliation.
4. **A seed kept by hand.**

## Decision

Chosen by the owner on 2026-10-11, going through the spec's decisions: **option 1**.

A scoring period's matchup period is read from `pointsByScoringPeriod` where a matchup
lists it. Otherwise it is the matchup period whose sides carry
`rosterForCurrentScoringPeriod` in the response for that scoring period. Where both
exist they must agree, and the build fails if they do not. Before any season depends on
the marker it is compared with `pointsByScoringPeriod` for every scoring period of 2025
and 2026.

Option 2 has ingestion decide what to fetch from a calendar assumption. Option 3 cannot
explain 2019 without a clause for it, and is fitted to weekly matchups. Option 4 ties
nothing to ESPN.

## Consequences

- Good: every season's mapping is what ESPN said about each day.
- Good: two sources that check each other on 368 days, and on 2018's 24 period starts.
- Bad / accepted cost: a new endpoint, `matchup_days`, of large responses read for one
  fact each.
- Bad / accepted cost: the marker is an observed behaviour of an undocumented API, seen
  on two days before the build. If the comparison fails, this ADR is not accepted as
  written and the decision returns to the owner.
- Follow-ups: if ESPN ever drops `pointsByScoringPeriod` for a running season, the
  marker has to be fetched daily, with a settle rule it does not have today.
