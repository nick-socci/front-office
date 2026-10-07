# 0022. ESPN's period counter is not read as a date after the final period

- Status: accepted
- Date: 2026-10-07
- Spec: [0070-scoring-period-dates](../specs/0070-scoring-period-dates/design.md) · Issue: #70

## Context

With [ADR 0021](0021-a-scoring-period-is-dated-from-mlbs-schedule.md) the warehouse no
longer dates anything from `status.latestScoringPeriod`. The audit still compares it:
each settings capture implies a date for period 1, and any disagreement, between
captures or with MLB opening day, is an error. On 2026 that check now fails for good:
the counter stopped at 188 and every later capture implies a later date.

What the counter means once the season is over is not documented by ESPN. Observed on
2026, with the final period at 180: 186 on 2026-09-26 and 188 on 2026-09-28, each the
right period for its date, then 188 on 2026-10-06 and 2026-10-07. MLB's last
regular-season day, 2026-09-27, would be period 187. So the counter ran past the league's
final period to the day after MLB's season and stopped. No capture exists from
2026-09-29 to 2026-10-05.

ESPN's game-level season resource, checked on 2026-10-07 (see ADR 0021), explains it: the
counter is game-wide, not the league's. It reports `currentScoringPeriod` 188, and the
last period with a pro game in 2026 is 187. Whether it stops one past the last game in
other seasons was not checked.

The check has a use in season: daily runs in 2027 will take a settings capture a day,
and a counter that disagrees with opening day then would mean the mapping, or the
Eastern-day boundary, is wrong.

## Decision drivers

- An audit error must mean something is wrong, not that time has passed.
- Keep the in-season check, which is the only one that sees the counter move.
- Do not build a rule on one season's observation of when the counter stops.

## Considered options

1. **Compare only captures with `latest <= final`**; report the rest as a count.
2. **Compare captures fetched up to the day after MLB's last regular-season game.**
3. **Drop the comparison**, since nothing is dated from the counter any more.
4. **Keep comparing every capture** and downgrade a disagreement to a warning.

## Decision

Chosen: **option 1**, by the owner on 2026-10-07.

A settings capture is in progress when its `latestScoringPeriod` is at most its
`finalScoringPeriod`. The audit compares the date an in-progress capture implies for
period 1 with MLB opening day, and reports a disagreement as an error. A capture past
the final period is not compared with anything; the audit reports how many there are.
`latest_scoring_period` stays a column of `stg_espn__league_settings`, described as
ESPN's counter and not as a date.

Option 2 keeps the three 2026 captures that agree, and the game-wide schedule makes its
rule plausible, but it ties the audit to the date of MLB's last game for evidence the
game-line test already gives. Option 3 loses the only in-season cross-check. Option 4 leaves a permanent
warning on every finished season, which teaches the reader to ignore it.

## Consequences

- Good: the 2026 audit is clean again without hiding anything: 5 captures past the final
  period, none compared.
- Good: a finished season fetched later (#57) audits clean from the start.
- Bad / accepted cost: 2026 has no in-progress capture, so the counter is never checked
  against opening day for 2026. The game-line test of ADR 0021 covers that season.
- Bad / accepted cost: between the final period and the end of MLB's season the counter
  did still move in 2026, and those captures are not used.
- Bad / accepted cost: if the counter turns over at about 04:30 Eastern, not midnight, an
  in-progress capture taken in the small hours implies a date one day early and the
  audit reports an error. Not observed; the first week of 2027 will show it (#66 runs
  then).
- Follow-ups: the roster re-check rule (ADR 0018) needs `latest > period + 7`. In 2026
  the counter stopped at exactly final + 8. A league whose final period is within 7 days
  of the end of MLB's season could never settle its last periods. Not in this spec: #75.
