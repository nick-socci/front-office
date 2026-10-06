# 0014. A capture is a directory, published by one rename

- Status: accepted
- Date: 2026-10-05
- Spec: [0029-committed-captures](../specs/0029-committed-captures/design.md) · Issue: #29

## Context

A capture is a payload file and a metadata sidecar. `LandingZone.write` renames each into
place separately, payload first. Reproduced on 2026-10-05:

- a failure on the sidecar leaves a lone payload, which the fetch logic counts as landed
  and the loader ignores, so the entity is neither refetched nor loaded;
- a second write to the same path replaces the first silently, and if it then fails at
  its sidecar the new payload sits beside the old sidecar and the pair looks committed.

#29 had agreed a different fix with the reviewer: keep the two loose files and treat the
sidecar, published last, as the commit marker.

## Decision drivers

- A capture should be complete or absent; no state in between for a reader to interpret.
- Nothing already landed may be replaced, and no landed file's contents may change.
- The cost of changing the layout is lowest now: one league-season is landed, and #57
  will add many.
- Standard library only, on the filesystem the landing zone is on.

## Considered options

1. **The sidecar is the commit marker** — publish the payload, then the sidecar, each by
   hard link; a capture exists only when both do. The layout does not change.
2. **A directory per capture** — write both files into a temporary directory and rename
   the directory into place.
3. **One file per capture** — an envelope holding the metadata and the payload.
4. **Exclusive create on the final path** (`O_EXCL`).

## Decision

Chosen by the owner on 2026-10-05: **option 2**, over the recommendation of option 1.

A capture is the directory `…/<partitions>/fetched_at=<stamp>/` holding `payload.json`
and `meta.json`. The writer builds it under a temporary name beside the final one and
publishes it with a single `os.rename`. The sidecar also records the payload's size and
SHA-256. If the final directory already exists the write is a collision: it raises,
publishes nothing and stops the run. The 5,118 captures already landed are moved into
the same layout by rename alone; their sidecars are not rewritten.

Option 1 leaves a window in which a payload exists without its sidecar, and defines that
state away: such a payload is "not a capture". It is correct, and it is cheaper. Option 2
removes the state. The owner preferred the more solid design, and the comparison of
costs showed it affordable: the migration is renames on one filesystem, and the larger
costs are a second rebuild of the warehouse and a mechanical move of 84 fixture files.
Option 3 breaks the rule that a payload is saved exactly as it arrived. Option 4 shows a
reader a file that is still being written.

One property of the rename has to be handled: onto a non-empty directory it fails, which
is the refusal wanted, but onto an *empty* directory it succeeds and replaces it. The
writer therefore checks for an existing final directory first, and the writer lock
([ADR 0015](0015-incomplete-captures-are-quarantined-under-a-writer-lock.md)) makes that
check sound.

## Consequences

- Good: no half-published capture can exist for anything written by this code; readers
  no longer pair files by name.
- Good: one definition of a capture, which #27 and #30 build on.
- Bad / accepted cost: every existing path changes. The migration is verified against a
  checksum manifest taken before it and can be reversed from a record of its moves.
- Bad / accepted cost: the raw table's `file_path` values change, so the real warehouse
  is rebuilt beside the old one and compared, and the owner swaps the files again.
- Bad / accepted cost: the NAS backup of the old layout is superseded and refreshed.
- Bad / accepted cost: captures written before and after differ in what can be verified;
  only new sidecars carry a size and checksum. The manifest of 2026-10-05 covers the
  rest.
- Follow-ups: none.
