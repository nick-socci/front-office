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
| `dbt_target/` | dbt's `target/` (`run_results.json`, the bytes billed) | |
| `secrets/.env`, `secrets/google-key.json` | the ESPN cookies, the run's Google key | 0400, in a 0700 directory |
| `config/front-office.env` | `FO_BQ_PROJECT=<the project>`: not secret, and not in the public repository | |
| `.config/containers/systemd/` | the three Quadlet units (`front-office-code`, `-daemon`, `-ui`), copied from `deploy/quadlet/` | |

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
The failed-fetch and stale-feed alerts are #219's.

## Run `daily` by hand

```bash
ssh mothership 'podman exec front-office-daemon dagster job launch -w /app/deploy/workspace.yaml -j daily'
```

`launch` queues the run for the daemon, so the instance's one-run-at-a-time limit applies (a second
`daily` waits for the first); the UI's Launchpad does the same. Do not use `dagster job execute`
against production: it would run beside the daemon and bypass the limit. To stop a run, use the UI's
Terminate: it reaches the code server, which ends the worker (ADR 0138).

## Deploy a commit

Not while a run is going: restarting the code server ends it. Check first (`dagster run
list` cannot tell you: it prints ids and jobs, no status):

```bash
ssh mothership
curl -s -H 'Content-Type: application/json' \
  -d '{"query":"{ runsOrError(filter: {statuses: [QUEUED, STARTING, STARTED, CANCELING]}) { ... on Runs { results { runId status } } } }"}' \
  http://127.0.0.1:3000/graphql; echo
```

`{"data":{"runsOrError":{"results":[]}}}` means none is. Then, in the same shell:

```bash
cd ~/src/front-office && git fetch origin && git checkout <commit>    # a "detached HEAD" is expected
sha=$(git rev-parse --short HEAD)
podman build -f deploy/Containerfile --build-arg GIT_COMMIT=$(git rev-parse HEAD) \
    -t localhost/front-office:$sha .          # always from the repository root
podman tag localhost/front-office:$sha localhost/front-office:current
cp deploy/quadlet/*.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user restart front-office-code front-office-daemon front-office-ui
journalctl --user -u front-office-code -f     # Ctrl-C at a new "Started Dagster code server" (about 15 s)
```

Then check the deploy, every time. **This is the step that shows the deploy happened**: a restart
after a missed `podman tag` comes back up on the old image and looks just like a deploy (2026-11-20).

```bash
for c in front-office-code front-office-daemon front-office-ui; do
  podman inspect $c --format "$c {{index .Config.Labels \"org.opencontainers.image.revision\"}}"; done
podman exec front-office-daemon dagster schedule list -w /app/deploy/workspace.yaml
```

Each container names the commit you checked out, and both schedules are `[RUNNING]` on their
crons. Before the code server's `Started` line, `schedule list` fails with "Could not reach user code
server … 127.0.0.1:4266 … Connection refused": wait and run it again. The landing zone and the
instance are volumes: a deploy touches neither. The first build on a host pulls the base image and
builds the locked dependencies; later builds reuse them while `uv.lock` is unchanged.

## Roll back

Older images stay, tagged with their short commit. Check that no run is going (as above), then pick
one from `podman images localhost/front-office`. If the units changed between that commit and the
running one (`git diff --stat <old> HEAD -- deploy/quadlet/`), the old image needs its own units: an
image from before ADR 0138 (`a40a20b`) does not work with the three-container units.

```bash
cd ~/src/front-office && git checkout <old>          # the clone names what runs
podman tag localhost/front-office:<old> localhost/front-office:current
cp deploy/quadlet/*.container ~/.config/containers/systemd/ && systemctl --user daemon-reload
systemctl --user restart front-office-code front-office-daemon front-office-ui
journalctl --user -u front-office-code -f            # Ctrl-C at a new "Started"
```

Then the same check as a deploy: each container names `<old>`. Rehearsed on 2026-11-20 by the
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
