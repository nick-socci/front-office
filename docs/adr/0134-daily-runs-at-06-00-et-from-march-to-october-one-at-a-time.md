# 0134. `daily` runs at 06:00 ET from March 1 to October 31, one at a time, with a two-hour limit

- Status: accepted
- Date: 2026-11-17
- Spec: [0218-schedule-the-daily-run](../specs/0218-schedule-the-daily-run/design.md) · Issue: #218

## Context

Spec 0216 R1.2 wants each day's run complete by 09:00 America/New_York and left the hour to this
spec. ADR 0130 says the run is scheduled only in-season, because after January 1 ESPN's answer for a
new season is unobserved and `fetch_complete` would fail daily. MLB's 2027 dates (C8): spring
training ends March 24, the regular season runs March 25 to September 26, the postseason ends
October 31. A boxscore's settle window is seven days (ADR 0019). Dagster's defaults would hurt:
a schedule starts stopped (C1), and ten runs may go at once (C3), against a writer lock that fails
the second fetch. (An unpartitioned schedule already launches one run after an outage, C2.) The latest 2026 regular-season
start was 22:15 ET (C16).

## Decision drivers

- Nothing needs a hand edit at the first week of 2027 (#66, #69).
- Quiet in the winter, so a red check means something (#219).
- A missed day costs one run; a stuck run cannot hold the next day.
- Time between the run and 09:00 for a person to act on a failure.

## Considered options

1. **A cron with a month range** (`0 6 * 3-10 *`, America/New_York), `RUNNING` by default, and the
   instance's `max_concurrent_runs: 1` and a two-hour run limit.
2. **A year-round daily schedule.**
3. **A schedule function that skips outside MLB's season dates.**

## Decision

Chosen by the owner on 2026-11-17, at the spec's walkthrough: **option 1**, as recommended. The window holds spring training's end, the regular season, the settle tail
and the postseason for one cron string, and a rescheduled season is one edit. The hour is 06:00: the
latest game starts at 22:15 ET and ends about 01:45, and three hours remain before 09:00. Option 2
fails ESPN's rollover every day of the winter. Option 3 follows MLB's calendar exactly, for a function
and a data source that a month's slack does without.

The limits are the instance's, in `deploy/dagster.yaml`: one run at a time (a second queues), and a
run over two hours is ended and marked failed. A missed stretch needs no setting: a schedule without a
partition set launches only the latest tick (C2), and a run fetches what is unsettled, so one catches
up every missed day. Two hours is a proposal against a 10-minute run (C9); #220's
rehearsal times a full in-season one. `FO_DAILY_CRON`, when set, replaces the cron for rehearsals.

## Consequences

- Good: no tick from November to February; no second writer.
- Bad / accepted cost: a season that starts before March 1 or ends after October 31 needs the string
  changed. Spring training games before March 1 are not captured.
- Bad / accepted cost: a stuck run waits up to two hours to be ended.
- Follow-ups: #219 alerts on a failed check; #220 rehearses a skipped day and the January rollover.
