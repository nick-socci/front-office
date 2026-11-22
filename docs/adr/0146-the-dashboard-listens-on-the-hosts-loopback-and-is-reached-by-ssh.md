# 0146. The dashboard listens on the host's loopback and is reached by an SSH tunnel

- Status: proposed
- Date: 2026-11-21
- Spec: [0232-dashboard](../specs/0232-dashboard/design.md) · Issue: #232

## Context

`mothership` holds members' data under ADR 0126's controls: SSH only over the tailnet, no public
port, no connection started on the tailnet. Dagster's UI listens on the host's loopback and is
reached by `ssh -L` (C15). The dashboard shows real team names (C14) and is for the owner alone. In
season the owner may want it on a phone, where an SSH tunnel is awkward.

## Decision drivers

- No public listener; nothing new on the tailnet unless chosen.
- Usable where the owner will look at it.
- Nothing for the owner to administer beyond what exists.

## Considered options

1. **Loopback only, reached by `ssh -L 8501:127.0.0.1:8501 mothership`**, as Dagster's UI is.
2. **`tailscale serve`** on the host (set once by the admin account), which proxies the loopback port
   to an HTTPS address on the tailnet only. It works from the phone, and every tailnet device can
   reach it unless the tailnet's access rules say otherwise.
3. **Publish the port on the host's tailnet address.** Plain HTTP inside WireGuard. It depends on
   `tailscaled` being up before the user's units start at boot.

## Decision

Chosen by the owner on 2026-11-22, at the spec's walkthrough: **option 1**, as recommended, for now, with option 2 as a later change of one unit's surroundings, not
of the app. Option 1 adds no listener anywhere and matches how the UI is reached. Option 2 is the
better daily experience on a phone, at the cost of a tailnet service and an admin step. Option 3
gives option 2's reach with a boot-order failure mode.


## Consequences

- Good: no new exposure on the host. The dashboard is as private as Dagster's UI.
- Bad / accepted cost: reaching it needs a device with the SSH key and a tunnel.
- Follow-ups: if the owner wants phone access in season, a short ADR moves to option 2, with a
  tailnet access rule limited to the owner's devices.
