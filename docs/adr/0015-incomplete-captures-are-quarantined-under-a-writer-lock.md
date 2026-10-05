# 0015. Incomplete captures are quarantined at the start of a run, under a writer lock

- Status: proposed
- Date: 2026-10-05
- Spec: [0029-committed-captures](../specs/0029-committed-captures/design.md) · Issue: #29

## Context

With the sidecar as the commit marker ([ADR 0014](0014-a-capture-is-committed-by-its-sidecar.md)),
a partial capture is no longer mistaken for a real one: the fetch logic ignores it and
fetches the entity again under a new timestamp. The partial files themselves remain. The
real landing zone shows what that costs: 201 payloads with no sidecar have made the audit
report 5 errors on every run since September, which is exactly the noise that would hide
a new orphan.

The reviewer's follow-up set two conditions on moving them aside: the quarantine must be
outside the tree that readers scan, and a write in progress must not be mistaken for an
orphan.

## Decision drivers

- The landing root should hold committed captures and nothing else.
- Nothing is ever deleted automatically: a partial capture may be the only copy of
  something.
- A sweep must not race a writer.
- A killed or suspended run must not leave anything for a person to clear.
- Quarantined ESPN payloads are private and must not be committable.

## Considered options

1. **Sweep at the start of every backfill, under an operating-system lock** — move
   anything uncommitted to a quarantine directory beside the landing root.
2. **Leave partial files where they are** — readers already ignore them; the audit
   reports them until a person acts.
3. **A separate repair command only** — the same sweep, but never automatic.
4. **Delete partial files.**

## Decision

Chosen: **option 1**, with option 3's command as well. Every command that writes takes
an exclusive `flock` on a lock file beside the landing root and holds it to the end; a
second writer is refused at once. Under that lock, a backfill first moves every file
that is not part of a committed capture to `<landing root>_quarantine/<run stamp>/`,
keeping its relative path, then fetches as usual, so the entity is fetched again in the
same run. `front-office repair` runs the sweep alone, with `--dry-run`.

`flock` is released by the kernel when the process ends, so a killed run leaves no stale
lock; a suspended one still holds it, correctly. Leaving partial files in place is safe
for correctness but lets the audit's errors become wallpaper. A repair command alone
relies on someone running it. Deleting is ruled out: the 201 spike payloads turned out to
be the only evidence of how ESPN reports eligibility.

`load` and `audit` take no lock. A reader that arrives between the two publishes of a
write sees a payload with no sidecar and correctly treats it as not yet a capture.

## Consequences

- Good: after a run the landing root holds only committed captures, and the audit's
  landing section is quiet unless something is new.
- Good: no stale-lock procedure.
- Bad / accepted cost: files move without anyone asking. Every move is logged, nothing
  is deleted, and the audit warns while the quarantine is not empty.
- Bad / accepted cost: `flock` is advisory, so a script that writes to the landing root
  without the package is not stopped. Its files would be swept on the next run, which is
  the right outcome.
- Bad / accepted cost: the quarantine needs its own `.gitignore` entry; today's rules
  cover `data/raw/` but not a sibling directory.
- Follow-ups: #21 retires the 201 spike payloads first. If it has not, the first sweep
  moves exactly those and nothing else.
