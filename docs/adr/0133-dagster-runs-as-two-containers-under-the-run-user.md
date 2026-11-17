# 0133. Dagster runs as two containers under the run's user, from units kept in the repository

- Status: accepted, amended by [0138](0138-dagsters-code-runs-in-its-own-container-and-the-daemon-and-ui-connect-to-it.md)
- Date: 2026-11-17
- Spec: [0218-schedule-the-daily-run](../specs/0218-schedule-the-daily-run/design.md) · Issue: #218

## Context

ADR 0126 puts Dagster's daemon, the CLI and the BigQuery build on `mothership` "in containers",
each with its own memory limit, under one unix user (`front-office`, uid 1002, linger on, Podman
4.9.3 with Quadlet's generator, the memory controller delegated to the user's slice: spec C4). The repository
has no image definition, unit file or Dagster instance file (C12): the 0216 spike's image was a
throwaway outside it. What was measured (674 MB idle, 1,395 MB with a full `daily`, C9) was
`dagster dev`, one process tree, which Dagster's own help calls "a local deployment" (C13).

## Decision drivers

- Starts at boot and restarts after a crash with nobody logged in.
- Each process has a memory limit (ADR 0126), and a UI crash does not stop the schedule.
- The credentials reach as few processes as possible (C15: the UI needs none).
- The deployment can be rebuilt from the repository, and the home server (ADR 0126) can take the
  same image.

## Considered options

1. **Two containers from one image**: `dagster-daemon run` and `dagster-webserver`, two Quadlet
   `.container` units in `deploy/`, started by `front-office`'s systemd.
2. **One container running `dagster dev`**: the shape that was measured.
3. **A `uv` virtual environment and systemd user services**, no containers.

## Decision

Chosen by the owner on 2026-11-17, at the spec's walkthrough: **option 1**, as recommended. The daemon and the UI are separate commands (C13), so each gets its own
limit and restart, and only the daemon's container mounts the ESPN `.env` and the Google key. Its
costs are a second `dbt parse` when the UI loads the code location (276 MB and 6.8 s, 0216 C7) and
a memory figure that has not been measured in this shape: spec task 6 measures it and fixes each
container's limit, provisionally 3 GB for the daemon and 1 GB for the UI. If the pair does not
fit, option 2 is the fallback, with one limit. Option 3 amends ADR 0126's "in containers" to save a
build step, and leaves the home server without an image.

Podman 4.9.3's Quadlet has no `.pod` units and no `Memory=` (C19), so there is no pod (the two share
only the instance's volume) and the limit is `PodmanArgs=--memory=`; the container's directory is
`WorkingDir=`, not systemd's `WorkingDirectory=`. The UI listens on `0.0.0.0` inside its container and
is published on the host's loopback only, so an SSH tunnel reaches it. The image holds no credential; it
is built from the repository at a stated commit, which is its label, and deploys and rollbacks are
a tag change and a restart.

## Consequences

- Good: restarts and limits per process; the UI holds no credential; the unit files are reviewed
  with the code.
- Bad / accepted cost: two code loads, so two dbt parses; a build step on the host for each deploy
  (the image is built on `mothership`, arm64, by hand, not by CI).
- Follow-ups: spec tasks 3 and 6. The runbook says how to deploy and roll back. A superseding ADR
  when the home server exists moves the same image there.
