# A roster period settles after ESPN's counter stops — requirements

Issue: #75 · Tier: M · Status: approved 2026-10-10

## Problem

ADR 0018 fetches a closed roster period again until one of its captures records
`latestScoringPeriod > period + 7`. ESPN's counter is game-wide and stops one past the
last period that has a pro game, so a period within 7 of that stop can never satisfy the
rule: every `backfill espn` fetches it again, for good, and the audit keeps listing it as
inside the re-check window.

Issue #75 described this as a risk for a league configured differently from this one.
The landed data says it is this league's own history. Read on 2026-10-10 from the nine
settings and nine pro schedule captures in the landing zone (2018–2026):

| Season | `finalScoringPeriod` | Last period with a pro game | Counter after the season | Periods that could never settle |
|---|---|---|---|---|
| 2018 | 179 | 186 | 187 | none |
| 2019 | 187 | 194 | 195 | none |
| 2020 | 186 | 186 | 187 | 180–186 (7) |
| 2021 | 179 | 186 | 187 | none |
| 2022 | 182 | 182 | 183 | 176–182 (7) |
| 2023 | 179 | 186 | 187 | none |
| 2024 | 195 | 195 | 196 | 189–195 (7) |
| 2025 | 188 | 195 | 196 | none |
| 2026 | 180 | 187 | 188 | none |

In all nine seasons the counter rests at the last period with a pro game plus one. It is
not "final plus 8", the other reading left open on #75: 2020, 2022 and 2024 rest at
final plus 1. In three of nine seasons this league's final period was MLB's last day, and
its last seven periods would never have settled. 2026 is not affected (180 of 180
periods settled), so nothing is wrong today; it matters for 2027, whose final period is
not known yet, and for any past season whose rosters are landed (#83).

## Goals

- Every closed roster period settles, in every season, without anyone running
  `--refresh` and without a request that repeats for good.
- A period near the end of the season gets the same week of re-checking as any other
  (ADR 0018's purpose), not less.
- The audit says why such a period is still being fetched, and stops saying it once it
  settles.
- 2026 is untouched: no period becomes unsettled and none is fetched again.

## No-gos

- **No run against ESPN.** The build needs none: it is tested on constructed sidecars and
  checked against the landed 2026 sidecars read-only. Any run uses the league
  credentials and is the owner's to start.
- **No change to what closes a period.** ADR 0016 stands: closed means a capture's own
  counter is greater than the period.
- **No change to the 7-period window** or to `--refresh`.
- **No reading of a payload to decide what to fetch.** The rule uses sidecars only, as
  today; in particular ingestion does not read the pro schedule.
- **No dbt change.** dbt reads the newest capture of a period whichever rule fetched it.
- **Nothing landed is rewritten or deleted** (ADR 0015).

## Rabbit holes

- Deriving the stop from the pro schedule → not needed: the rule below never asks where
  the counter will stop, only whether it has moved. See design, option B.
- Working out the hour at which ESPN's counter turns over → the rule counts whole 24-hour
  spans between two captures that carry the same counter, which is safe whatever the hour
  is (design, *Why it cannot fire in season*).
- A league whose final period is at or past the stop (its last period could never even
  *close*) → not seen in nine seasons (final is at most the last period with a game in
  every one); left as an open question, not designed for.
- Landing past seasons' rosters → #83.

## Requirements

### R1. A stopped counter is extended by the calendar

So that a period settles a week after it closes whether or not ESPN's counter is still
moving.

- R1.1 THE SYSTEM SHALL compute, for each roster period of a league-season, an *extended
  counter*. Let `top` be the greatest counter any committed roster capture of the
  league-season carries. If the period has captures carrying `top` and `top` is greater
  than the period, the extended counter is `top` plus the number of whole 24-hour spans
  between the earliest and the latest capture of that period carrying `top`. Otherwise
  it is the greatest counter the period's captures carry.
- R1.2 THE SYSTEM SHALL treat a period as settled when its extended counter is greater
  than the period plus `RECHECK_PERIODS` (7), and SHALL NOT fetch a settled period unless
  `--refresh` is given.
- R1.3 WHEN every capture of a period carries a different counter, or two captures
  carrying the same counter are less than 24 hours apart, THE SYSTEM SHALL give the same
  answer as ADR 0018's rule (the extended counter equals the greatest counter).
- R1.4 THE SYSTEM SHALL NOT count a capture whose counter is at most the period towards
  the extended counter, however long that counter has been unchanged.
- R1.5 THE SYSTEM SHALL decide whether a period is closed from the greatest counter
  alone, as today, and never from the extended counter.
- R1.6 THE SYSTEM SHALL take a capture's time from the `fetched_at` of its sidecar and
  its counter as today: `source_status.latest_scoring_period`, or for a legacy sidecar
  the settings counter of the same run (ADRs 0016, 0017). A capture with no usable
  counter counts for nothing. A capture whose `fetched_at` cannot be read as a time
  keeps its counter as evidence, as today, and is left out of the spans only.
- R1.7 WHEN a period is fetched during a run, THE SYSTEM SHALL include that new capture
  in the period's evidence for the rest of the run, as today.
- R1.8 THE SYSTEM SHALL read no payload other than the settings capture a legacy sidecar
  needs, as today.
- R1.9 IF a period's captures repeat a counter lower than `top`, however far apart, THEN
  THE SYSTEM SHALL NOT extend it: some response has shown the counter higher, so that
  value is a lagging status and not a stopped counter.

### R2. The audit agrees and explains

- R2.1 THE SYSTEM SHALL use the same functions for the audit as for the fetch, so the
  two cannot disagree (as today).
- R2.2 WHEN closed periods are inside the re-check window, THE SYSTEM SHALL report them
  at INFO as today, and SHALL add how many of them have an extended counter greater
  than their greatest counter, naming the counter that is being extended.
- R2.3 WHEN every closed period is settled THE SYSTEM SHALL print no re-check line.

### R3. The record

- R3.1 THE SYSTEM SHALL describe the rule in the module docstring of
  `espn/rosters.py`, citing the new ADR beside ADR 0018.

## Expected values

The 2026 rows are read from the real landing zone, read-only. The others replay the real
counters of the seasons in the table above on constructed sidecars: no roster capture of
those seasons exists.

| Check | Expected | How to verify |
|---|---|---|
| 2026 committed roster captures | 182 over 180 periods (178 with one capture, 2 with two) | `LandingZone.committed`, counted |
| 2026 greatest counter by period | 186 for periods 1–178, 188 for 179–180 | `roster_evidence` |
| 2026 periods settled, before and after | 180 of 180; no period closed and unsettled | `is_settled` over the real sidecars |
| 2026 audit, roster lines | unchanged: the INFO line, no re-check line | `front-office audit`, before against after |
| 2022 shape (final 182, counter rests at 183), one run a day from the day after period 176, **today's rule** | periods 176–182 fetched on every run, never settled | pytest, expected to fail before the change |
| Same, **new rule**, period 182 | fetched on the 8 runs from its close to 7 days later, skipped from the 9th | pytest |
| Same, new rule, period 176 | settled on the first run 24 hours after the counter first read 183 (extended 184 > 183) | pytest |
| 2020 shape (186, 187) and 2024 shape (195, 196) | the last 7 periods all settle within 7 days of the counter stopping | pytest, parametrised with the 2022 shape |
| A finished season landed in one run (all captures carry the resting counter `rest`) | periods below `rest - 7` settle at once; period `p` of the last 7 settles on the first run at least `p + 8 - rest` days later | pytest |
| In season: one run a day over one period | fetched on each of the first nine runs, skipped on the tenth (ADR 0018, unchanged) | the existing nine-run test, unmodified |
| Two captures of period 100 with counter 100, 30 days apart | not closed, not settled | pytest (R1.4, R1.5) |
| Period 100 captured with counter 107 on two days 48 hours apart, while a capture of another period carries 109 | extended counter 107: closed, not settled, fetched again | pytest (R1.9) |
| A period-100 sidecar with counter 108 and a `fetched_at` that is not a stamp | closed and settled, as today | pytest (R1.6) |
