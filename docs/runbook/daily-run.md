# The daily run on `mothership` — runbook

How to operate what spec 0218 deploys: Dagster's code server, daemon and UI as three containers under
the `front-office` user (ADRs 0133, 0138), the schedule (ADRs 0134, 0136), the run's Google identity (ADR 0135)
and the NAS's pull (ADR 0137). Each step was shown on the host during spec 0218's build (the evidence is on
#218); a command here that no one has run on the host says so.

Nothing in this file is a credential. The values live in `~/secrets` on the host, and an agent
never creates, copies, rotates or deletes one: the owner does, and says so on the issue.

## Layout on the host

Everything is under `/home/front-office` (mode 0700), as the `front-office` user (`ssh mothership`):

| Path | What | Mode |
|---|---|---|
| `src/front-office/` | a clone of the public repository, at the commit being built | |
| `data/raw/` | the production landing zone; `data/raw.lock` and `raw.upload.lock` sit beside it | |
| `dagster_home/` | Dagster's instance: SQLite run history | |
| `dashboard/` | the dashboard's extract (`extract.duckdb`), written by the code server and read by the dashboard; create it once with `mkdir -p ~/dashboard` | |
| `dbt_target/` | dbt's `target/` (`run_results.json`, the bytes billed) | |
| `secrets/.env`, `secrets/google-key.json`, `secrets/healthchecks-ping-key` | the ESPN cookies, the run's Google key, the healthchecks.io ping key | 0400, in a 0700 directory |
| `config/front-office.env` | `FO_BQ_PROJECT=<the project>`: not secret, and not in the public repository | |
| `.config/containers/systemd/` | the four Quadlet units (`front-office-code`, `-daemon`, `-ui`, `-dashboard`), copied from `deploy/quadlet/` | |

## See the schedule and the last run

```bash
ssh mothership 'systemctl --user status front-office-code front-office-daemon front-office-ui --no-pager'
ssh mothership 'podman exec front-office-daemon dagster schedule list -w /app/deploy/workspace.yaml'
ssh -L 3000:127.0.0.1:3000 mothership        # then http://localhost:3000 : runs, checks, lineage
```

Which container does what: the **code server** loads the code and is where every run executes (it holds
the credentials and the landing zone); the **daemon** holds the schedules and the run queue; the **UI**
shows and controls them. All three listen on the host's loopback only (4266, none, 3000).

A day's run is healthy when the run is `SUCCESS` **and** each fetch asset's `fetch_complete` check
passed: Dagster does not fail a run for a failed non-blocking check (ADR 0129, 0217 *Amendments*).
Each run's outcome is also emailed to the owner through healthchecks.io: see *Alerts* and
*When an alert arrives*.

## The dashboard

The fourth container, `front-office-dashboard`, serves the dashboard (spec 0232) from the same image.
It holds no credential and mounts one directory, `~/dashboard`, read-only: the extract the code server
writes after each good daily build. It has no `Network=host`; its port is published on the host's
loopback only (ADR 0146), and from inside it the host's loopback services (4266, 3000) are out of reach.

```bash
ssh -L 8501:127.0.0.1:8501 mothership        # then http://localhost:8501
ssh mothership 'systemctl --user status front-office-dashboard --no-pager'
ssh mothership "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8501/"     # 200
```

Out of season there is no daily extract, or the last one is old. Make one by hand with the code
server's own environment (it holds `FO_BQ_PROJECT` and the Google key; the dashboard never does):

```bash
ssh mothership
podman exec front-office-code sh -c 'front-office extract-marts --project "$FO_BQ_PROJECT" --out /dashboard/extract.duckdb'
```

Each page shows when the extract was built and from which commit. A **stale banner** means the
extract is older than the pages expect: the last daily run did not publish one. Read *When an alert
arrives* for that run (a failed dbt build publishes nothing, by design), then make one by hand once
the cause is fixed. Restarting the dashboard alone (`systemctl --user restart front-office-dashboard`)
touches no run and reads the extract again; it does not depend on the code server being up.

## Run `daily` by hand

```bash
ssh mothership 'podman exec front-office-daemon dagster job launch -w /app/deploy/workspace.yaml -j daily'
```

`launch` queues the run for the daemon, so the instance's one-run-at-a-time limit applies (a second
`daily` waits for the first); the UI's Launchpad does the same. Do not use `dagster job execute`
against production: it would run beside the daemon and bypass the limit. To stop a run, use the UI's
Terminate: it reaches the code server, which ends the worker (ADR 0138).

## Deploy a commit

Restarting the code server ends a run in flight, so the restart is guarded by a check that no run is
queued, starting, running or being cancelled. The check sits on the restart line, not before the
build: the build takes minutes, and the schedule (06:00 ET in season) or a person can start a run
meanwhile. (`dagster run list` cannot tell: it prints ids and jobs, no status.)

The code server's unit mounts `~/dashboard` read-write and the dashboard's read-only; it must exist
before the restart or the units do not start: run `mkdir -p ~/dashboard` once. The `cp` below copies
the fourth unit with the others, and `restart` starts a unit that is not running yet. Restarting the
dashboard alone touches no run, so it needs no `no_run_going`.

```bash
ssh mothership
no_run_going() {
  curl -s -H 'Content-Type: application/json' \
    -d '{"query":"{ runsOrError(filter: {statuses: [QUEUED, STARTING, STARTED, CANCELING]}) { ... on Runs { results { runId status } } } }"}' \
    http://127.0.0.1:3000/graphql | grep -q '"results":\[\]'
}
cd ~/src/front-office && git fetch origin && git checkout <commit>    # a "detached HEAD" is expected
sha=$(git rev-parse --short HEAD)
podman build -f deploy/Containerfile --build-arg GIT_COMMIT=$(git rev-parse HEAD) \
    -t localhost/front-office:$sha .          # always from the repository root
podman tag localhost/front-office:$sha localhost/front-office:current
cp deploy/quadlet/*.container ~/.config/containers/systemd/
systemctl --user daemon-reload
no_run_going && systemctl --user restart front-office-code front-office-daemon front-office-ui front-office-dashboard \
  || echo "NOT RESTARTED: a run is going (or the UI did not answer). Wait for it to end, then run this line again."
journalctl --user -u front-office-code -f     # Ctrl-C at a new "Started Dagster code server" (about 15 s)
```

If the restart line printed `NOT RESTARTED`, the old image still runs: the UI's Runs page shows the
run; once it has ended, run the `no_run_going && …` line again.

Then check the deploy, every time. **This is the step that shows the deploy happened**: a restart
after a missed `podman tag` comes back up on the old image and looks just like a deploy (2026-11-20).

```bash
for c in front-office-code front-office-daemon front-office-ui front-office-dashboard; do
  podman inspect $c --format "$c {{index .Config.Labels \"org.opencontainers.image.revision\"}}"; done
podman exec front-office-daemon dagster schedule list -w /app/deploy/workspace.yaml
```

Each container names the commit you checked out, and both schedules are `[RUNNING]` on their
crons. Before the code server's `Started` line, `schedule list` fails with "Could not reach user code
server … 127.0.0.1:4266 … Connection refused": wait and run it again. The landing zone and the
instance are volumes: a deploy touches neither. The first build on a host pulls the base image and
builds the locked dependencies; later builds reuse them while `uv.lock` is unchanged.

## Roll back

Older images stay, tagged with their short commit. Pick one from `podman images localhost/front-office`. If the units changed between that commit and the
running one (`git diff --stat <old> HEAD -- deploy/quadlet/`), the old image needs its own units: an
image from before ADR 0138 (`a40a20b`) does not work with the three-container units. An image from
before the dashboard (spec 0232) has no `streamlit`: rolling back past it, stop the dashboard and
remove its unit first, or it restarts forever on the old image:
`systemctl --user stop front-office-dashboard && rm ~/.config/containers/systemd/front-office-dashboard.container`
(then `daemon-reload`).

```bash
cd ~/src/front-office && git checkout <old>          # the clone names what runs
podman tag localhost/front-office:<old> localhost/front-office:current
cp deploy/quadlet/*.container ~/.config/containers/systemd/ && systemctl --user daemon-reload
no_run_going && systemctl --user restart front-office-code front-office-daemon front-office-ui front-office-dashboard \
  || echo "NOT RESTARTED: a run is going (or the UI did not answer). Wait for it to end, then run this line again."
journalctl --user -u front-office-code -f            # Ctrl-C at a new "Started"
```

`no_run_going` is the function defined in *Deploy a commit*; define it first in a new shell. Then
the same check as a deploy: each container names `<old>`. Rehearsed on 2026-11-20 by the
owner, from `b29c35a` to `942fb27` and back (#218).

## Rehearse a run at another time

`FO_DAILY_CRON`, when set, replaces the daily schedule's cron (the id map's has no override). The
schedule is defined in the code location, so the **code server** reads it; its unit already reads
`~/config/front-office.env`, so the rehearsal is a line in it. (A
systemd drop-in does not work: Podman 4.9's Quadlet ignores `.container.d` drop-ins, and a `[Service]
Environment=` would reach Podman, not the container: spec 0218 *Amendments*, 2026-11-17.)

```bash
cp ~/config/front-office.env /tmp/fo-config.bak
echo "FO_DAILY_CRON=$(TZ=America/New_York date -d '+3 minutes' +'%-M %-H') * * *" >> ~/config/front-office.env
systemctl --user restart front-office-code front-office-daemon   # read at start; ends a run in flight
# ... the run starts at that minute. Remove the line AT ONCE, or it fires every day at that minute:
cp /tmp/fo-config.bak ~/config/front-office.env          # the running code server keeps the rehearsal cron
# until it restarts: restart it once no run is going, then check the real cron is back
systemctl --user restart front-office-code
podman exec front-office-daemon dagster schedule list -w /app/deploy/workspace.yaml
```

Never restart the code server while a run is going: it would end the run. Until it restarts, the
schedule list still shows the rehearsal cron (the file is read at start): that is how to tell the line
is still in force. A cron that fires
every minute queues a run a minute behind a running one (one at a time, ADR 0134); the first rehearsal
(2026-11-17) used one to show that, and cancelled what it queued (`terminateRun` in the UI's GraphQL).

## Replace the Google key (each off-season, ADR 0124; the owner's)

The owner creates the new key for the run's service account, puts it at
`~/secrets/google-key.json.new` (mode 0400), moves it over `google-key.json`, and restarts the code server
(`systemctl --user restart front-office-code`; a replaced file is a new inode, which a bind mount
does not follow). Launch `daily` by hand and see the upload and the build succeed. Only then does
the owner delete the old key.

## Replace the ESPN cookies (when `fetch_complete` fails with "cookies expired")

The owner edits `~/secrets/.env` (`ESPN_S2`, `SWID`), writing in place or moving a new file over it,
then restarts the code server, then launches `daily`. Never paste a value into an issue, a log or a chat.

## Alerts (healthchecks.io; the owner sets it up)

When a `daily` or `idmap` run ends, a sensor in the code server sends one ping to healthchecks.io
with a short report as its body: `/fail` when the run failed or was cancelled, or an `ERROR` check
failed, and a plain ping otherwise (spec 0219, ADRs 0139 to 0142). healthchecks.io emails the owner
when a check goes **down** (a `/fail`, or no ping by the cron time plus the grace) and when it comes
back **up**. While a check is down, a later failure sends no new email; every report is in the
check's log (its last 100 pings).

The owner's setup, once, in healthchecks.io (Hobbyist plan, $0):

| Check (slug) | Cron | Time zone | Grace |
|---|---|---|---|
| `front-office-daily` | `0 6 * 3-10 *` | `America/New_York` | 2 h 30 min |
| `front-office-idmap` | `0 5 * 3-10 1` | `America/New_York` | 2 h 30 min |

The crons are `DAILY_CRON` and `IDMAP_CRON` in `orchestration/front_office_pipeline/schedules.py`:
change both together. The email integration is the owner's address; a push to a phone is another
healthchecks.io integration, set there, with nothing to change here.

The project's **ping key** (in the project's settings in healthchecks.io) goes in `~/secrets/healthchecks-ping-key`
on the host, one line, mode 0400, written by the owner; restart the code server after (`systemctl
--user restart front-office-code`, once no run is going: see *Deploy a commit*). It is a credential:
whoever holds it can mark the checks up and hide a failure. Never paste it into an issue, a log or
a chat. Without the file the sensors skip with "no FO_HEALTHCHECKS_PING_KEY_FILE: nothing sent",
and the next morning's missing ping becomes a "down" email: the alerting fails safe.

Rehearsals on the laptop use a second healthchecks.io project with the same two slugs, and its own
ping key in a file the laptop's `FO_HEALTHCHECKS_PING_KEY_FILE` names, so they never touch the
production checks.

See the sensors and their last ticks:

```bash
ssh mothership 'podman exec front-office-daemon dagster sensor list -w /app/deploy/workspace.yaml'
```

## When an alert arrives

The email holds the report: its first line says `FAILED` or `OK`; then the run's id, times and
status, one line per failure and per warning, and a pointer here. It never holds a path, the
league's id or an error message (ADR 0141): the run's page in the UI has those
(`ssh -L 3000:127.0.0.1:3000 mothership`, then `/runs/<run id>`).

| The report says | What it means | What to do |
|---|---|---|
| `espn_captures: fetch_complete` with `ESPN returned 401: cookies expired …` | the ESPN login expired; MLB still landed and BigQuery was built | the owner refreshes the cookies (*Replace the ESPN cookies*), then launches `daily` by hand |
| another `…: fetch_complete`, with counts or `failed game_pks: […]` | a fetch landed what it could; the rest is fetched on the next run | nothing if the next run is clean; if it repeats, read the step's log in the UI |
| `front_office_dbt (Failure)` and a `model.…: error` line | a model failed, often a new tie where a ranking cuts (ADR 0107) | read the node's error in the UI; open an issue: a tie is a question about the data, not a retry |
| `front_office_dbt (Failure)` and a `test.…: fail` line | a dbt test went red | read the test's failing rows in the UI; open an issue |
| `raw_in_warehouse (Failure)` | the upload stopped (for example `privacy hit(s). Nothing was sent.`) | read the step in the UI; a privacy hit is the owner's to resolve, never by editing the check |
| `source_freshness: mlb_runs_fresh` or `espn_runs_fresh`, with a status and an age | the feed's run marker is over 36 hours old although the run ran | read that feed's fetch step in the same run: it landed no schedule or settings |
| `run ended FAILURE` or `CANCELED`, with no step | the run was stopped: cancelled, or ended by the two-hour limit | if no one cancelled it, read the run in the UI for the step that hung |
| a "down" email with no report (the check is late) | no run happened: the host, the containers or the network | `systemctl --user status front-office-code front-office-daemon front-office-ui`; then the host itself |
| `WARNING …` lines in an `OK with warnings` report | a warn-severity test, or the id map's age; nothing pages for these | read them when convenient; a warning that should page is raised to `error` in its test |
| a sensor tick failing with `PingKeyUnreadable` (in `dagster sensor list` or the UI) | the key file is missing or not one line | the owner checks `~/secrets/healthchecks-ping-key` |

A good run after any of these sends the "up" email.

## Stop and start the schedule

Nothing to do for the off-season: both schedules have cron month ranges, March to October
(ADR 0134). To stop one before then: `dagster schedule stop <name> -w /app/deploy/workspace.yaml`
in the daemon's container, and `dagster schedule start` to resume. A schedule is `RUNNING` on a new
instance without a click; a stopped one stays stopped across restarts, as it is in the instance.

## A pull caught mid-capture

`rsync` copies a capture's two files one after the other, so a pull (or a Hyper Backup run) can see a
capture directory with `meta.json` and no `payload.json` yet. The landing zone calls that not
committed ("not exactly payload.json and meta.json": `LandingZone.check`), the loader and the capture
views skip it, and the next pull adds the other file; `rsync` writes each file whole or not at all. So
nothing needs doing, except not running `front-office repair` (without `--dry-run`) on a copy while a
pull is going: it would quarantine the half capture, which the next pull then fetches again.

## Is the second copy current? (the NAS's pull and the backup)

The pull writes `last_pull_ok` beside the NAS's copy (`/volume1/FrontOffice/last_pull_ok`) after each
good run. It is a DSM Task Scheduler task that runs **hourly, on the hour** (since 2026-11-19 12:00
ET; it ran daily at 00:00 before then). Read the file's age on the NAS: more than about two hours is
a failed pull, and the gap before a second device is open (ADR 0137). `mothership`'s SSH log shows
each pull as a login for `front-office` from the NAS's tailnet address
(`sudo journalctl -u ssh | grep 'Accepted publickey for front-office'`, as `ubuntu`). The external drive's copy is the NAS's Hyper Backup job, daily at 03:00 and including
the `FrontOffice` share: read DSM's log for the last success. The pull and the daily job are
intervals, not bounds.

## Restore captures to `mothership`

`mothership` starts nothing on the tailnet, and the NAS's key is read-only, so a restore goes through
the laptop: pull the NAS's copy to the laptop, then push it to the host with the owner's key:

```bash
NAS_COPY=/path/to/the/laptops/copy/of/the/NAS/raw        # the path itself, no angle brackets
rsync --archive --ignore-existing --exclude '*.tmp-*' "$NAS_COPY"/ mothership:data/raw/
```

Then check the host's copy: it must report nothing to move.

```bash
ssh mothership 'podman run --rm -v ~/data:/data localhost/front-office:current \
    front-office repair --raw-root /data/raw --dry-run --deep'
```

To restore from the external drive itself (the NAS's own copy lost), use Hyper Backup's Backup
Explorer on the task, pick a version, and copy `FrontOffice/raw` to a scratch folder on the NAS,
then compare before trusting it: `sha256sum` each restored `payload.json` and `meta.json` against
the host's copy of the same path. Exercised on 2026-11-19 (#218): 28 of 28 files from one
endpoint were identical. A full restore of the share was not tried.

## Pull a copy to the laptop

```bash
deploy/pull_landing.sh mothership:data/raw/ data/raw      # adds; never deletes; not while a build reads it
```

The laptop's fetch commands are never run against production: the host is the one writer
(spec 0216, R2.1). `data/raw` on the laptop is a copy.

`data/raw` is left out of the laptop's own home backup, because the NAS holds the copy. That
backup is not in this repository: `~/.local/bin/backup` (a restic wrapper: `backup run`, `backup
status`), the hourly `backup.timer` in `~/.config/systemd/user/`, and the exclusion list
`~/.config/restic/excludes`, which names `…/fantasy-baseball-analytics/data/raw` (added 2026-11-19).
On a new laptop, the exclusion has to be added again. Check it with `backup ls latest
<repo>/data/raw`, which should list nothing.

## If ESPN refuses the host's address

ADR 0126's fallback: the laptop on a timer. Stop the host's schedules first, so there is one writer,
pull the host's landing zone to the laptop, run the fetch there, and push the new captures back
with the command above. (Not rehearsed: spec 0218 R7.1 is where it would first be needed.)
