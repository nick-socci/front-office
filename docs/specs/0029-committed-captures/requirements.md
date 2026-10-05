# Committed captures: a payload and its sidecar land together, or not at all — requirements

Issue: #29 · Tier: M · Status: draft

## Problem

A capture is two files, the payload and a sidecar recording its request. Each is written
atomically; the pair is not. Review finding
[R3](../../reviews/2026-09-27-code-review.md#r3--p1-a-sidecar-failure-creates-an-orphan-that-ingestion-will-never-repair)
and three probes run on 2026-10-05 ([design.md](design.md#evidence)) show what follows:

- **A lost capture nobody retries.** If the sidecar write fails after the payload is in
  place, the payload is left alone. The fetch logic counts any payload as landed, so a
  settled game or a closed roster period is never fetched again; the loader skips a
  payload with no sidecar. The capture is gone and nothing reports it.
- **A silent overwrite.** A second write to the same path replaces the first with no
  error. If that second write then fails at its sidecar, the new payload sits beside the
  old sidecar and the pair looks committed.
- **Three definitions of "landed".** The fetch logic looks for any payload file, the
  loader requires a sidecar, and the audit has a third classification that only it uses.

The real landing zone holds 201 payloads with no sidecar, left by pre-pipeline scripts
(#21). They sit in folders the fetch logic does not consult, so they have cost only audit
noise; the same file in a roster or boxscore folder would freeze that entity.

#27 and #30 both need to ask "when was this entity last captured for certain?", which
has no single answer until this is fixed.

## Goals

- A capture exists when, and only when, both files are in place and agree.
- Every part of the system uses that one definition.
- A failure at any point in a write is repaired by the next run, without a person.
- Nothing already landed is ever replaced or deleted by the ingestion package.

## No-gos

- **No change to the landing layout**, and no rewriting of any file already landed.
  Existing sidecars stay as they are.
- **No automatic deletion.** Incomplete files are moved aside, never removed.
- **No quarantine inside the landing root**, and none in a path git could pick up.
- **No sub-second timestamps and no new capture id.** The reviewer's follow-up asked to
  keep the timestamp format and fail on collisions; concurrency is prevented by a lock,
  not designed for.
- **Not R1 or R4** (#27, #30): when a capture is *final* is their subject. This gives them
  the committed capture to build on.
- **No change to the raw table or any dbt model.**
- **The NAS backup is not touched.**

## Rabbit holes

- *A transactional store, a manifest database, a write-ahead log* → two files and a
  publish order. The sidecar is the commit record.
- *Making concurrent writers work* → one writer at a time, enforced; a second is refused.
- *Verifying every payload's checksum on every run* → the fetch logic checks existence
  and size; the audit checks the checksum.
- *Repairing a capture in place* → an incomplete capture is moved aside and the entity
  is fetched again.

## Requirements

### R1. Publishing a capture

- R1.1 THE SYSTEM SHALL write a capture's payload and sidecar to temporary files, then
  publish the payload, then publish the sidecar, so that the sidecar's presence means
  the payload is complete.
- R1.2 THE SYSTEM SHALL publish each file without replacing an existing one.
- R1.3 IF either final path already exists when a capture is written THEN THE SYSTEM
  SHALL raise a collision error naming the path, publish nothing, and leave the existing
  payload and sidecar byte for byte as they were.
- R1.4 WHEN a collision is raised during a backfill THE SYSTEM SHALL stop the run with a
  non-zero exit, not count it as one failed entity and continue.
- R1.5 THE SYSTEM SHALL record in each new sidecar the payload's size in bytes and its
  SHA-256.
- R1.6 THE SYSTEM SHALL remove its own temporary files when a write fails.

### R2. One definition of a committed capture

- R2.1 THE SYSTEM SHALL treat a capture as committed when its payload and sidecar both
  exist; the sidecar is valid JSON with the required fields; the sidecar describes the
  path the pair is at (source, endpoint, partitions and fetch time); and, where the
  sidecar records the payload's size, the payload has that size. One function decides
  this for the fetch logic, the loader, the sweep and the audit.
- R2.6 THE SYSTEM SHALL check separately, in the audit and on request in the sweep, that
  a committed capture's payload is readable JSON and matches its recorded checksum, and
  SHALL NOT make the fetch logic read every payload to decide what has landed.
- R2.7 IF the loader meets a committed capture whose payload is not valid JSON THEN THE
  SYSTEM SHALL fail the load naming the file, not skip it.
- R2.8 WHEN a file disappears between being listed and being read, because a sweep moved
  it, THE SYSTEM SHALL treat it as not committed and carry on.
- R2.2 THE SYSTEM SHALL decide whether an entity has landed, in every fetch path, from
  committed captures only.
- R2.3 THE SYSTEM SHALL load only committed captures.
- R2.4 THE SYSTEM SHALL read the newest schedule, and anything else it reads back from the
  landing zone, from committed captures only.
- R2.5 THE SYSTEM SHALL accept a sidecar written before this change, which records no
  size or checksum, as committed when both files exist and the sidecar is valid.

### R3. Recovery

- R3.1 WHEN a backfill starts THE SYSTEM SHALL move every file under the landing root
  that is not part of a committed capture (a payload with no sidecar, a sidecar with no
  payload, a pair that fails R2.1, a leftover temporary file) to a quarantine directory,
  keeping its relative path, and log each one.
- R3.2 THE SYSTEM SHALL keep the quarantine directory outside the landing root, and SHALL
  make it ignored by git wherever it is, by writing an ignore-everything file into it
  before moving anything, so that a landing root other than the default is covered too.
- R3.3 THE SYSTEM SHALL never delete or overwrite a quarantined file; a second file with
  the same relative path goes under a new run directory.
- R3.4 WHEN a capture was quarantined THE SYSTEM SHALL fetch its entity again in the same
  run if that entity is one the run fetches, by the ordinary rule that it has not landed.
- R3.5 THE SYSTEM SHALL provide the same sweep as a command that fetches nothing, with a
  dry-run mode that lists what would move, and a deep mode that also moves committed
  captures failing R2.6.

### R4. One writer

- R4.1 THE SYSTEM SHALL hold an exclusive lock on the landing root for the whole of any
  command that writes to it or sweeps it.
- R4.2 IF the lock is held by another process THEN THE SYSTEM SHALL exit non-zero at
  once with a message naming the lock, and change nothing.
- R4.3 THE SYSTEM SHALL use a lock that the operating system releases when its process
  ends, so that a killed run leaves nothing to clear.
- R4.4 THE SYSTEM SHALL keep the lock file outside the landing root.
- R4.5 THE SYSTEM SHALL let `load` and `audit` run without the lock.

### R5. Audit

- R5.1 THE SYSTEM SHALL report in `front-office audit` any file under the landing root
  that is not part of a committed capture, as an error, as it does today.
- R5.2 THE SYSTEM SHALL verify in the audit, for every sidecar that records one, that the
  payload's SHA-256 matches, and report a mismatch as an error.
- R5.3 THE SYSTEM SHALL report the number of files in quarantine, as a warning when it is
  not zero.

## Expected values

Real landing zone, `data/raw/`, on 2026-10-05 after the settle-window refresh.

| Check | Expected | How to verify |
|---|---|---|
| Today, before this change | 5,118 committed captures; 201 payloads with no sidecar; 0 sidecars with no payload; 0 temporary files | `LandingZone.scan()` |
| The orphan, today | a failed sidecar write leaves 1 payload; the fetch logic says it does not need fetching; the loader inserts 0 | reproduced; becomes a fault-injection test expecting a refetch |
| The overwrite, today | a second write to one path replaces the payload with no error | reproduced; becomes a test expecting a collision error and the first payload intact |
| No-replace publish | `os.link` onto an existing name raises `FileExistsError` on the landing zone's filesystem (btrfs) | reproduced |
| After #21, first sweep (dry run) | 0 files to move | `front-office repair --dry-run` |
| If run before #21 | exactly the 201 spike payloads would move, and nothing else | `front-office repair --dry-run` |
| Committed captures after the change | 5,118, the same set as the loader holds: `raw.api_responses` has 5,118 rows | scan; row count |
| Existing sidecars | all 5,118 lack size and checksum and are still committed | scan |
| Fault injection | each failure point has its own stated disk state (design.md, Test strategy); after the next run the entity is committed, nothing uncommitted is under the landing root, and whatever debris that failure leaves is in quarantine | pytest, one case per point |
| Audit after #21 and this change | exit 0, 0 errors, 0 warnings | `front-office audit --season 2026` |
