# Run the daily pipeline on a schedule — tasks

Issue: #218 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #218 during the build, and this file is not edited to show it.

Credentials, the Google account, the tailnet's rules and DSM are the owner's (AGENTS.md): the
tasks that touch them say so, and an agent posts the exact command and stops.

1. Add the schedules: `orchestration/front_office_pipeline/schedules.py` with `DAILY_CRON`,
   `IDMAP_CRON`, `America/New_York`, `default_status=RUNNING` and the `FO_DAILY_CRON` override, a
   job `idmap` for `idmap_capture`, and both added to `Definitions`. The tests first, as the design's
   table says: the ticks across 2027, the default status, the targets, and `daily`'s selection
   unchanged — `impl` — R1.1, R1.2, R1.6, R1.7
   - Verify: `uv run pytest orchestration`; the ticks test fails when `DAILY_CRON` is `0 6 * * *`
     and when the timezone is UTC; `dagster definitions validate -m front_office_pipeline` for both
     `FO_WAREHOUSE` values; the gates.
2. Add `deploy/dagster.yaml` and `deploy/workspace.yaml`, with a test that loads the instance file
   through Dagster's own config and asserts its limits (one concurrent run, run monitoring on with a
   7,200-second run limit), a test that neither schedule has a partition set, and a test on a
   scratch instance that a run past a 60-second limit ends failed — `impl` — R1.3, R1.4, R1.5
   - Verify: the tests fail when a limit is removed from the file; the sleeping run is `FAILURE`.
3. Write `deploy/Containerfile`, the root `.containerignore`, the two Quadlet `.container` units
   (`deploy/quadlet/`) and `deploy/pull_landing.sh`, with the static tests of the design's table for
   R2.4 and the generator's dry run (C19) over the units, and build the image on `mothership` as
   `front-office` with `podman build -f deploy/Containerfile -t <tag> .` from the root. Start the UI container with no credential mounted and see
   whether the code location loads (the open question) — `judgment` (the units' mounts, the limits and
   what the UI may see are the design's) — R2.1, R2.3, R2.4, R2.5
   - Verify: `.agentic/gates` green; the ignore-file test fails when `.env` is removed from the root
     file; the generator's dry run accepts both units;
     `podman build` succeeds on arm64 and `front-office --help`, `dagster definitions validate` run
     in the image; `podman image history` and a grep of the build context for the cookie names and
     the key's `private_key_id` find nothing; the answer to the UI question recorded on #218.
4. Draft the runbook under `docs/` (R6.1) and the README's roadmap line — the daemon, the schedule
   and the NAS's pull now exist — from tasks 1 to 3, to be finished after task 8 — `impl` — R6.1
   - Verify: every R6.1 verb has a heading with a command under it; `.agentic/gates` (the docs
     site builds).
5. Set up `front-office` on `mothership` — `judgment`, the owner for the credentials — R3.1, R3.2,
   R4.1
   - Move: stop the spike's containers under `ubuntu`; copy the landing zone to
     `/home/front-office/data/raw` (`rsync --archive --exclude '*.tmp-*'`); merge the laptop's 19
     captures into it and the host's 6 into the laptop (`--ignore-existing`, both ways); check the
     counts per endpoint and `front-office repair --dry-run --deep` (0 items). Nothing fetches
     meanwhile.
   - The owner: creates the service account (ADR 0135) and its key; places the key and the `.env` in
     `/home/front-office/secrets` (0700; files 0400); grants the roles. The agent posts the
     `gcloud` and `bq` commands and the dataset access entries for the owner to run, and checks the
     result with a read-only listing.
   - Verify: the Expected values rows for the landing zone and the roles; `stat` shows the modes; the
     `ubuntu` copies are still there.
6. Bring the units up and prove them on `mothership` — `judgment` — R1.1, R1.3 to R1.5, R2.1 to
   R2.6, R3.4
   - Start the two units; `dagster schedule list` shows both schedules `RUNNING` on the new instance
     (C1); `ss -tlnp`; `podman exec … pwd` in the daemon names `/dagster_home`; the UI reached by an
     SSH tunnel and refused at `mothership`'s tailnet address.
   - Rehearse with `FO_DAILY_CRON` set by a drop-in to a minute ahead: the daemon launches one
     `daily` as `front-office`, on the new account, ending `RUN_SUCCESS`, the build billing about 16 GB
     (`run_results.json`); launch a second `daily` during it: queued; stop the daemon across three
     ticks and start it: one run, and the "has no partition set, so not trying to catch up" line.
     Remove the drop-in.
   - Peak PSS per container under `measure.sh` during a rehearsal run; fix each `--memory` at
     1.5 times its peak or more, record the figures in ADR 0133, and record rpcbind's port 111.
   - Kill the daemon's process: it restarts. Reboot `mothership`: both containers up and the
     schedule `RUNNING`, nobody logged in.
   - The scan of 0217's task 5 over `dagster_home`, the image history, the units and the user
     journal.
   - Verify: the Expected values rows for the schedule state, the missed stretch, the second run, the
     run, the memory, the secrets and the listeners; the evidence on #218. If the pair does not fit its
     limits, stop and take ADR 0133's option 2 back to the owner.
7. The NAS's pull and the laptop's — `judgment`, the owner for the tailnet and DSM — R4.2, R5.1,
   R5.2, R5.4
   - The owner: the tailnet rule (the NAS reaches `mothership` on 22; `mothership` reaches nothing);
     the NAS's key and the restricted `authorized_keys` line, which the agent drafts; the Task
     Scheduler job running `deploy/pull_landing.sh` hourly into a shared folder that Hyper Backup
     includes; the laptop's hourly backup excluding `data/raw`.
   - The pull script writes a `last_pull_ok` file beside the copy after each good run; the runbook says
     to read its age and DSM's Hyper Backup log (R5.4).
   - Verify: from the NAS, a pull, then `rsync -n --itemize-changes` listing nothing; the NAS's key
     given a shell and a different path is refused; from `mothership`, a connection to the NAS
     fails; the laptop's pull run and `front-office load` on it lists the union; the laptop's backup
     log no longer holds `data/raw`. Recorded on #218.
8. After the NAS's next 03:00 job: restore one capture from the external drive, compare its sha256
   with the host's, and confirm the boot volume's encryption — `judgment`, the owner — R5.3, R5.5
   - Verify: the two hashes equal; the `oci` output (or the console's page) recorded.
9. Close the move and finish the runbook — `judgment` — R3.1, R3.2, R3.3, R6.1
   - After a scheduled-shape `daily` has run from `front-office`'s files: the owner removes the
     `ubuntu` copies of the landing zone, the `.env`, the key and the spike's containers, and retires
     `fo-spike216` and its key. The agent lists what is left under `ubuntu` and does not delete
     it. The runbook is finished from what tasks 5 to 8 showed, and a person other than its author
     follows its deploy and rollback once on `mothership`.
   - Verify: the `ubuntu` home holds no landing zone, no `.env` and no key; `gcloud` shows the
     spike account gone; the runbook's deploy and rollback done by the second person.
10. Before January 1, run the three-day rehearsal: a drop-in with `FO_DAILY_CRON=0 6 * * *` for three
    consecutive mornings, then remove it — `judgment` — R7.2
    - Verify: three runs started by the daemon (not by hand), each `RUN_SUCCESS` with every
      `fetch_complete` passed, listed on #218 with their run ids; the drop-in removed and
      `dagster schedule list` showing the real cron again. It must finish before January 1 (ADR
      0130: ESPN's rollover is unobserved).
11. Post the first in-season checks on #218 and #220: the commands and the expected values — the
    first three March mornings started by the real schedule, each green (R7.2); `espn_captures`'
    `fetch_complete` passed, rosters and teams landed (`front-office audit`), and a settings capture
    at 06:00 ET naming the day's scoring period (R7.1); the Cloud Billing report for the first full
    month with daily runs (R7.3) — and mark the work as awaiting the check — `judgment` — R7.1,
    R7.2, R7.3
    - Verify: the comment exists. The work is not merge-ready on this item alone: R7.1 to R7.3 are
      awaiting the season, and the owner decides at review whether the PR merges before them.
12. (last) Verify every acceptance criterion and expected value against `mothership` and the NAS —
    `judgment` — all
    - Verify: record the commands and results as a comment on #218, against the Expected values
      table, and name what is not yet shown (R7.1 to R7.3).
