# Tell the owner when a daily run fails or a feed goes stale — design

Issue: #219 · Requirements: [requirements.md](requirements.md) · Tasks: [tasks.md](tasks.md)

## Overview

healthchecks.io watches the run from outside: it holds one check per job, each with the job's cron,
New York time and a grace of 2 h 30 min, and emails the owner when a check goes down or comes back
up (ADR 0139). Inside the code location, run-status sensors fire when a `daily` or `idmap` run ends.
They read the run's own events (failed steps, and each check's outcome and severity), write a short
plain-text report from fixed-shape parts only (ADR 0141), and send it as the body of one ping. A run
that failed, or that has an `ERROR` check that failed, pings `/fail`. Anything else pings success,
with any `WARN` failures listed in the body (ADR 0140). A run that never happens sends no ping,
and healthchecks.io reports it once the grace has passed. A good run after a bad one pings success,
and healthchecks.io sends the UP email. Source freshness becomes three asset checks, one per feed,
read from dbt's `sources.json`. Its filters choose their SQL by `target.type`, so it runs on BigQuery
too (ADR 0143). The ping key is a file in `~/secrets`, mounted into the code server alone (ADR 0142).

A **sensor** (a new Dagster concept here) is a function the daemon asks the code server to evaluate
every 30 seconds. A *run-status* sensor is handed each run of the jobs it monitors once the run
reaches the status it watches, and keeps a cursor so that each run is handed over once.

```mermaid
sequenceDiagram
  autonumber
  participant D as daemon
  participant C as code server (runs, sensors)
  participant H as healthchecks.io
  participant O as owner (email)
  D->>C: 06:00 ET tick: launch daily
  C->>C: run: fetch → upload → dbt build → source_freshness
  D->>C: evaluate sensors (every 30 s)
  C->>C: read the run's step failures and check results; build the report
  alt failed, cancelled, or an ERROR check failed
    C->>H: POST <ping-key>/front-office-daily/fail (report)
    H->>O: DOWN (only if it was up), with the report
  else good, maybe with WARN results
    C->>H: POST <ping-key>/front-office-daily (report)
    H->>O: UP (only if it was down)
  end
  Note over H,O: no ping by 08:30 ET (tick + grace): DOWN, "missed"
```

## Claims ledger

All run or read on 2026-11-20.

| # | Claim | Query (or script) | Result | Run on |
|---|---|---|---|---|
| C1 | healthchecks.io's Hobbyist plan is free and is enough for two checks. | https://healthchecks.io/pricing/ | "$0 / month", "Monitor 20 jobs", "100 log entries per job"; SMS and phone credits only on Business plans | 2026-11-20 |
| C2 | A ping can be addressed by a project's ping key and a check's slug, can carry a report, and says whether it was recorded. | https://healthchecks.io/docs/http_api/ | `https://hc-ping.com/<ping-key>/<slug>` and `…/<slug>/fail`; POST bodies stored up to the first 100 kB; success is `200 OK` with body `OK`; an unknown slug is `404`; more than 5 pings a minute may be rate-limited (`429`) | 2026-11-20 |
| C3 | The alert email carries the last ping's body, and is sent on a change of state, down or up. | `templates/emails/alert-body-html.html` in github.com/healthchecks/healthchecks (master) | `{% if ping and ping.has_body %}` → "Last Ping Body", "Showing the last 10000 bytes"; `{% if flip.new_status == "down" %}` … is DOWN, else … is UP, "The downtime lasted"; the FAQ: alerts are "one-shot" | 2026-11-20 |
| C4 | A check can expect pings on a cron in a time zone, with a grace time. | https://healthchecks.io/docs/configuring_checks/ | "Cron Expression, Server's Time Zone, and Grace Time"; grace is "how long to wait before sending an alert for a late check" | 2026-11-20 |
| C5 | ntfy.sh's free topics are protected only by their name. | https://docs.ntfy.sh/ , https://ntfy.sh/#pricing | "topic names are public"; without sign-up "the topic is essentially a password"; reserved topics from $5 a month | 2026-11-20 |
| C6 | A failed fetch leaves the run `SUCCESS`; only the check says so. Today's real run had no failed check. | 0217 *Amendments* (2026-11-16); GraphQL `logsForRun` on `mothership` for run `f535efa8` (the 06:00 ET `daily` of 2026-11-20), paged through every event | 1,854 events; 430 `AssetCheckEvaluationEvent`, all `success: true`; no `ExecutionStepFailureEvent`; run `SUCCESS` | 2026-11-20 |
| C7 | A sensor can read, from the instance, each check's outcome, severity and metadata, and each failed step's key, exception class and metadata. | scratchpad `proto.py`: an ephemeral instance, a job of a fetch with a failed non-blocking `ERROR` check and an asset raising `Failure(metadata=…)`; `instance.get_records_for_run(run_id, of_type=ASSET_CHECK_EVALUATION / STEP_FAILURE)` | run `FAILURE`; `fetch fetch_complete False AssetCheckSeverity.ERROR {'stderr_tail': …}`; `step failure build Failure … {'failed_nodes': …}` | 2026-11-20 |
| C8 | Sensors are evaluated in the code server, so the ping key need be mounted there only. | Dagster 1.13.30: `_daemon/sensor.py:884` calls `code_location.get_sensor_execution_data(…)`; `_grpc/server.py:1247,1257` serve `SyncExternalSensorExecution` / `ExternalSensorExecution` | the daemon asks; the code server runs the function | 2026-11-20 |
| C9 | `dbt source freshness` exits 0 when a feed is only at warn, 1 at error. | `dbt source freshness --target ci --select source:raw_feeds.idmap_runs` and `…mlb_runs` on `dbt/ci.duckdb` | `idmap_runs` WARN, rc 0; `mlb_runs` ERROR STALE, rc 1 | 2026-11-20 |
| C10 | `target` renders in source YAML, in `loaded_at_field` and in `freshness.filter`, per target. | a scratch copy of `dbt/` with `{{ … target.type … }}` in both keys; `dbt parse --target ci` and `--target bq`; read `manifest.json` | ci: `strptime(…)`, filter `… = 'duckdb'`; bq: `parse_timestamp(…)`, filter `… = 'bigquery'` | 2026-11-20 |
| C11 | The BigQuery form of all three declarations works through dbt, and costs little. | the scratch copy with `{% if target.type == 'bigquery' %}parse_timestamp('%Y%m%dT%H%M%SZ', fetched_at){% else %}strptime(…){% endif %}` and `json_value`/`json_extract_string` by the same test; `dbt source freshness --target bq --select source:raw_feeds`; the same SQL by hand with `bq query --dry_run` | rc 0; `mlb_runs` pass 2026-11-20T11:00:33Z (10.4 h), `espn_runs` pass 11:00:48Z (10.4 h), `idmap_runs` pass 2026-11-17T20:45:22Z (72.6 h), as the hand query; dry run "upper bound of 2208185 bytes" | 2026-11-20 |
| C12 | The DuckDB form is unchanged by the branch. | the same copy, `--target ci` | rc 1; `mlb_runs` error, `espn_runs` error, `idmap_runs` warn, max 2026-04-30T16:00Z: as the unmodified file gave | 2026-11-20 |
| C13 | Nine dbt tests are warn-severity. | `grep -rn severity dbt/models dbt/tests` less `error` | 8 singular tests `config(severity='warn')` and 1 generic test in `_intermediate__models.yml:791` | 2026-11-20 |
| C14 | A bad cookie can be forced without touching `.env`. | `espn/client.py:68`: `load_dotenv(dotenv_path)`, whose `override` defaults to `False` | a variable already in the environment wins over `.env` | 2026-11-20 |
| C15 | A tie's error message carries key values. | `dbt/macros/latest_by_entity.sql:44-55`, `fo_tie_message` | `concat('<node>: rows tie for place ', …, ' in (', <each partition key cast to text>, ')')` | 2026-11-20 |
| C16 | A `landed … -> <path>` line names the league. | `find data/raw/espn/settings -maxdepth 3`; `fixtures/landing/espn/roster/season=2026/league_id=111111/…` | real paths: `espn/<endpoint>/season=<y>/league_id=<n>/…` | 2026-11-20 |
| C17 | dagster-dbt can run a command without raising, and hand back its artifacts. | `inspect.signature(DbtCliResource.cli)`; `dir(DbtCliInvocation)` | `cli(args, *, raise_on_error: bool = True, …)`; `get_artifact` present | 2026-11-20 |

## Alternatives considered

| | A — healthchecks.io (chosen) | B — email from Dagster over SMTP | C — ntfy.sh push | D — a GitHub issue |
|---|---|---|---|---|
| Price | $0 (C1) | $0 | $0 | $0 |
| Reports a missed run (host or daemon down) | yes: no ping by the grace (C4) | no | no | no |
| Says when it recovers | yes, UP email (C3) | only if written | only if written | only if written |
| Secret on the host | a ping key: can mark a check up or down, nothing else | a Gmail app password: can send mail as the owner | the topic name: anyone with it reads every alert (C5) | a token that writes issues |
| Where the report goes | healthchecks.io's log (100 entries) and the owner's email | the owner's email | ntfy's public server | a public repository |
| Repeats while failing | no: one email per change of state | every run | every run | every run |

**A — healthchecks.io.** It is the only option that reports the failure nothing on the host can
report: the host, the daemon or the sensor never running. It also gives the recovery email for
free, and its key can do the least harm. Chosen by the owner on 2026-11-20 (ADR 0139). The cost is
that a second failure while a check is down sends no email (R2.4's rabbit hole).

**B — Dagster's `make_email_on_run_failure_sensor` over SMTP.** It is built in, and it emails on
every failed run. But it is blind to a run that never starts, and to the `SUCCESS` run with a
failed fetch (C6) unless it is rewritten anyway. Its password can send mail as the owner.

**C — ntfy.sh.** Push to a phone, free. A topic name is the only protection on the free server (C5),
and it still cannot see a missed run. healthchecks.io can deliver to ntfy itself if the owner
later wants a push: that is a setting in its UI, not this design.

**D — a GitHub issue per failure.** It sits beside the work, but the repository is public: every
failure, and its report, would be published. It also needs a write token on the host and sees no
missed run.

**Freshness on BigQuery — branch in YAML (chosen) vs. a model vs. two files.** A singular test or
a model of feed ages would be portable through the `fo_*` macros, but would replace dbt's freshness
and ADR 0050's declarations. Two source files enabled per target duplicate every threshold. A
`target.type` branch keeps one declaration per feed, and was shown on both warehouses (C10 to C12).

## Decisions

| ADR | Decision | Status |
|---|---|---|
| [0139](../../adr/0139-healthchecks-io-is-told-of-every-run-and-alerts-on-a-missed-one.md) | healthchecks.io gets one ping per run from a sensor, and alerts on a missed one | accepted |
| [0140](../../adr/0140-an-error-check-or-a-failed-run-fails-the-ping-and-a-warn-is-reported.md) | an `ERROR` check or a failed run fails the ping; a `WARN` is reported only | accepted |
| [0141](../../adr/0141-the-alert-carries-fixed-shape-parts-only.md) | the report carries fixed-shape parts only: no path, no league id, no error message | accepted |
| [0142](../../adr/0142-the-ping-key-is-a-file-mounted-into-the-code-server-only.md) | the ping key is a file in `~/secrets`, mounted into the code server only | accepted |
| [0143](../../adr/0143-freshness-filters-choose-their-sql-by-target-type-and-each-feed-is-a-check.md) | freshness filters choose their SQL by `target.type`; each feed is a check; freshness runs in `daily` on both warehouses | accepted |

## Detailed design

### `orchestration/front_office_pipeline/alerts.py` (new)

- `SLUGS = {"daily": "front-office-daily", "idmap": "front-office-idmap"}`.
- `ping_key(environ=None) -> str | None`: reads `FO_HEALTHCHECKS_PING_KEY_FILE`; `None` when the
  variable is unset or empty. A named file that is missing, empty or not one line of `[A-Za-z0-9_-]`
  raises `PingKeyUnreadable`, whose message names the variable and never the content. This is the
  only function that opens the file (R1.5).
- `Outcome`: the run's id, job, status, start and end; `failures` and `warnings`, each a list of
  `Item(kind, name, lines)`. `kind` is `step`, `check` or `run`.
- `outcome(instance, run) -> Outcome`, built from `instance.get_records_for_run(run_id, of_type=…)`
  (C7):
  - `STEP_FAILURE`: the step key, the error's `cls_name`, and the `failed_nodes` and
    `stderr_tail` metadata when present. The message is not read.
  - `ASSET_CHECK_EVALUATION` with `passed=False`: the asset key and check name. `stderr_tail`,
    `exit_code`, `status` and `age_hours` metadata are kept. `ERROR` goes to `failures`, `WARN` to
    `warnings`.
  - A run `FAILURE` or `CANCELED` with no step failure (a run monitor's timeout, a cancel) is one
    `run` failure naming the status.
- `failed(outcome) -> bool`: the status is not `SUCCESS`, or `failures` is not empty (R1.2, R2.1).
- `report(outcome) -> str` (R3.1). Lines come only from `alert_lines(stderr_tail)` (R3.3) and from
  the fields above. Truncated to 10,000 bytes at a line boundary, inside an item if need be (one failed dbt step can
  name hundreds of nodes); the cut adds `… and <n> more`, counting the lines left out.
- `ALERT_PATTERNS`: anchored regexes, each one narrower than an entry of `cli.ALLOWLIST` and
  free of `_PATH`. They are the expired-cookie line, `credentials rejected`, `(boxscores|rosters|matchup
  days): fetched=…`, `failed game_pks: […]`, `failed scoring periods: […]`, `unproven scoring
  periods: […]`, the give-up line (matched with groups and rewritten as `<what>: <source>: gave up
  after <n> attempts (last failure: <x>)`: its URL is dropped, so no URL a caller might print ever
  leaves), the two fixed-text transactions lines, `\d+ privacy hit\(s\)\.
  Nothing was sent\.`, and the upload's `\w+\.\w+: \d+ committed, …`. `alert_lines` keeps a line of
  the (already filtered) tail that fully matches one of them, and drops the rest, `<line withheld>`
  included.
- `send(slug, body, failed, key, *, opener=urllib.request.urlopen) -> str`: POSTs
  `text/plain; charset=utf-8` to `https://hc-ping.com/{key}/{slug}` (plus `/fail`), with a ten-second
  timeout and three tries in all (R2.5). It returns `sent`, `not sent: HTTP <code>` or `not sent:
  <exception class>`, and never raises. The URL is built inside it and never leaves it.

### Sensors (`orchestration/front_office_pipeline/sensors.py`, new)

Three `@run_status_sensor`s, for `SUCCESS`, `FAILURE` and `CANCELED`, each with
`monitored_jobs=[daily, idmap]` and `default_status=RUNNING` (Dagster's default is `STOPPED`). They
share one body: without a key, `SkipReason("no FO_HEALTHCHECKS_PING_KEY_FILE: nothing sent")`
(R1.4); else build the outcome, the report, `send`, and log `ping <slug>: <sent|fail> <result>`.
`build_defs()` adds them to `Definitions(sensors=…)`. They need the job definitions, so the jobs
move to module level or are passed in.

### The dbt step (`dbt_assets.py`)

`front_office_dbt` streams as now. Around the stream, a `DagsterDbtCliRuntimeError` is caught. The
step then reads `invocation.get_artifact("run_results.json")` (C17) and raises
`Failure(description="dbt build failed", metadata={"failed_nodes": "<unique_id>: <status>" per
line})` from the error. A node is listed when its status is `error` or `fail`. A failing
error-severity test therefore appears twice in the run: once as its own failed `ERROR` check, as
now, and once among the failed nodes. The report lists it once, by unique id (R3.4).

### `source_freshness` (`assets.py`)

The asset becomes a `@multi_asset` with three check specs (R4.3). It runs
`dbt.cli(["source", "freshness", "--target", …], raise_on_error=False)`, waits, and reads
`get_artifact("sources.json")`. With no artifact, or a `runtime error` result, it raises (R4.4).
Otherwise it yields the materialization and one `AssetCheckResult` per feed:
`passed = status == "pass"`, severity `ERROR` for `mlb_runs` and `espn_runs` and `WARN` for
`idmap_runs`, metadata `status` and `age_hours` (rounded to 0.1). `build_defs()` no longer removes
`source_freshness` from `daily` on BigQuery (R4.2).

Why `mlb` and `espn` fail at dbt's *warn* (36 h) and not only at its error (7 days): a daily feed 36
hours old has missed a run, and C9 shows the exit code would hide it for five more days. `idmap` is
weekly. Its own check in healthchecks.io already reports a missed id-map run, and it is always
stale in the season's first days before the first Monday, so it is a warning only.

### `_raw_feeds__sources.yml`

`loaded_at_field` becomes `{% if target.type == 'bigquery' %}parse_timestamp('%Y%m%dT%H%M%SZ',
fetched_at){% else %}strptime(fetched_at, '%Y%m%dT%H%M%SZ'){% endif %}`. The four
`json_extract_string(partitions, '$.season')` become `{{ 'json_value' if target.type == 'bigquery'
else 'json_extract_string' }}(partitions, '$.season')`. Note the argument order, which differs
between the two functions. The header comment loses "Still dormant" and "is to be rewritten …
for BigQuery", and says why the branch is in YAML. The subquery's bare `raw.captures` resolves on
BigQuery to the job's project, which is `FO_BQ_PROJECT` (C11).

### Deployment

- `front-office-code.container`: `Volume=%h/secrets/healthchecks-ping-key:/run/secrets/healthchecks-ping-key:ro`
  and `Environment=FO_HEALTHCHECKS_PING_KEY_FILE=/run/secrets/healthchecks-ping-key`. The daemon
  and UI units get neither (R5.1).
- Runbook: *Alerts* (the account and project, the two checks with slug, cron, `America/New_York` and
  grace 2 h 30 min, the email integration, the key file and its mode) and *When an alert arrives*:
  one row per failure kind, with what it means and the remedy. For expired cookies, refresh
  `~/secrets/.env`, the owner's step. For a tie or a red test, read the node in the UI and open an
  issue. For a stale feed, read the step that should have landed it. For a missed run, `systemctl
  --user status` and the host. For `PingKeyUnreadable` in the sensor's ticks, check the file.
- AGENTS.md rule 3 names the ping key, read only by `alerts.ping_key`. The *Project shape*
  freshness sentence becomes "branch on `target.type`" (R5.3).

### What is not changed

The fetch assets, `fetch_complete`, `cli.ALLOWLIST`, the schedules and `dagster.yaml`.

## Test strategy

| Requirement | Test | Catches |
|---|---|---|
| R1.1, R1.2, R2.1, R2.2 | `test_alerts.py`: runs on an ephemeral instance (as C7) of a fetch with a failed `ERROR` check, a failed `WARN` check, a raising step, a clean run, and a cancelled run; `outcome` and `failed` for each | a `SUCCESS` run with a failed fetch pinging success; a WARN failing the ping; a cancel unreported |
| R1.3 | `test_definitions.py`: three sensors, `RUNNING`, monitoring exactly `daily` and `idmap` | a sensor that starts stopped, or watches the wrong job |
| R1.4 | the sensor body with no variable returns a `SkipReason`, and `send` is not called | the laptop or CI pinging production |
| R1.5 | a key planted in a temp file; every log line, the report, the outcome and `PingKeyUnreadable`'s message searched for it; a key file with two lines raises without its content | the key in a log, a body or a traceback |
| R2.5 | `send` with a fake opener: 200, 404, 429 then 200, three timeouts; the tries, the result strings, never an exception, never the URL in the result | a sensor tick that crashes; a URL logged |
| R3.1 | `report` of a run whose one dbt step names 500 failed nodes is ≤ 10,000 bytes, keeps the step's line and the first nodes, and ends `… and <n> more` with the right count | an email cut mid-line with the explanation lost |
| R3.2, R3.3 | every `ALERT_PATTERNS` entry is matched by a sample line that `cli.filter_line` keeps; the give-up line comes out without its URL, whatever the URL holds; none matches a `landed … -> …` line, the `no settings captured … league …` line, `another writer holds …`, or a line with `league_id=`; a tail with those lines yields only the allowed ones | a path or the league's id reaching healthchecks.io |
| R3.4 | a `run_results.json` fixture with `success`, `error`, `fail`, `skipped`, `warn` nodes → `failed_nodes` holds exactly the `error` and `fail` ones | a skipped node blamed, a failed one missing |
| R4.1 | `dbt parse --target ci` and `--target bq` (a dummy project name) in a test: the manifest's `loaded_at_field` is `strptime(…)` and `parse_timestamp('%Y…', fetched_at)` respectively | a branch that renders DuckDB SQL on BigQuery |
| R4.2 | `daily` holds `source_freshness` on both warehouses (replaces 0217's R3.5 test) | freshness left out of production |
| R4.3, R4.4 | `sources.json` fixtures: all pass; `espn_runs` warn; `mlb_runs` error; `idmap_runs` warn; one `runtime error`; none → checks and severities as R4.3; the asset raises only in the last two | a stale feed failing the asset (and skipping nothing, but hiding the check); a runtime error passing |
| R5.1 | `test_deploy_files.py`: the key file is mounted `:ro` in the code unit only, and the variable set there only | the key in the daemon's or UI's container |
| all | the five forced failures and the recovery on the real channel (tasks 9, 10) | anything the fakes got wrong about healthchecks.io or Dagster's sensor daemon |

## Risks

- healthchecks.io is down or gone: no email for a failure, and maybe a false DOWN later. Low
  likelihood; accepted. The UI still shows every run.
- A ping lost on a good day gives a false "missed" email at 08:30. Rare; it fails safe.
- While a check is down, later failures send no email (C3). Accepted (R2.4's rabbit hole). The log
  holds each report.
- The rate limit is 5 pings a minute (C2). Two jobs and one ping per run stay well under it.
- The 10,000-byte email view (C3) rests on the template at `master`, not on a documented promise.
  R3.1 keeps bodies under it either way.
- Freshness runs only after a good build (it depends on every dbt asset). On a day the build fails,
  freshness is skipped, and the failure already alerts.

## Open questions

- That a run-status sensor's cursor hands each run over exactly once across a daemon restart, so a
  restart neither repeats a ping nor drops one — Dagster's design says so. Task 10 shows it with a
  restart between a run and its ping. Should a ping repeat, healthchecks.io takes it without harm.
- How a cancel and a run monitor's timeout look in the events (step failure or none) — tasks 3
  and 9.

## Review log

| Source | Finding | Resolution |
|---|---|---|
| design-review | F1 (P1): the expected value forbade paths and `league_id=` in Dagster's events, which the 0217 allowlist logs by design | Fixed: paths and the league id are searched for in the reports sent; the key in the events and logs too (Expected values, task 9) |
| design-review | F2 (P1): the give-up line carries a URL unchecked | Fixed: the line is rewritten without its URL (R3.3, *Detailed design*, ADR 0141), and a test holds it whatever the URL |
| design-review | F3 (P2): truncating at an item boundary cannot keep one 500-node item under 10,000 bytes | Fixed: the cut falls at a line boundary inside an item, with the count of lines left out |

## Amendments

- **2026-11-21 (pre-PR review F1): a dbt test that is not an asset check is read from its
  observation.** dagster-dbt 0.29.30 turns a singular test with several parents into an
  `AssetObservation` per parent instead of an asset check (`dbt_cli_event.py`,
  `_to_observation_events`: "a singular test with multiple dependencies"); the observation's
  metadata holds the test's `unique_id` and `status`. Three of the nine warn-severity tests are such
  tests (the review read the real manifest), so R2.2 missed them: a `warn` from one of them left
  the report saying `OK`. `outcome` now also reads `ASSET_OBSERVATION` events: one per test
  `unique_id` (an observation repeats per parent), `warn` to warnings, `fail` or `error` to
  failures unless a step's `failed_nodes` already names it; only a `unique_id` of the fixed shape
  is kept. Within the goals and no-gos; R2.2 now reads "every failed check or observed dbt test of
  severity `WARN`".
- **2026-11-21 (pre-PR review F2): a missing `sources.json` is a `FileNotFoundError`.**
  `DbtCliInvocation.get_artifact` reads the file directly and raises when it is absent, so R4.4's
  fixed failure is raised from that exception rather than from a `None`.
