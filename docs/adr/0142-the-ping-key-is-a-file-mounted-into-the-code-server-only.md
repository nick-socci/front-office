# 0142. The ping key is a file mounted into the code server only

- Status: proposed
- Date: 2026-11-20
- Spec: [0219-alert-on-the-daily-run](../specs/0219-alert-on-the-daily-run/design.md) · Issue: #219

## Context

The healthchecks.io ping key (ADR 0139) lets anyone who holds it mark the two checks up or down:
with it, a failure could be hidden. It is a credential under AGENTS.md rule 3. Sensors are
evaluated in the code server's process (C8), the container that already mounts the ESPN `.env` and
the Google key, one file each, read-only, from `~/secrets` (ADR 0133, 0135). Runs execute in that
container too, as subprocesses that inherit its environment, and run the CLI and dbt.

## Decision drivers

- Only the code that pings can read the key, and nothing logs it.
- The same shape as the run's other credentials, so the runbook has one pattern.

## Considered options

1. **A file**, `~/secrets/healthchecks-ping-key` (0400), mounted read-only at
   `/run/secrets/healthchecks-ping-key` in the code server only. Its path, not its value, is in
   `FO_HEALTHCHECKS_PING_KEY_FILE`, and one function reads it.
2. **An environment variable** from an `EnvironmentFile=` in `~/secrets`.
3. **The full ping URLs** in the environment, one per job.

## Decision

Chosen by the owner on 2026-11-20: **option 1**, as recommended. Options 2 and 3 put the value in the environment of every run's
subprocesses (the CLI, dbt, `uv`) and of anything that dumps its environment. A file is read
when a ping is sent, and only there. One key with fixed slugs (C2) is one secret instead of two
URLs, and an unknown slug is a 404 rather than a silent miss.

## Consequences

- Good: the key never enters a process's environment, and the daemon and UI containers never see
  it.
- Bad / accepted cost: one more file for the owner to place. The owner creates it; an agent never
  creates, copies or reads it.
- Follow-ups: the planned secret manager replaces the file, as for the other two credentials.
