# The daily run on `mothership` — runbook

How to operate what spec 0218 deploys: Dagster's daemon and UI as two containers under the
`front-office` user (ADR 0133), the schedule (ADRs 0134, 0136), the run's Google identity (ADR 0135)
and the NAS's pull (ADR 0137). **Draft**: finished after the production run has shown each step
(spec 0218, tasks 4 and 9). A command here that no one has run on the host says so.

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
| `.config/containers/systemd/` | the two Quadlet units, copied from `deploy/quadlet/` | |

## See the schedule and the last run

```bash
ssh mothership 'systemctl --user status front-office-daemon front-office-ui --no-pager'
ssh mothership 'podman exec front-office-daemon dagster schedule list -w /app/deploy/workspace.yaml'
ssh -L 3000:127.0.0.1:3000 mothership        # then http://localhost:3000 : runs, checks, lineage
```

A day's run is healthy when the run is `SUCCESS` **and** each fetch asset's `fetch_complete` check
passed: Dagster does not fail a run for a failed non-blocking check (ADR 0129, 0217 *Amendments*).
The failed-fetch and stale-feed alerts are #219's.

## Run `daily` by hand

```bash
ssh mothership 'podman exec front-office-daemon dagster job launch -w /app/deploy/workspace.yaml -j daily'
```

`launch` queues the run for the daemon, so the instance's one-run-at-a-time limit applies (a second
`daily` waits for the first). Do not use `dagster job execute` against production: it would run
beside the daemon and bypass the limit.

## Deploy a commit

Not while a run is going (the UI's Runs page, or `dagster run list`): restarting the daemon ends it.

```bash
ssh mothership
cd ~/src/front-office && git fetch origin && git checkout <commit>
sha=$(git rev-parse --short HEAD)
podman build -f deploy/Containerfile --build-arg GIT_COMMIT=$(git rev-parse HEAD) \
    -t localhost/front-office:$sha .          # always from the repository root
podman tag localhost/front-office:$sha localhost/front-office:current
cp deploy/quadlet/*.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user restart front-office-daemon front-office-ui
podman inspect front-office-daemon --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

The last line prints the running commit. The landing zone and the instance are volumes: a deploy
touches neither. The first build on a host pulls the base image and builds the locked dependencies.

## Roll back

Older images stay. `podman images localhost/front-office` lists them; re-tag one as `current` and
restart both units, as above.

## Rehearse a run at another time

A drop-in sets the cron for the daemon only, so the production unit is not edited:

```bash
mkdir -p ~/.config/systemd/user/front-office-daemon.service.d
printf '[Service]\nEnvironment=FO_DAILY_CRON=*/5 * * * *\n' \
    > ~/.config/systemd/user/front-office-daemon.service.d/rehearsal.conf
systemctl --user daemon-reload && systemctl --user restart front-office-daemon
# ... watch the run ...
rm ~/.config/systemd/user/front-office-daemon.service.d/rehearsal.conf
systemctl --user daemon-reload && systemctl --user restart front-office-daemon
podman exec front-office-daemon dagster schedule list -w /app/deploy/workspace.yaml   # the real cron again
```

(Not yet run on the host: task 6 does it, and corrects this if the drop-in has to differ.)

## Replace the Google key (each off-season, ADR 0124; the owner's)

The owner creates the new key for the run's service account, puts it at
`~/secrets/google-key.json.new` (mode 0400), moves it over `google-key.json`, and restarts the daemon
(`systemctl --user restart front-office-daemon`; a replaced file is a new inode, which a bind mount
does not follow). Launch `daily` by hand and see the upload and the build succeed. Only then does
the owner delete the old key.

## Replace the ESPN cookies (when `fetch_complete` fails with "cookies expired")

The owner edits `~/secrets/.env` (`ESPN_S2`, `SWID`), writing in place or moving a new file over it,
then restarts the daemon, then launches `daily`. Never paste a value into an issue, a log or a chat.

## Stop and start the schedule

Nothing to do for the off-season: both schedules have cron month ranges, March to October
(ADR 0134). To stop one before then: `dagster schedule stop <name> -w /app/deploy/workspace.yaml`
in the daemon's container, and `dagster schedule start` to resume. A schedule is `RUNNING` on a new
instance without a click; a stopped one stays stopped across restarts, as it is in the instance.

## Is the second copy current? (the NAS's pull and the backup)

The pull writes `last_pull_ok` beside the NAS's copy after each good run. On the NAS, read its
age; more than a couple of hours is a failed pull and the gap before a second device is open
(ADR 0137). The external drive's copy is the NAS's Hyper Backup job at 03:00: read DSM's log for the
last success. The hourly pull and the daily job are intervals, not bounds.

## Restore captures to `mothership`

`mothership` starts nothing on the tailnet, and the NAS's key is read-only, so a restore goes through
the laptop: pull the NAS's copy to the laptop, then push it to the host with the owner's key:

```bash
rsync --archive --ignore-existing --exclude '*.tmp-*' <NAS copy>/ mothership:data/raw/
```

Then `front-office repair --dry-run --deep --raw-root` on the host's copy must report nothing to
move. (Not yet exercised: task 8 restores one capture from the external drive.)

## Pull a copy to the laptop

```bash
deploy/pull_landing.sh mothership:data/raw/ data/raw      # adds; never deletes; not while a build reads it
```

The laptop's fetch commands are never run against production: the host is the one writer
(spec 0216, R2.1). `data/raw` on the laptop is a copy.

## If ESPN refuses the host's address

ADR 0126's fallback: the laptop on a timer. Stop the host's schedules first, so there is one writer,
pull the host's landing zone to the laptop, run the fetch there, and push the new captures back
with the command above. (Not rehearsed: spec 0218 R7.1 is where it would first be needed.)
