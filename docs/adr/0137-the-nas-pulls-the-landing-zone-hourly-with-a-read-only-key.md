# 0137. The NAS pulls the landing zone hourly with a key that can only read it

- Status: proposed (the owner's: the NAS backup)
- Date: 2026-11-17
- Spec: [0218-schedule-the-daily-run](../specs/0218-schedule-the-daily-run/design.md) · Issue: #218

## Context

ADR 0126 makes the second device in the home a pull of the landing zone onto the NAS, started by
the NAS because `mothership` starts nothing on the tailnet, with "a tailnet grant for the NAS to reach
`mothership`'s SSH, with a read-only account", and the NAS's 03:00 Hyper Backup job carrying the
pulled copy to the external drive (C7). It leaves #218 the pull's interval, the account and a restore
test. `front-office`'s home is mode 0700 and `/srv` is root's (C18). `mothership` has `rrsync` (C17),
and a listing of the 44,444 captures takes 14 s (C5).

## Decision drivers

- A capture reaches a second device soon: ESPN data cannot be refetched after the league rolls over.
- The key the NAS holds can do nothing but read the landing zone.
- No new account or permission scheme on a host with credentials in it.

## Considered options

1. **An hourly NAS pull with a key restricted to `rrsync -ro` on the landing zone**, on the run's
   account.
2. **A separate read-only unix account**, a daily pull after the run, the landing zone moved outside
   the 0700 home.
3. **An hourly pull through a second account that owns a copy.**

## Decision

Chosen by the owner on 2026-11-17, at the spec's walkthrough: **option 1**, as recommended. The line in `front-office`'s `authorized_keys` is
`restrict,command="rrsync -ro /home/front-office/data/raw"`: no shell, no forwarding, and one
directory, read-only, which holds neither the `.env` nor the Google key. The NAS runs
`deploy/pull_landing.sh` (`rsync --archive --ignore-existing --exclude '*.tmp-*'`, never `--delete`)
from DSM's Task Scheduler every hour. While the pull and the backup job succeed, a capture is on a second device within an
hour, and on the external drive within that hour plus up to 24 hours (ADR 0126). Those are intervals
between jobs, not a bound: a pull that fails leaves a capture on `mothership` alone until one
succeeds, so the script writes a `last_pull_ok` file after each good run and the runbook says to read
its age and DSM's Hyper Backup log. The interval is the owner's to change. Option 2 follows ADR 0126's wording to the letter and costs a user, a group, a
moved landing zone and a daily gap. Option 3 doubles the disk for nothing.

## Consequences

- Good: the second copy is at most an hour behind; a stolen NAS key reads what the NAS already holds;
  nothing new on the host.
- Bad / accepted cost: a pull reading a capture as it is published is avoided only by the exclusion
  (a capture is published by one rename, ADR 0014); the key sits on the NAS, which the owner trusts.
- Follow-ups: the owner adds the tailnet rule (the NAS reaches `mothership` on 22; `mothership` reaches
  nothing), the Task Scheduler job and Hyper Backup's folder; one restore from the external drive is
  tested (spec R5.3).
