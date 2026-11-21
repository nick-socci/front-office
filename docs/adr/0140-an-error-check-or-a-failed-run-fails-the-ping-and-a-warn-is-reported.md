# 0140. An ERROR check or a failed run fails the ping; a WARN is reported only

- Status: accepted
- Date: 2026-11-20
- Spec: [0219-alert-on-the-daily-run](../specs/0219-alert-on-the-daily-run/design.md) · Issue: #219

## Context

A ping is up or down (ADR 0139), and healthchecks.io emails only on a change. The run's failures
come in three shapes: a run that ended `FAILURE` or `CANCELED` (the dbt build, which carries a new
tie and a red error-severity test; the upload; a timeout); a failed `ERROR` check on a run that
ended `SUCCESS` (`fetch_complete`); and failed `WARN` checks (C6). Nine dbt tests are
warn-severity (C13). `dbt source freshness` exits 0 at warn (36 h) and 1 only at 7 days (C9).

## Decision drivers

- Every failure #219 lists reaches the owner.
- A known, lasting warning must not hold the check down, because while it is down a new failure
  sends no email.

## Considered options

1. **`ERROR` fails, `WARN` reports.** A run that is not `SUCCESS`, or any failed `ERROR` check,
   pings `/fail`. `WARN` failures are listed in a success ping's body. The `mlb` and `espn`
   freshness checks fail as `ERROR` at dbt's warn (36 h); the `idmap` one is a `WARN`.
2. **Every failed check fails the ping**, whatever its severity.
3. **Only a failed run fails the ping**, as Dagster's own failure sensors do.

## Decision

Chosen by the owner on 2026-11-20: **option 1**, as recommended. Option 3 misses expired cookies (C6). Option 2 lets one warn-severity
test that warns all season hold the check down, and so hides the next real failure. It also
fails every year's first runs on the id map, which is weekly and stale until the season's first
Monday, while its own healthchecks.io check already reports a missed id-map run.

## Consequences

- Good: the severity a test already declares decides whether it pages. Nothing new to configure.
- Bad / accepted cost: a warn-severity test that starts failing is seen only when someone reads a
  report. Making a test page means raising it to `error`, a change to the test.
- Follow-ups: none.
