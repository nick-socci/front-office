# Run the daily pipeline on a schedule — requirements

Issue: #218 · Tier: M · Status: draft

## Problem

`daily` (spec 0217) runs once, by hand, from `dagster job execute`. Nothing starts it each
morning, nothing keeps Dagster's daemon up after a crash or a reboot, and the production files
are still where the 0216 spike left them: the landing zone, the ESPN `.env` and the Google key
under `ubuntu`'s home on `mothership`, the `front-office` account that ADR 0126 names as the
run's one unix user owning nothing (C4, C6). ADR 0126 decided the host and 0217 built the
pipeline. This spec turns them into a deployment that runs every day of the 2027 season without
the owner, and puts a second copy of every capture in the home. The first week of 2027 cannot be
redone (#66, #69), and the schedule has to be right before it, because its first real test is
the season itself.

## Goals

- One schedule starts `daily` each morning of the 2027 season, in time for R1.2 of spec 0216
  (09:00 ET), and starts nothing outside it.
- Dagster's daemon and UI run as the `front-office` user, restart by themselves, hold a memory
  limit, and run one `daily` at a time.
- The production landing zone, the ESPN cookies and the Google key live under `front-office`
  and nowhere else on the host; the run has its own Google identity.
- Every capture reaches the NAS, then its external drive, and the laptop's copy can be refreshed
  from the host; one restore is proven.
- Everything about the deployment that can live in the repository does (image, units, Dagster's
  instance files, the pull script); what cannot (credentials, DSM, the tailnet's access rules)
  is a named step for the owner.

## No-gos

Explicitly out of scope. Work that drifts here is escalated, not done.

- Alerts on a failed run or a stale feed, and BigQuery source freshness (#219).
- Rehearsing a skipped day, the January rollover and the bytes billed (#220), and the first
  in-season run of rosters and teams from this address (R7.1 states what this spec can and cannot
  show).
- Running the BigQuery unit tests in CI (#221).
- The home server, a secret manager, or a second host. ADR 0126 and 0124 say when those come.
- Changing what `daily` runs. This spec adds schedules and deployment files; it does not add,
  remove or reorder assets.
- Automatic deploys from CI. A deploy is a person (or an agent they ask) pulling and building on
  the host.

## Rabbit holes

- Hosting Dagster "properly" (Postgres, a separate code server per location, a Kubernetes or
  Docker launcher) → the default instance on SQLite, one code location, runs as subprocesses of
  the daemon: what 0216 C8 and 0217's task 7 measured.
- Making the landing zone resilient to the host's loss beyond ADR 0126 (snapshots, a second
  off-site copy) → the NAS pull and the NAS's own backup are the copies; option 4 of ADR 0125
  stays open.
- A guard in the CLI that refuses to fetch into a copy of the landing zone → raised as an open
  question, not built here (no-go: this spec does not change ingestion).
- Encrypting the pull beyond what SSH over the tailnet gives → no.

## Requirements

### R1. The schedule

`daily` is started by Dagster's daemon, from a schedule written in the repository.

- R1.1 THE SYSTEM SHALL start `daily` at 06:00 America/New_York each day from March 1 to October
  31, from a schedule defined in the code location, that is running as soon as an instance
  first loads the code, with no click in the UI (ADR 0134).
- R1.2 WHILE the date is outside March 1 to October 31 THE SYSTEM SHALL start no `daily` run
  from a schedule. A person can still run it by hand.
- R1.3 IF the daemon was down when ticks were due THEN THE SYSTEM SHALL, on its return, start one
  run for them, not one per tick (ADR 0134, C2): a run fetches whatever is unsettled (ADRs 0018,
  0019), so one run catches up every missed day.
- R1.4 WHILE a `daily` run is in progress THE SYSTEM SHALL start no second one, whether from the
  schedule or from the UI (the writer lock, 0217 C7, would fail the second fetch).
- R1.5 IF a run is still going 2 hours after it started THEN THE SYSTEM SHALL end it and mark it
  failed, so a stuck fetch cannot hold the next day's run (ADR 0134). A run takes about 10
  minutes (C9).
- R1.6 THE SYSTEM SHALL refresh the id map on its own weekly schedule, Mondays at 05:00
  America/New_York, from March 1 to October 31, and not in `daily` (ADR 0136).
- R1.7 WHERE a rehearsal needs a run at another time THE SYSTEM SHALL take the cron expression
  from `FO_DAILY_CRON` when it is set, and from the code otherwise (design: *The schedule*).

### R2. The host runs it

- R2.1 THE SYSTEM SHALL run Dagster's daemon and UI as two rootless Podman containers of one image,
  as the `front-office` user, started by that user's systemd, restarted after a crash and
  after the host reboots, with no login session open (ADR 0133).
- R2.2 THE SYSTEM SHALL give each container a memory limit, such that the measured peak of a
  `daily` run with the daemon and UI (1,395 MB, C9) is under the limit by at least a half
  (limits are measured in task 6 and recorded in ADR 0133).
- R2.3 THE SYSTEM SHALL add no listener on a non-loopback address of `mothership` (ADR 0126's
  controls). The UI listens on the container's loopback and is reached by an SSH tunnel.
- R2.4 THE SYSTEM SHALL keep every credential out of the image, its history and its build
  context, and mount the credential files read-only. Dagster SHALL be started from a directory
  that holds no `.env` (0217 *Amendments*, 2026-11-16).
- R2.5 THE SYSTEM SHALL build the image from the repository at a stated commit, say which commit
  is running, and keep the landing zone and Dagster's instance on volumes that a rebuild does not
  touch.
- R2.6 IF the host reboots THEN THE SYSTEM SHALL start both containers again and have the schedule
  running, without a person logging in.

### R3. Credentials and identity

- R3.1 THE SYSTEM SHALL hold the ESPN `.env` and the Google key only under `front-office`'s home,
  owner-readable (0400 files, 0700 directories), and the copies under `ubuntu`'s home SHALL be
  gone once the move is checked (rule 3; ADR 0126).
- R3.2 THE SYSTEM SHALL run as its own Google service account, named for the daily run, with
  BigQuery User on the project and `WRITER` on exactly `raw` and the five model datasets, and
  no other role (ADR 0135). The spike account (`fo-spike216`) is retired once the run no longer
  uses it.
- R3.3 THE SYSTEM SHALL say how often the key is replaced (each off-season, ADR 0124) and how, as
  a step in the runbook.
- R3.4 THE SYSTEM SHALL show no cookie value, key field or member's name in Dagster's instance, a
  run's log, the image's history or the units (scan, as 0217's task 5).

### R4. One home for captures

- R4.1 THE SYSTEM SHALL move the production landing zone to `front-office`'s home, make
  `front-office` its writer, merge into it the captures the laptop landed since the 0216 move (C5),
  and show the result equal to the union of both (counts per endpoint, and `front-office repair
  --dry-run --deep` moving nothing) before the source is removed (ADR 0126, R2.1 of 0216).
- R4.2 THE SYSTEM SHALL let the laptop refresh its copy from the host with one documented command
  that adds and never deletes (0216 R2.2), and the laptop's hourly home backup SHALL exclude
  `data/raw` (ADR 0125's follow-up).

### R5. The second copy

- R5.1 THE SYSTEM SHALL have the NAS pull the landing zone from `mothership` every hour, by
  `rsync` over SSH on the tailnet, adding and never deleting, leaving out `*.tmp-*` (ADR 0137).
- R5.2 THE SYSTEM SHALL give the NAS's key the power to read the landing zone and nothing else on
  `mothership`; and `mothership` SHALL start no connection to the NAS or any tailnet device
  (ADR 0126).
- R5.3 THE SYSTEM SHALL have the NAS's Hyper Backup job carry the pulled folder to the external
  drive, and prove it by restoring one capture from the drive, byte for byte (ADR 0125's follow-up).
- R5.4 THE SYSTEM SHALL state the time before a capture is on a second device (one hour, the pull's
  interval) and before it is on the drive (that hour plus up to 24 hours) as holding only while the
  pull and the backup job succeed, and SHALL have each job's last success checked: the pull's by
  a file the script writes after a good run, the backup's by DSM's log, in the runbook.
- R5.5 THE SYSTEM SHALL confirm that `mothership`'s boot volume is encrypted at rest (ADR 0126's
  follow-up), and record how.

### R6. Operating it

- R6.1 THE SYSTEM SHALL document, in one runbook, how to see the schedule and the last run, run
  `daily` by hand, deploy a new commit, roll back, replace the key and the ESPN cookies, stop the
  schedule for an off-season, restore from the NAS, and fall back to the laptop if ESPN refuses
  the host (ADR 0126).

### R7. Proof over time (the issue's "Done when", and what only the season shows)

- R7.1 THE SYSTEM SHALL, on its first in-season runs, record whether `espn_captures` lands teams
  and rosters from this address, and whether a settings capture taken at 06:00 ET names the day's
  scoring period (the hour is chosen to follow ESPN's rollover, which no capture we hold shows). This
  cannot be shown before the season (C10): the task that covers it ends as awaiting the check, with
  the exact command and the expected values posted on the issue.
- R7.2 THE SYSTEM SHALL have started `daily` on its own on three consecutive days, each run
  green (`RUN_SUCCESS`, every `fetch_complete` passed), recorded on #218. A rehearsal before the
  season, with `FO_DAILY_CRON` set to `0 6 * * *` in December, shows it with the real daemon and
  the real files; the first three days of March show it with the real schedule (awaiting the check).
  Whether the rehearsal alone satisfies the issue's "Done when" is the owner's to say at review.
- R7.3 THE SYSTEM SHALL show the monthly cost on the billing report: a month's BigQuery charge from
  the daily build, against 0216's expectation (about 16 GB a build, under the free 1 TiB), and no
  other GCP charge from this deployment (R1.4 of 0216). The report for the first full month with
  daily runs is awaited.

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| Schedule's ticks across 2027 | the first is 2027-03-01 06:00 EST; the first after the clocks change is 2027-03-14 06:00 EDT (the change is at 02:00 that day); the last is 2027-10-31 06:00 EDT; none from 2027-11-01 through 2028-02-29 | a unit test over the schedule's cron and timezone (`croniter`), run on the laptop and in the image |
| Schedule state on a new instance | `RUNNING` | `dagster schedule list` in the container, on `mothership` |
| A missed stretch | daemon stopped across 3 ticks, then started: 1 run launched, with the daemon's log line "has no partition set, so not trying to catch up" | the rehearsal of task 6, with `FO_DAILY_CRON` set to a minute |
| A second run while one runs | the second is queued, not started | task 6: launch `daily` from the UI during a run |
| A run over its limit | ended and marked failed | a test with a 60-second limit on a run that sleeps |
| Daemon and UI plus one real `daily` | each container's peak under its limit (R2.2) and none killed; the summed peak recorded beside 1,395 MB (C9) | task 6, the measurement as 0217's task 7 (`measure.sh`) |
| One `daily` run through the daemon, by the rehearsal | `RUN_SUCCESS`; the BigQuery build bills about 16 GB (C12 of 0216), at most 20 GB; wall time at most 15 minutes | `run_results.json`, the run's events, on `mothership` |
| Landing zone after the move | 44,463 captures (the host's 44,444 and the laptop's 19, C5), plus any landed since, equal on both sides; `repair --dry-run --deep`: 0 items | `LandingZone.iter_landed` on both; the command |
| The NAS's copy | equal to the host's after a pull, by capture count and by `rsync -n --itemize-changes` listing nothing | the pull's dry run, on the NAS |
| A restore from the external drive | the restored capture's `payload.json` and `meta.json` have the sha256 of the host's | task 8 |
| Three green days on their own | three consecutive `RUN_SUCCESS` runs, started by the schedule (not by hand), each with every `fetch_complete` passed | Dagster's run history on `mothership`, December rehearsal; again in March (awaiting) |
| The monthly cost | the month's BigQuery charge under the free tier, nothing else billed | the Cloud Billing report for the first full month of daily runs (awaiting) |
| Secrets | 0 hits for the cookie names' values, the key's `private_key_id`, a GUID outside Dagster's own uuid4 ids, or a `FORBIDDEN_KEYS` member in the instance directory, the image history and the units | the scan of 0217's task 5, on `mothership` |
| Listeners on `mothership` | those of C17 and no more | `ss -tlnp`, and the UI from the laptop's tailnet address refused |
