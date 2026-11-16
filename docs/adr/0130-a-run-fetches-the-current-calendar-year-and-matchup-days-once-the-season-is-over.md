# 0130. A run fetches the current calendar year, and matchup days once the season is over

- Status: accepted
- Date: 2026-11-15
- Spec: [0217-dagster-daily-pipeline](../specs/0217-dagster-daily-pipeline/design.md) · Issue: #217

## Context

Every fetch command takes `--season`. ESPN's newest 2026 settings capture (2026-11-10) has
`latestScoringPeriod` 188 above `finalScoringPeriod` 180, though `isActive` is true; 2025's agree
(196 over 188) (spec C3). 2026's matchup days were fetched on 2026-10-11, after the season ended
(C4). `int_fantasy__matchup_periods` takes a running season's mapping from `pointsByScoringPeriod`
and the matchup-day marker only for scoring periods that has no row for (C5), and
`espn/matchup_days.py` is for seasons that are over: in a running season it would request periods
that have not happened. No 2027 settings capture exists, so ESPN's rollover is unobserved (C11).

## Decision drivers

- The first week of 2027 cannot be redone (#66, #69), so nothing may need a hand edit at rollover.
- No request for a future scoring period.
- The tail of one season settles within 7 days of its last game (ADR 0019).

## Considered options

1. **The calendar year in America/New_York**, `FO_SEASON` to override, and `espn_matchup_days` only
   when the newest landed settings of the season show it over.
2. **A season set by hand** in the run's environment.
3. **The newest season with unsettled work**, found by reading the landing zone.

## Decision

Chosen by the owner on 2026-11-15: **option 1**, as recommended.

January 1 moves the run to the new season by itself, and 2026's last games settled in October.
Option 2 loses the first week if the edit is forgotten. Option 3 is the most code and its case that
matters, nothing unsettled and nothing yet for 2027, is the one with no data to test it on.

## Consequences

- Good: nothing to change at rollover; no future-period requests.
- Bad / accepted cost: between January 1 and the first 2027 settings, ESPN may refuse or answer
  oddly; `fetch_complete` fails on those days. #218 schedules the run only in-season, and #220
  rehearses the rollover.
- Bad / accepted cost: "over" is read from two settings fields that two seasons agree on; a third
  shape would show as matchup days never fetched, which `front-office audit` reports.
- Follow-ups: #66 and the first in-season week confirm `pointsByScoringPeriod` in a running season.
