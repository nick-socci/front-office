# 0125. The landing zone joins the NAS's backup to its external drive

- Status: proposed (the owner's decision: AGENTS.md puts the NAS backup outside an agent's choice)
- Date: 2026-11-04
- Spec: [0216-where-the-daily-run-runs](../specs/0216-where-the-daily-run-runs/design.md) · Issue: #216

## Context

Today the landing zone's primary copy is on the laptop, and an hourly user timer backs up the home
directory to the NAS (spec C11). Under ADR 0121 the NAS holds the primary copy, so the existing
backup runs the wrong way for captures. It would copy the laptop's pulled copy back onto the device
it came from. ESPN data cannot be refetched after the league rolls over, and a capture is never
re-created.

The laptop's pulled copy (ADR 0121) is a second device only up to its last pull. While the laptop
is away, every capture landed since then is on the NAS alone (design review F2). The NAS already
backs itself up to an external hard drive in the home (the owner, 2026-11-05).

## Decision drivers

- Every capture on two devices, with the gap before that stated, not hidden (spec R5.3).
- Members' data stays in the home (ADR 0054).
- No new cost.

## Considered options

1. **The NAS and the laptop's pull only**; the hourly backup leaves out `data/raw/`.
2. **Option 1, plus snapshots on the NAS**: covers a bad write or a deletion on the NAS, not the
   NAS failing.
3. **The landing zone added to the NAS's existing backup job to its external drive**, with the
   laptop's pull kept: a second device in the home that does not need the laptop.
4. **An encrypted copy outside the home**: survives losing the home; needs ADR 0054 amended.

## Decision

Chosen by the owner on 2026-11-05, at the spec's walkthrough: **option 3**. It was not among the
options first put to them, which recommended option 2. The owner's existing NAS backup already
does what option 3 asks, at no cost. The landing zone's folder is added to that job, and the
laptop's hourly backup leaves out `data/raw/`, since the NAS holds it.

## Consequences

- Good: every capture reaches a second device in the home on the backup job's schedule, whether
  or not the laptop is there. The laptop's pull is a third copy.
- Good: no new device, service or cost, and members' data stays in the home.
- Bad / accepted cost: a capture landed since the job's last run is on the NAS alone. Task 1
  records the job's schedule, and that schedule bounds the gap.
- Bad / accepted cost: the home itself is a single point of failure. Option 4 remains open.
- Follow-ups: #218 adds the folder to the NAS's backup job and changes the laptop's exclusions.
  One restore of a capture from the external drive is tested, and recorded on #218.
