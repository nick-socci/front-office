# 0047. A period counter that has stopped is extended by the calendar

- Status: proposed
- Date: 2026-10-10
- Spec: [0075-settle-after-counter-stops](../specs/0075-settle-after-counter-stops/design.md) · Issue: #75

## Context

[ADR 0018](0018-a-closed-roster-period-is-rechecked-for-seven-periods.md) settles a
closed roster period when one of its captures records ESPN's counter greater than the
period plus 7. The counter is game-wide and stops when MLB's regular season ends
([ADR 0022](0022-espns-period-counter-is-not-a-date-after-the-final-period.md)).

Read from the landed settings and pro schedule captures of 2018–2026: in all nine
seasons the counter rests at the last period with a pro game plus one. In 2020, 2022 and
2024 this league's final period was that last period, so its last seven periods could
never have settled: they would be fetched on every run for good. In the other six,
2026 among them, the final period was seven earlier and everything settles, by one.
Next season's final period is not known.

The eight past seasons were captured on one day in October 2026. Where the counter rests
is known; the moment it stops has not been observed.

## Decision drivers

- Every closed period must settle without a person remembering to do something.
- The last periods of a season deserve the same week of re-checking as any other: a
  commissioner's correction is as likely there.
- Ingestion fetches and saves; it decides what to fetch from sidecars, not payloads.
- Do not build a rule on how the counter stops, which has only been seen at rest.
- Leave ordinary periods exactly as ADR 0018 has them.

## Considered options

1. **Extend the counter by the calendar**: when two captures of a period carry the same
   counter, add one per whole 24 hours between them.
2. **Take the stop from the pro schedule** (last period with a game, plus one) and treat
   a capture carrying it as final.
3. **Settle by date**: a capture fetched more than 7 days after the period's date.
4. **Nothing automatic**: keep the rule, quiet the audit, rely on `--refresh`.

## Decision

Chosen: **option 1** (proposed; the owner decides).

Let `top` be the greatest counter any roster capture of the league-season carries. For
a period whose captures carry `top`, with `top` greater than the period, the *extended
counter* is `top` plus the whole 24-hour spans between the earliest and the latest
capture of that period carrying it; for any other period it is the greatest counter its
captures carry. A lower counter that repeats is a lagging status, not a stop, and is
never extended. A period is settled when its extended counter is greater than the
period plus 7. Whether a period is closed is still
decided by the counter alone (ADR 0016).

While the counter moves, two captures a day apart never carry the same value, so the
extended counter is the counter and ADR 0018 is unchanged. Once it stops, the extended
counter rises by one a day, as ESPN's would have.

Option 2 knows where the counter will rest, but a capture taken the morning after the
season already carries that value, so it still needs a time margin to give the last
periods their week, and that margin is option 1. It also has ingestion interpret a
payload and rests on a pattern seen only after the fact. Option 3 states the intent most
directly and costs nothing extra for past seasons, but a period's date comes from the
pro schedule, and it replaces the rule for every period to repair seven. Option 4 leaves
seven requests on every run for good.

## Consequences

- Good: every closed period settles, in any league and any season, with no new input.
  A period that can never close (a final period at or past the resting counter, not
  seen in nine seasons) is outside this decision.
- Good: the last period of a season is fetched on 8 runs after it closes, as an ordinary
  period is.
- Good: nothing depends on when, where or why the counter stops.
- Bad / accepted cost: a season that finished long ago and is landed in one run has its
  last seven periods fetched again on each run for up to seven days, though nothing can
  have changed: at most 7 requests and about 17 MB a run. This is what #83 would meet.
- Bad / accepted cost: runs less than 24 hours apart do not advance the extension, and
  drifting run times can cost one more capture per period.
- Bad / accepted cost: no real capture exercises the rule until the end of the 2027
  season or a past season's rosters. It is tested on constructed sidecars carrying the
  real counters of 2020, 2022 and 2024.
- Bad / accepted cost: if every response of two runs a day apart carried the same
  lagging status, it would be extended as a stopped counter. Not observed; #66 is where
  it would show.
- Follow-ups: if #83 is scheduled and its week of repeat fetches is unwelcome, option 3
  is the alternative to weigh then.
