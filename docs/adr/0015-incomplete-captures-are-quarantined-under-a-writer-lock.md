# 0015. Anything that is not a capture is quarantined at the start of a run, under a writer lock

- Status: accepted
- Date: 2026-10-05
- Spec: [0029-committed-captures](../specs/0029-committed-captures/design.md) · Issue: #29

## Context

With a capture published by one rename
([ADR 0014](0014-a-capture-is-a-directory-published-by-one-rename.md)), a run that is
killed leaves at most a temporary directory. Nothing reads it and nothing is blocked by
it, so this is no longer about correctness. It is about what the landing root is allowed
to hold. The real landing zone shows the cost of allowing clutter: 201 payloads with no
sidecar have made the audit report 5 errors on every run since September, which is the
noise that would hide something new.

The reviewer's follow-up set two conditions on moving such things aside: the quarantine
must be outside the tree that readers scan, and a write in progress must not be mistaken
for debris.

## Decision drivers

- The landing root should hold committed captures and nothing else, so that an audit
  error means something.
- Nothing is ever deleted automatically: something that looks like junk may be the only
  copy.
- A sweep must not race a writer.
- A killed or suspended run must not leave anything for a person to clear.
- Quarantined ESPN payloads are private and must not be committable.
- Files moving without being asked must not be able to go badly wrong.

## Considered options

1. **Sweep at the start of every backfill, under an operating-system lock.**
2. **Leave it where it is** — readers ignore anything that is not a capture; the audit
   reports it until a person acts.
3. **A separate repair command only.**
4. **Delete it.**

## Decision

Chosen: **option 1**, with option 3's command as well.

Every command that writes, sweeps or migrates takes an exclusive `flock` on a lock file
beside the landing root and holds it to the end. A second writer waits a moment and is
then refused. Under that lock, a backfill first moves everything that is not a committed
capture to `<landing root>_quarantine/<run stamp>/`, keeping its relative path, then
fetches as usual. `front-office repair` runs the sweep alone, with `--dry-run` and
`--deep`.

Safeguards, since files move unasked:

- it only moves; it never deletes or overwrites, and the relative path makes a move
  reversible by hand;
- every move is logged, and the audit warns while the quarantine is not empty;
- the quarantine is made git-ignored by an ignore-everything file written into it first,
  so a landing root other than the default is covered;
- **a sweep that would move more than the larger of 50 items and 1% of the files under
  the root moves nothing** and exits non-zero unless forced. A killed run leaves a
  handful of things; thousands mean a bug in the capture check or a landing zone that
  was never migrated;
- the first sweep of the real landing zone is a dry run shown to the owner.

`load` and `audit` do not wait for the lock: a capture appears in one step, so there is
nothing half-written for them to see. They warn if a writer holds it, because a load
during a backfill is correct but incomplete.

`flock` is released by the kernel when the process ends, so a killed run leaves no stale
lock; a suspended one still holds it, correctly. Leaving clutter in place is safe and
lets the audit's errors become wallpaper. A repair command alone relies on someone
running it. Deleting is ruled out: the 201 spike payloads turned out to be the only
evidence of how ESPN reports eligibility.

## Consequences

- Good: after a run the landing root holds only committed captures.
- Good: no stale-lock procedure.
- Bad / accepted cost: files move without anyone asking, within the safeguards above.
- Bad / accepted cost: `flock` is advisory, so a script that writes to the landing root
  without the package is not stopped. Its files would be swept on the next run.
- Bad / accepted cost: a reader's check of the lock holds it for an instant, which is why
  a writer waits briefly before deciding it is refused.
- Follow-ups: #21 retires the 201 spike payloads before the migration.
