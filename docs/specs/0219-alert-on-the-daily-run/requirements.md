# Tell the owner when a daily run fails or a feed goes stale — requirements

Issue: #219 · Tier: M · Status: draft

## Problem

The daily run (specs 0217, 0218) runs on `mothership` every morning of the season and tells nobody
how it went. Several failures are designed to stop it and need a person: expired ESPN cookies
(`AuthExpired`, exit 1), a new tie where a ranking cuts (ADR 0107), a red dbt test, and a feed
that stops updating (ADR 0050). Worse, the most common one is quiet by design: a failed fetch fails
a non-blocking check and the run still ends `SUCCESS` (ADR 0129, 0217 *Amendments*; C6). Spec 0216
also accepted a home host's outages on the promise that a missed run is alerted (R1.3), and nothing on
the host can report that the host is down. Source freshness cannot help yet: its filters are DuckDB
SQL, so the BigQuery `daily` leaves it out (0217 R3.5), and `dbt source freshness` exits 0 for a feed
that is only at warn (C9). The first week of 2027 cannot be redone (#66, #69), so the alerts must work
before it.

## Goals

- The owner hears of every failed, cancelled or missed daily or id-map run, and of every stale daily
  feed, by email from healthchecks.io (ADR 0139), at $0.
- Each alert says which step failed, the line that explains it where the CLI printed one, and where
  to look; it never carries a credential, a member's data, a path or the league's id.
- A good run after a bad one says so.
- Source freshness runs in `daily` on BigQuery as on DuckDB, one declaration per feed.

## No-gos

Explicitly out of scope. Work that drifts here is escalated, not done.

- Creating the healthchecks.io account, its checks, its email integration or the ping key: the
  owner's (credentials), following the runbook. An agent never creates, copies or reads the key.
- Provisioning checks through healthchecks.io's management API (a second secret, an API key).
- Paging by SMS or phone, or any paid plan.
- Alerts for anything but the `daily` and `idmap` jobs: hand-launched asset materializations, the
  laptop's runs (unless given a key on purpose), CI.
- Changing what the CLI prints, or the 0217 allowlist (`cli.ALLOWLIST`).
- Rehearsing a skipped day, the January rollover and the bytes billed in season (#220).
- Running the unit tests on BigQuery in CI (#221).

## Rabbit holes

- A message assembled from dbt's or Dagster's error text → the body is built only from fixed-shape
  lines (R3.2, ADR 0141); a tie's message carries key values (C15), so dbt nodes are named, never
  quoted.
- healthchecks.io emails on a change of state only (C3): a second failure while the check is down
  sends no email → accepted: the owner is already acting on the first, and every run's report is
  in the check's log; the UP email ends it (R2.4).
- Warn-severity dbt tests that warn all season would hold the check down and hide the next real
  failure → WARN results are reported, never fail the ping (ADR 0140).
- Writing the BigQuery freshness SQL as a dispatched macro → dbt makes no project macro available in
  source YAML; `target.type` is, and was shown to render (C10, ADR 0143).
- A ping that cannot be sent raising inside the sensor, and relying on Dagster's cursor to retry →
  the sensor retries in-tick and then gives up without raising: an unsent success ping becomes a
  missed-run alert, which fails safe (R2.5).

## Requirements

### R1. A report per run, sent to healthchecks.io

When `daily` or `idmap` ends, its outcome reaches the owner.

- R1.1 WHEN a run of `daily` or `idmap` ends `SUCCESS`, `FAILURE` or `CANCELED` THE SYSTEM SHALL
  send one ping for it to `https://hc-ping.com/<ping-key>/<slug>`, with `<slug>` `front-office-daily`
  or `front-office-idmap`, and the run's report (R3) as its body.
- R1.2 THE SYSTEM SHALL send the ping to the `/fail` form of the URL IF the run did not end
  `SUCCESS`, or any check of the run failed with severity `ERROR` (R2.1), and to the plain URL
  otherwise.
- R1.3 THE SYSTEM SHALL send the ping from Dagster run-status sensors in the code location, which
  start `RUNNING` and monitor exactly the `daily` and `idmap` jobs.
- R1.4 IF no ping key is configured THEN THE SYSTEM SHALL send nothing and the sensor SHALL skip
  with a reason that says so, so the laptop and CI load the same definitions and stay silent.
- R1.5 THE SYSTEM SHALL read the ping key only from the file named by
  `FO_HEALTHCHECKS_PING_KEY_FILE`, in one module, and SHALL NOT write it, or a URL holding it, to
  a log line, an event, metadata, an exception or the report (ADR 0142).

### R2. What counts as a failure

- R2.1 THE SYSTEM SHALL treat as failures: a run that ended `FAILURE` or `CANCELED`; a failed
  `fetch_complete` check; a failed dbt test of severity error; and a failed freshness check of the
  `mlb` or `espn` feed. Each of these is an `ERROR` check or a failed step.
- R2.2 THE SYSTEM SHALL report, without failing the ping, every failed check of severity `WARN`:
  dbt tests configured `warn`, and the `idmap` feed's freshness.
- R2.3 WHEN no ping reaches a check by its cron time plus its grace time THE SYSTEM (healthchecks.io)
  SHALL email the owner that the check is down: the daily check's cron is `0 6 * 3-10 *` and the
  id map's `0 5 * 3-10 1`, both in `America/New_York`, each with a grace of 2 h 30 min (two hours of
  run limit, ADR 0134, and half an hour's margin), so a missed day is known by 08:30 ET, before
  0216 R1.2's 09:00.
- R2.4 WHEN a check that is down receives a plain ping THE SYSTEM (healthchecks.io) SHALL email
  that it is up: that email is "the run that succeeds after a failure says so".
- R2.5 IF a ping is not answered `200` THEN THE SYSTEM SHALL retry it up to three times in all,
  ten seconds' timeout each, then log `ping not sent: <slug> <outcome>` (no URL) and return without
  raising.

### R3. The report

- R3.1 THE SYSTEM SHALL write the report as plain text no longer than 10,000 bytes (what the
  alert email shows, C3): a first line `front-office <job>: FAILED | OK | OK with warnings`; the run
  id, start and end in New York time and the run's status; one line per failure (R2.1), then one
  per warning (R2.2), each naming the step or check; and a last section naming the runbook's
  *When an alert arrives* section and the run's page in the UI (`/runs/<run_id>` through the
  SSH tunnel). Past the limit, the lists end with `… and <n> more`.
- R3.2 THE SYSTEM SHALL build the report only from: job and check names, asset and step keys, the
  run's id, status and times, exit codes, freshness statuses and ages in hours, the unique ids
  and statuses of failed dbt nodes, exception class names, and those lines of a command's stderr
  tail that match the alert's own patterns (R3.3). It SHALL NOT include an exception's message,
  dbt's log, a path or a value read from a payload.
- R3.3 THE SYSTEM SHALL keep a stderr line in the report only if it fully matches one of the
  alert's patterns, a subset of the CLI's allowlist with no path and no league id in any of
  them: the expired-cookie and rejected-credentials lines, the fetch counts, the failed game pks
  and scoring periods, the HTTP give-up line rewritten without its URL (`<what>: <source>: gave up
  after <n> attempts (last failure: <x>)`), the transactions lines with a fixed text, the
  privacy-hit line and the upload's counts. Every other line is dropped, not marked.
- R3.4 WHEN the dbt build fails THE SYSTEM SHALL record on the step's failure the unique id and
  status of every node that ended `error` or `fail` in that invocation's `run_results.json`, and
  the report SHALL list them.

### R4. Source freshness on both warehouses

- R4.1 THE SYSTEM SHALL keep one declaration per feed in `_raw_feeds__sources.yml` whose
  `loaded_at_field` and season clause are chosen by `target.type`: BigQuery's
  `parse_timestamp('%Y%m%dT%H%M%SZ', fetched_at)` and `json_value`, and DuckDB's `strptime` and
  `json_extract_string` as now (ADR 0143, amending ADR 0050).
- R4.2 THE SYSTEM SHALL include `source_freshness` in `daily` for `FO_WAREHOUSE=bigquery` as for
  `duckdb` (replacing 0217 R3.5).
- R4.3 WHEN `source_freshness` runs THE SYSTEM SHALL emit one asset check per feed
  (`mlb_runs_fresh`, `espn_runs_fresh`, `idmap_runs_fresh`) from dbt's `sources.json`: passed when
  the feed's status is `pass`; else failed, with severity `ERROR` for `mlb` and `espn` and `WARN`
  for `idmap`, carrying the status and the age in hours as metadata.
- R4.4 IF `dbt source freshness` gives no `sources.json`, or a feed's status is `runtime error`,
  THEN THE SYSTEM SHALL fail the `source_freshness` asset. A stale feed alone SHALL NOT fail it.

### R5. Deployment and operation

- R5.1 THE SYSTEM SHALL mount the ping key file read-only into the code server's container only,
  from `~/secrets/healthchecks-ping-key` (0400), and set `FO_HEALTHCHECKS_PING_KEY_FILE` there.
- R5.2 THE SYSTEM SHALL describe in the runbook the two checks (slug, cron, time zone, grace) as
  the owner sets them up, and a section *When an alert arrives* with what each failure means and
  what to do.
- R5.3 THE SYSTEM SHALL state in AGENTS.md that the ping key is a credential under rule 3, and that
  the freshness filters branch on `target.type` instead of being rewritten by hand.

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| Cost | $0: two checks of the Hobbyist plan's 20 (C1) | the healthchecks.io account page |
| Expired cookies, forced once | one DOWN email for `front-office-daily`; the body names `espn_captures: fetch_complete` and holds `ESPN returned 401: cookies expired …`; the run ended `SUCCESS` | the email and the check's log, recorded on #219 |
| New tie, forced once | DOWN (or, if already down, a `/fail` in the log); the body names `front_office_dbt` and the model's unique id with `error`, and no key value | same |
| Red dbt test, forced once | the body names the test's unique id with `fail` | same |
| Stale feed, forced once | the body names `espn_runs_fresh` or `mlb_runs_fresh`, its status and age; the run ended `SUCCESS` | same |
| Missed run, forced once | DOWN email at the tick plus 2 h 30 min, with no run that day | the email's time |
| Recovery | the next good run gives one UP email | the email |
| Freshness on BigQuery | `dbt source freshness --target bq` exits 0 on a fresh morning; three feeds; on 2026-11-20 they read `pass` at 10.4 h, 10.4 h and 72.6 h (C11) | `source_freshness` in the next `daily` on `mothership` |
| Freshness on DuckDB | unchanged: on the CI fixtures `mlb_runs` and `espn_runs` `error`, `idmap_runs` `warn` (C12) | the same command on `--target ci` |
| Freshness's bill | three queries a run, each at BigQuery's 10 MB minimum (the scan is 2.2 MB, C11): about 30 MB a day, under 1 GB a month | `INFORMATION_SCHEMA.JOBS` for one run, recorded on #219 |
| Body size | under 10,000 bytes on every forced run | the check's log |
| What never leaves the host | no ping key, no `league_id=`, no path, no `ESPN_S2=`/`SWID=` value in any report sent | a search of every forced run's body as healthchecks.io stored it |
| The key stays out of the host's records | no ping key in any Dagster event, log line or sensor tick of the forced runs (Dagster's own log keeps `landed … -> <path>` lines by 0217's design, so paths are not searched for there) | a search of the instance's events and the containers' logs |
