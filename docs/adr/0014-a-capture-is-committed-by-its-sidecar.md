# 0014. A capture is committed by its sidecar, published last and never over an existing file

- Status: proposed
- Date: 2026-10-05
- Spec: [0029-committed-captures](../specs/0029-committed-captures/design.md) · Issue: #29

## Context

A capture is a payload file and a metadata sidecar. `LandingZone.write` renames each into
place separately, payload first. Reproduced on 2026-10-05:

- a failure on the sidecar leaves a lone payload, which the fetch logic counts as landed
  and the loader ignores, so the entity is neither refetched nor loaded;
- a second write to the same path replaces the first silently, and if it then fails at
  its sidecar the new payload sits beside the old sidecar and the pair looks committed.

The direction was agreed in #29 with the reviewer; this records it with the alternatives.

## Decision drivers

- A reader must be able to tell a complete capture from a partial one without guessing.
- Nothing already landed may be replaced.
- No change to the landing layout, and no rewriting of the 5,118 captures already there.
- Standard library only, and it must work on the filesystem the landing zone is on.

## Considered options

1. **The sidecar is the commit marker** — publish the payload, then the sidecar; a
   capture exists only when both do. Each file is published with a hard link, which
   fails if the name exists.
2. **A directory per capture** — write both files into a temporary directory and rename
   the directory into place, which is atomic for the pair.
3. **One file per capture** — an envelope holding the metadata and the payload, so there
   is no pair.
4. **Exclusive create on the final path** (`O_EXCL`) — as first proposed in the review
   response.

## Decision

Chosen: **option 1**. A write puts both files under temporary names, links the payload
to its final name, then links the sidecar, then removes the temporary names. `os.link`
refuses an existing name, so a collision fails at the moment of publishing and leaves the
existing file untouched; both final paths are also checked before anything is published.
The sidecar additionally records the payload's size and SHA-256, so "both files exist"
can be tightened to "and they agree": the fetch logic checks the size, the audit the
checksum.

Option 2 is the cleanest atomic pair, but it changes the layout: every existing capture
would move into its own directory and every reader and the backup would follow. Option 3
ends the pairing problem and breaks the project's first rule for ingestion, that a
payload is saved exactly as it arrived. Option 4 makes the final name visible while the
file is still being written, which the reviewer's follow-up rejected.

A collision stops the run. With one writer and a per-run timestamp it cannot happen in
normal use, so it means a bug or a clock problem, and continuing would bury it.

## Consequences

- Good: one definition of a capture, which #27 and #30 build on.
- Good: no existing file changes; old sidecars, which record no size or checksum, are
  accepted as they are.
- Bad / accepted cost: between the two publishes a payload exists without its sidecar.
  That window is the thing the commit marker defines away: such a payload is simply not
  a capture, and the next run moves it aside ([ADR 0015](0015-incomplete-captures-are-quarantined-under-a-writer-lock.md)).
- Bad / accepted cost: hard links need a filesystem that has them. The landing zone's
  does (btrfs, checked); on one that does not, a write fails loudly.
- Bad / accepted cost: the sidecar format gains two fields, so captures written before
  and after differ in what can be verified.
- Follow-ups: none.
