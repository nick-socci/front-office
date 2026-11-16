# 0129. A failed fetch fails a check, and the run goes on

- Status: accepted
- Date: 2026-11-15
- Spec: [0217-dagster-daily-pipeline](../specs/0217-dagster-daily-pipeline/design.md) · Issue: #217

## Context

`backfill espn` exits 1 on expired cookies (`AuthExpired`, nothing landed after it) and on failed
periods, transactions or the pro schedule (the rest landed). `backfill mlb` exits 1 after landing
what it could. No command has a distinct code for an expired login (spec C8). Every capture is
published by one rename (ADR 0014), so what landed is whole, and a build on a landing zone where one
feed is a day behind is the same state as a day the feed lagged. Dagster skips every asset
downstream of one that raises. The data must be current by 09:00 (spec 0216 R1.2).

## Decision drivers

- An ESPN failure must not also leave BigQuery without that morning's MLB games.
- A failure is read by #219 without parsing logs.
- No CLI change.

## Considered options

1. **A fetch succeeds if it ran to the end and fails a non-blocking asset check** with the exit code
   and stderr tail; upload and build still run; the check reports the failure.
2. **Stop at the first failure**: a fetch that exits 1 raises, and everything after is skipped.
3. **Stop only on `AuthExpired`**, which needs a distinct exit code from the CLI.

## Decision

Chosen by the owner on 2026-11-15: **option 1**, as recommended.

Option 2 leaves BigQuery stale for both feeds after one expired cookie, and the next run's catch-up
(0216 R1.3) would do the work anyway. Option 3 needs a CLI change this spec's no-gos keep out.

## Consequences

- Good: a failed ESPN login costs ESPN's data for the day, not MLB's.
- Bad / accepted cost: BigQuery is built on a partly current landing zone on such a day, and a mart
  can combine fresh MLB with a stale ESPN roster until the next run. The failed check says so.
- Bad / accepted cost: `upload` and the dbt build run even when a fetch failed; a failure of those
  two still stops what follows.
- Follow-ups: #219 alerts on a failed `fetch_complete`. If a distinct exit code for `AuthExpired` is
  wanted, that is a CLI issue.
