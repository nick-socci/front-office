# Where the daily run runs — requirements

Issue: #216 · Tier: L · Status: draft

## Problem

Nothing runs Front Office on a schedule. Every capture so far was fetched by hand on the owner's
laptop, and the landing zone lives there (ADR 0119). Sub-project 4 must make the pipeline run
every day of the 2027 season. #66 and #69 depend on its first week, which cannot be redone. Three
choices have to be made before anything can be scheduled, and the roadmap's answer ("Dagster
locally, Cloud Scheduler + Cloud Run in production") answers none of them:

- **Which machine runs it.** The laptop is on most of the time but is a laptop (owner,
  2026-11-04), and it suspends when idle (C11). Cloud Run has no durable disk. A free e2-micro
  has 1 GB of RAM (C5), and Dagster's daemon alone holds 505 MB over this project's graph (C8).
- **Where captures live.** Whole captures hold members' data. Putting them in the cloud reverses
  ADR 0054's premise that they "have so far lived only on the owner's machine and the NAS".
- **What Dagster is**: the description of the pipeline, its scheduler, or both.

The data has to be current **by morning, before lineups are set** (owner, 2026-11-04).

## Goals

- One host, chosen with its monthly cost and failure modes stated from the billing catalog and
  from measurements, runs the daily pipeline without the laptop.
- Captures have one home and one writer, and the laptop keeps a full copy for development.
- Dagster's role is settled, so that #217 writes the pipeline once.
- The credentials' home and the backup are settled by the owner, so that #218 only carries
  them out.
- The chosen host is shown to run one real daily run end to end (fetch, upload, BigQuery
  build), within its memory, before #217 starts.

## No-gos

- Writing the Dagster definitions (#217), provisioning the schedule (#218), alerting (#219).
  This spec's spike runs the CLI by hand on the chosen host.
- Intraday or "live" refresh: a later issue (owner, 2026-11-03).
- Moving any endpoint's data, or any field, to BigQuery that does not go up today.
- Changing what a capture is (ADR 0014), the landing zone's layout, or the loader (spec 0140),
  except where `LandingZone` gains a second backend under option b, if that is chosen.
- Running the BigQuery unit tests in CI (#221).
- The dashboard's host (sub-project 5).

## Rabbit holes

- Hosting Dagster's full deployment (Postgres, separate code servers, a run queue) → the
  default instance with SQLite storage, one code location. C8 is measured on exactly that.
- Making the laptop and the host write one landing zone together → one writer (R2.1). The laptop
  pulls a copy, and the writer lock stays a local lock.
- Measuring every option on real hardware → only the chosen one is measured (task 4). The
  options lost on figures already in the ledger, or on criteria no measurement would change.
- Containerizing the dbt DuckDB build for the host → R4 decides whether the host builds DuckDB
  at all, before anything is packaged.

## Requirements

### R1. A host that runs without the laptop

- R1.1 THE SYSTEM SHALL run the daily pipeline on one host chosen in ADR 0121, with the laptop
  asleep, off or away.
- R1.2 WHILE the 2027 season is being played THE SYSTEM SHALL complete each day's run by 09:00
  in the owner's timezone (America/New_York). A game not final when the run fetches arrives on
  the next run.
- R1.3 IF a day's run does not happen (host down, power, network) THEN THE SYSTEM SHALL fetch on
  the next run whatever the settle windows still need (ADRs 0018, 0019), with nothing fetched
  twice that is already settled.
- R1.4 THE SYSTEM SHALL cost no more than 1 USD a month in GCP charges beyond what BigQuery
  already bills, stated per service from the billing catalog (C1 to C4).

### R2. One home for captures

- R2.1 THE SYSTEM SHALL have exactly one writer of the production landing zone: the host.
- R2.2 THE SYSTEM SHALL keep a full copy of the landing zone on the laptop for development
  builds, refreshed from the host, and never written by the laptop's fetch commands while the
  host is the writer.
- R2.3 IF whole captures would be stored outside the owner's home THEN THE SYSTEM SHALL have an
  accepted ADR amending ADR 0054 before any capture leaves.
- R2.4 THE SYSTEM SHALL have room for the 2027 season's captures on the host (C9, C10), and say
  when the next season would exceed it.

### R3. Dagster's role

- R3.1 THE SYSTEM SHALL describe the daily pipeline once, in Dagster, and run it in production
  from those definitions (ADR 0122).
- R3.2 THE SYSTEM SHALL fit Dagster's processes, a run, and the host's own services in the
  host's memory, as measured on the host (task 4).

### R4. The warehouse built each day

- R4.1 THE SYSTEM SHALL build the BigQuery warehouse after each daily upload (ADR 0123).
- R4.2 THE SYSTEM SHALL keep DuckDB buildable on the laptop from its copy of the landing zone,
  with the result `scripts/compare_bigquery.py` expects.

### R5. Credentials and backup

- R5.1 THE SYSTEM SHALL keep the ESPN cookies and the BigQuery credential only where ADR 0124
  says, readable by the run and nothing else on the host, and never in an image, a log line or
  the repository (rule 3).
- R5.2 THE SYSTEM SHALL give the BigQuery credential no more access than a real upload and a
  suffixed build use, as task 4 finds them: no role on another project, and no access to the
  owner's other Google data.
- R5.3 THE SYSTEM SHALL copy every committed capture to a second device in the home, the NAS's
  external backup drive, on the NAS backup job's schedule, without needing the laptop (ADR
  0125). A capture landed since the job's last run is on the NAS alone. The job's schedule bounds
  that gap.

### R6. The spike

- R6.1 WHEN the host is chosen THE SYSTEM SHALL run one daily run on it by hand, on the
  production landing zone moved there: the CLI's fetch for MLB and ESPN, a real `front-office
  upload`, and `dbt build --target bq` into suffixed datasets. The run shows a capture it landed
  in BigQuery's raw tables and in the build. It records peak memory, wall time and bytes billed
  on #216.
- R6.2 IF the run's peak memory with Dagster's daemon and UI added (C8) exceeds the host's free
  memory THEN THE SYSTEM SHALL stop and bring ADR 0122 back to the owner before #217.
- R6.3 THE SYSTEM SHALL treat C8 as a lower bound: it was measured on a manifest with the unit
  tests and dbt functions removed. #217 measures again with its real definitions.

- R6.4 *(added 2026-11-07)* WHILE the host is not yet chosen THE SYSTEM SHALL measure Dagster's
  daemon and UI, a fetch of MLB data, an `upload --dry-run` and a `_216` build on a VM that holds
  no league data, with images that build for `linux/amd64` and `linux/arm64`. This does not
  satisfy R6.1, and R2.3 is not triggered: nothing from ESPN reaches the VM.

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| GCP charges for the chosen host | 0.00 USD a month in 2027 (option d); at most 1 USD under any option chosen | the billing catalog rows C1 to C4; the billing report after #218 |
| BigQuery bytes billed by one daily build | about 16.16 GB now (C12), no more than 20 GB in task 4; at most about 27 GB by the end of 2027 (C16), so at most about 814 GB a month, under the free 1 TiB | `run_results.json` of task 4's build; #220 records it again in the rehearsal |
| Landing zone after the 2027 season | about 12 GB plus about 8 GB (C9, C10) | `du -sh` on the host after the season |
| Peak memory of a daily run with Dagster | daemon 505 MB + UI 349 MB (C8) + the run (task 4) under the host's free memory | task 4's measurement, recorded on #216 |
| A missed day | the next run fetches what is unsettled, and nothing settled | task 4 run twice with one day between; the second run's capture count |
