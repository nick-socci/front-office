# Settled roster captures: a period is final only when a capture proves it — requirements

Issue: #27 · Tier: M · Status: draft

## Problem

A scoring period's roster can change until the period closes. The fetch logic skips a
period once any capture exists and the league has moved past it, without asking whether
that capture was taken after the period closed. Review finding
[R1](../../reviews/2026-09-27-code-review.md#r1--p1-active-roster-snapshots-can-be-frozen-before-their-final-state):
fetch period 100 while it is current, change a lineup that evening, run the next day, and
the mid-day lineup is kept for good. Every started player-day and every matchup score
downstream is credited from it.

The 2026 season is not affected: all 180 roster captures were taken in one run on
2026-09-26, after the season ended, and the audit shows each one final. The defect bites
the first time ingestion runs while a season is in progress, which is the 2027 daily
schedule. #29 gave the fetch logic one definition of a committed capture to build on.

## Goals

- A period is skipped only when a committed capture shows the league had moved past that
  period when the capture was taken.
- The evidence is recorded with the capture, so the question is answered from sidecars.
- The fetch logic and the audit give the same answer, from one definition.
- A period that should be final and cannot be shown final is fetched again and reported,
  never quietly accepted.
- A commissioner's correction to a recently closed period is picked up without anyone
  asking for it.

## No-gos

- **Not R4** (#30). Boxscore settle windows are a different rule on a different source.
  The sidecar field introduced here is named so that #30 can use it.
- **No change to any dbt model, seed, fixture or to the raw table.** Staging already
  takes the latest capture per period (`fo_espn_latest`), which is the one taken last.
- **No existing sidecar is rewritten.** The 180 captures of 2026 keep the sidecars they
  have (AGENTS.md: nothing in the landing zone is replaced).
- **No request to ESPN by an agent.** Tests use a fake transport. The real season is
  verified by reading the landing zone; a live run is the owner's, with the credentials.
- **No detection of which periods were edited.** A commissioner can change a past
  period's roster (the owner, 2026-10-06). Recently closed periods are simply fetched
  again for a fixed number of periods (R6); an edit older than that is picked up only by
  `--refresh`, and the audit says when a finished season has not had one.
- **No change to how often the current period is fetched.** It is fetched on every run
  today and still is.
- **No dates.** Settled is never decided from today's date, from a `fetched_at`
  compared with a calendar, or from `latest == final`.

## Rabbit holes

- *Working out the clock time a period closes* → never needed: the evidence is ESPN's own
  period counter, not a time.
- *Comparing two captures of a period to see whether anything changed* → reads 2.3 MB
  payloads on every run, and "unchanged so far" is not "final".
- *Pruning the superseded captures* → nothing is deleted; each costs about 2.4 MB and dbt
  reads only the newest.
- *Finding edits in ESPN's activity log, or landing a re-check only when it differs* →
  both make ingestion interpret payloads; a fixed window does not.
- *A general "settled" framework for every endpoint* → one rule for rosters; #30 writes
  its own for boxscores.
- *Backfilling `source_status` into old sidecars* → they are not rewritten; a legacy rule
  covers them (R3).

## Requirements

### R1. Record the league's status with each roster capture

So that a capture carries its own evidence of when it was taken, in ESPN's terms.

- R1.1 WHEN a roster response is landed THE SYSTEM SHALL record in its sidecar a
  `source_status` object holding `latest_scoring_period` and `final_scoring_period`,
  copied from the `status` block of that same response.
- R1.2 IF the response has no `status` block, or its `latestScoringPeriod` is not an
  integer, THEN THE SYSTEM SHALL still land the capture, record
  `latest_scoring_period` as null, and log a warning naming the period.
- R1.3 THE SYSTEM SHALL write `source_status` only where the caller supplies it; the
  sidecar of every other endpoint keeps exactly the keys it has today.
- R1.4 THE SYSTEM SHALL treat a capture as committed by the existing check alone; the
  presence, absence or content of `source_status` never makes a capture uncommitted.

### R2. A period is settled only by evidence

- R2.1 THE SYSTEM SHALL treat scoring period P of a league-season as closed if and only
  if some committed roster capture of P, for that season and league, is evidence of a
  latest scoring period greater than P, and as settled if and only if some such capture
  is evidence of a latest scoring period greater than P plus the re-check window (R6).
- R2.2 WHERE a roster sidecar has a `source_status` key THE SYSTEM SHALL take its
  `latest_scoring_period` as the evidence when the value is an object and the counter an
  integer, and SHALL treat any other shape as no evidence, without raising.
- R2.3 WHEN a backfill runs without `--refresh` THE SYSTEM SHALL fetch every period from
  1 to the latest that exists which is not settled, and skip every period that is.
- R2.4 WHEN a backfill runs with `--refresh` THE SYSTEM SHALL fetch every period.
- R2.5 THE SYSTEM SHALL NOT use the status fetched by the current run to settle a
  period; that status only decides which periods exist.
- R2.6 THE SYSTEM SHALL decide what to fetch without reading any roster payload.
- R2.7 THE SYSTEM SHALL NOT let a capture of one league or season settle a period of
  another.

### R3. Captures made before this change

The 180 captures of 2026, and the two fixture captures, have no `source_status`.

- R3.1 WHERE a roster sidecar has no `source_status` key THE SYSTEM SHALL take as its
  evidence the `status.latestScoringPeriod` of a committed settings capture with the
  same season, league and `fetched_at`.
- R3.2 IF no such settings capture exists, or it has no integer `latestScoringPeriod`,
  THEN THE SYSTEM SHALL treat the roster capture as no evidence.
- R3.3 THE SYSTEM SHALL read a settings payload only for a `fetched_at` that a legacy
  roster capture of the same league-season carries.
- R3.4 IF a roster sidecar has a `source_status` key that is unusable (R2.2) THEN THE
  SYSTEM SHALL NOT fall back to R3.1 for that capture.

### R4. What cannot be shown final stays visible

- R4.1 WHEN a backfill finishes THE SYSTEM SHALL report the periods that exist (1 to the
  smaller of the run's latest and final period) and lie below the run's latest scoring
  period that are still not closed, and exit non-zero if there are any.
  (The owner, 2026-10-06: exit non-zero for now; revisit if it fails persistently in
  season.)
- R4.2 THE SYSTEM SHALL have the audit judge roster finality by the same function the
  fetch logic uses, reporting how many required periods are closed, which have no
  roster (error) and which have a roster but no capture showing them closed (warning).

### R6. Re-check recently closed periods

So that a commissioner's correction to a recent day reaches the warehouse.

- R6.1 THE SYSTEM SHALL use a re-check window of 7 scoring periods, held as one named
  constant.
- R6.2 WHILE a period is closed and not settled THE SYSTEM SHALL fetch it on every run;
  this is not a failure and does not affect the exit code.
- R6.3 THE SYSTEM SHALL have the audit report, as information, how many closed periods
  are still inside the re-check window.
- R6.4 WHEN a season is over (the newest settings capture's latest period is greater
  than its final period) THE SYSTEM SHALL have the audit warn of every period with no
  capture that is evidence of a latest period greater than the final period.

### R5. Tests

- R5.1 THE SYSTEM SHALL replace `test_roster_is_skipped_once_its_period_is_over` with
  tests of transitions: a period captured while current, then after it closed, then on
  repeated later runs.
- R5.2 THE SYSTEM SHALL have tests for a scheduler outage spanning several periods, for
  a status that lags the roster (recovery), for a legacy capture in both directions, and
  for a period fetched on each daily run until the window has passed and never after.

## Expected values

Measured on the real landing zone on 2026-10-06. The first four rows are read-only.

| Check | Expected | How to verify |
|---|---|---|
| Committed roster captures, 2026 | 180, one per period 1–180, all from run `20260926T162307Z`, none with `source_status` | `LandingZone.committed(source="espn", endpoint="roster")` |
| Periods closed, by R3.1 (evidence 186) | 180 of 180; 0 missing; 0 without evidence | the new evidence function over the real landing zone |
| Periods settled (186 > P + 7) | 178: periods 1–178. For 179 and 180 the evidence, 186, is not greater than the period plus 7 | the same |
| Periods the fetch logic would fetch, no `--refresh`, status latest 188 or more | 2 of 180: 179 and 180 | call the fetch decision for each period; no network |
| Audit roster line | `scoring periods 1-180, latest 188; 180 of 180 rosters captured after their period closed`, as today, plus information that 2 are inside the re-check window | `uv run front-office audit --season 2026` before and after |
| Audit season-close warning (R6.4) | none: every period has evidence 186 > 180 | the same |
| Each roster payload's own `status` (cross-check of R3.1, not used at run time) | latest 186, final 180 in all 180; the same-run settings capture says 186 | one-off script, results on #27 |
| Files changed under `dbt/` or `fixtures/` | none | `git diff --stat main` |
| Sidecars of non-roster endpoints written after the change | same key set as before | pytest |
