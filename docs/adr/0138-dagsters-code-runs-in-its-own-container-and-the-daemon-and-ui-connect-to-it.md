# 0138. Dagster's code runs in its own container, and the daemon and the UI connect to it

- Status: accepted (the owner chose it on 2026-11-17, during the build, from the options below)
- Date: 2026-11-17
- Spec: [0218-schedule-the-daily-run](../specs/0218-schedule-the-daily-run/design.md) · Issue: #218
- Amends: [0133](0133-dagster-runs-as-two-containers-under-the-run-user.md)

## Context

ADR 0133 chose a daemon container and a UI container, each loading the code location through
`workspace.yaml`'s `python_module`. Each Dagster process then starts its own code server, on a unix
socket in its own `/tmp`. The first rehearsal on `mothership` (spec 0218 *Amendments*, 2026-11-17)
launched a run through the UI and cancelled it: `DagsterUserCodeUnreachableError: Could not reach
user code server. gRPC Error code: UNAVAILABLE`. The run's worker and its 16 GB `dbt build` ran to
the end although the run showed `CANCELING`, then `CANCELED`. The sockets were in the daemon container's
`/tmp`, and the UI container's `/tmp` had none of them. The daemon's own run monitoring (the two-hour
limit, ADR 0134) runs in the daemon and is not affected. The Terminate button is the way to stop a bad
morning's run, and it did not work.

## Decision drivers

- A run started by the daemon or the UI can be cancelled from the UI, and the cancel stops the worker.
- The credentials reach as few processes as possible (ADR 0133).
- The shape is the one Dagster's own multi-process deployments use, and not a hack of paths.

## Considered options

1. **A third container: one code server** (`dagster api grpc`) on the host's loopback, which the daemon
   and the UI load through `grpc_server` in `workspace.yaml`.
2. **Keep two containers and cancel from the daemon's container** by a command in the runbook.
3. **One container** for the daemon and the UI (ADR 0133's option 2), sharing one code server.

## Decision

Chosen by the owner: **option 1**, as recommended. The three units share the host's network
(`Network=host`) and bind to 127.0.0.1 (the code server on 4266, the UI on 3000), so nothing listens on
another address. Runs execute as subprocesses of the code server, so **the code server's container
is the one that mounts the ESPN `.env`, the Google key and the landing zone**; the daemon and the UI
mount the instance's volume and nothing else. The code location loads once, so dbt is parsed once and
not twice. The memory limits are the code server's 3 GB, the daemon's 1 GB and the UI's 1 GB, to be
confirmed by measurement (spec task 6).

Option 2 leaves the UI's button broken and the fix a command to remember on a bad morning. Option 3
supersedes ADR 0133's choice for a shape where one process's crash takes the other down.

## Consequences

- Good: Terminate works from the UI; the daemon and the UI hold no credential; one dbt parse.
- Good: the credentials sit in the one container that needs them.
- Bad / accepted cost: a third unit, and an unauthenticated gRPC port on the host's loopback: any
  local user of `mothership` (the owner's own `ubuntu` account) could ask it to run the pipeline. The
  host's accounts are the owner's (ADR 0126).
- Bad / accepted cost: the daemon and the UI start after the code server, and show the location as
  errored until it is up (a few seconds).
- Follow-ups: spec task 6 re-runs the cancel test, the reboot and the memory measurement on this shape.
