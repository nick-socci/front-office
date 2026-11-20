# 0136. The id map is refreshed weekly on its own schedule

- Status: accepted
- Date: 2026-11-17
- Spec: [0218-schedule-the-daily-run](../specs/0218-schedule-the-daily-run/design.md) · Issue: #218

## Context

Spec 0217 left `idmap_capture` out of `daily` and gave it no cadence ("materialized by hand until
#218"). It has two captures in seven weeks, 4.2 MB each (C11). Its freshness feed, `idmap_runs`, warns
after 14 days and is dormant until the 2027 schedule wakes it. Nothing refreshes it today, so the
feed would warn two weeks into the season.

## Decision drivers

- The id map stays under its 14-day warning with some slack.
- `daily` is not changed (spec no-go).
- No landing of a capture a day for a source that changes about monthly.

## Considered options

1. **Its own weekly schedule**, Mondays at 05:00 America/New_York in the same months as `daily`, on
   an `idmap` job.
2. **Inside `daily`.**
3. **By hand.**

## Decision

Chosen by the owner on 2026-11-17, at the spec's walkthrough: **option 1**, as recommended. A week leaves a week of slack under the 14-day warning, lands about 35
captures (0.15 GB) a season against about 245 (1 GB) for option 2, runs an hour before `daily`, and
leaves `daily`'s selection as 0217 wrote it. Option 3 is how the feed goes stale, and nothing would
say so before #219.

## Consequences

- Good: a current id map on the 06:00 build, with `daily` untouched.
- Bad / accepted cost: a second schedule and job to read in the UI; the instance's one-run limit
  queues it behind a stuck run for up to the run limit (ADR 0134).
- Follow-ups: the feed's `idmap_runs` freshness is #219's.
