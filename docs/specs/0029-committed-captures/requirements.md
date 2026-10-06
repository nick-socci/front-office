# Committed captures: a payload and its sidecar land together, or not at all — requirements

Issue: #29 · Tier: M · Status: approved 2026-10-05

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

- A capture appears in the landing zone in one step, complete, or not at all.
- Every part of the system uses one definition of a capture.
- Whatever a killed run leaves behind is cleared by the next run, without a person.
- Nothing already landed is ever replaced or deleted by the ingestion package, and no
  file's contents change.

## No-gos

- **No change to any landed file's contents.** The layout changes (ADR 0014): every
  capture moves into its own directory, by rename only. Existing sidecars are not
  rewritten, so they gain no size or checksum.
- **No automatic deletion.** Anything that is not a capture is moved aside, never removed.
- **No quarantine inside the landing root**, and none in a path git could pick up.
- **No sub-second timestamps and no new capture id.** Concurrency is prevented by a lock,
  not designed for.
- **Not R1 or R4** (#27, #30): when a capture is *final* is their subject. This gives them
  the committed capture to build on.
- **No change to any dbt model or to the shape of the raw table.** The raw table's
  `file_path` values change, so the real warehouse is rebuilt beside the old one and
  compared, as in #28; the owner swaps the files.
- **The NAS backup is not touched by an agent.** The owner backs up before the migration
  and refreshes the backup after it.
- **No second layout kept alive.** After the migration the package reads and writes the
  directory layout only.

## Rabbit holes

- *A transactional store, a manifest database, a write-ahead log* → a directory and one
  rename.
- *Making concurrent writers work* → one writer at a time, enforced; a second is refused.
- *Verifying every payload's checksum on every run* → the light check everywhere; the
  deep check in the audit and on request.
- *Repairing a capture in place* → anything incomplete is moved aside and the entity is
  fetched again.
- *A general migration framework* → one script for this one move, with a dry run, a
  record of every move and a way back.

## Requirements

### R1. Publishing a capture

- R1.1 THE SYSTEM SHALL store each capture as a directory named for its fetch time,
  holding the payload as `payload.json` and the sidecar as `meta.json`.
- R1.2 THE SYSTEM SHALL write both files into a temporary directory and publish the
  capture by renaming that directory to its final name, so that the capture is visible
  complete or not at all.
- R1.3 IF the capture's final directory already exists, empty or not, THEN THE SYSTEM
  SHALL raise a collision error naming the path, publish nothing, and leave whatever is
  there byte for byte as it was.
- R1.4 WHEN a collision is raised during a backfill THE SYSTEM SHALL stop the run with a
  non-zero exit, not count it as one failed entity and continue.
- R1.5 THE SYSTEM SHALL record in each new sidecar the payload's size in bytes and its
  SHA-256.
- R1.6 THE SYSTEM SHALL remove its own temporary directory when a write fails.

### R2. One definition of a committed capture

- R2.1 THE SYSTEM SHALL treat a capture as committed when its directory holds both
  files; the sidecar is valid JSON with the required fields; the sidecar describes the
  path the capture is at (source, endpoint, partitions and fetch time); and, where the
  sidecar records the payload's size, the payload has that size. One function decides
  this for the fetch logic, the loader, the sweep and the audit.
- R2.2 THE SYSTEM SHALL decide whether an entity has landed, in every fetch path, from
  committed captures only.
- R2.3 THE SYSTEM SHALL load only committed captures.
- R2.4 THE SYSTEM SHALL read the newest schedule, and anything else it reads back from the
  landing zone, from committed captures only.
- R2.5 THE SYSTEM SHALL accept a sidecar written before this change, which records no
  size or checksum, as committed when the rest of R2.1 holds.
- R2.6 THE SYSTEM SHALL check separately, in the audit and on request in the sweep, that
  a committed capture's payload is readable JSON and matches its recorded checksum, and
  SHALL NOT make the fetch logic read every payload to decide what has landed.
- R2.7 IF the loader meets a committed capture whose payload is not valid JSON THEN THE
  SYSTEM SHALL fail the load naming the file, not skip it.
- R2.8 WHEN a file or directory disappears between being listed and being read, because a
  sweep moved it, THE SYSTEM SHALL treat it as not committed and carry on.

### R3. Recovery

- R3.1 WHEN a backfill starts THE SYSTEM SHALL move everything under the landing root
  that is not a committed capture or a folder leading to one (a leftover temporary
  directory, a capture directory that fails R2.1, a loose file, an empty directory) to a
  quarantine directory, keeping its relative path, and log each one.
- R3.2 THE SYSTEM SHALL keep the quarantine directory outside the landing root, and SHALL
  make it ignored by git wherever it is, by writing an ignore-everything file into it
  before moving anything.
- R3.3 THE SYSTEM SHALL never delete or overwrite a quarantined file; a second item with
  the same relative path goes under a new run directory.
- R3.4 WHEN something was quarantined THE SYSTEM SHALL fetch its entity again in the same
  run if that entity is one the run fetches, by the ordinary rule that it has not landed.
- R3.5 THE SYSTEM SHALL provide the same sweep as a command that fetches nothing, with a
  dry-run mode that lists what would move and a deep mode that also moves committed
  captures failing R2.6.
- R3.6 IF a sweep would move more items than the larger of 50 and 1% of the files under
  the landing root, counting the folders it would leave empty, THEN THE SYSTEM SHALL move
  nothing and exit non-zero saying how many and why, unless told explicitly to proceed.
  The dry run reports that same complete list.

### R4. One writer

- R4.1 THE SYSTEM SHALL hold an exclusive lock on the landing root for the whole of any
  command that writes to it, sweeps it or migrates it.
- R4.2 IF the lock is still held by another process after a short wait THEN THE SYSTEM
  SHALL exit non-zero with a message naming the lock, and change nothing.
- R4.3 THE SYSTEM SHALL use a lock that the operating system releases when its process
  ends, so that a killed run leaves nothing to clear.
- R4.4 THE SYSTEM SHALL keep the lock file outside the landing root.
- R4.5 THE SYSTEM SHALL let `load` and `audit` run without waiting for the lock.
- R4.6 WHEN `load` or `audit` runs while a writer holds the lock THE SYSTEM SHALL print a
  warning that a backfill is in progress and the result may be incomplete.

### R5. Audit

- R5.1 THE SYSTEM SHALL report in `front-office audit` anything under the landing root
  that is not a committed capture, as an error.
- R5.2 THE SYSTEM SHALL verify in the audit, for every sidecar that records one, that the
  payload's SHA-256 matches, and report a mismatch as an error.
- R5.3 THE SYSTEM SHALL report the number of items in quarantine, as a warning when it is
  not zero.

### R6. Moving what is already landed

- R6.1 THE SYSTEM SHALL provide a migration that moves every existing committed capture
  into the directory layout by rename alone, under the writer lock, with a dry-run mode.
- R6.2 THE SYSTEM SHALL record the migration in a journal, noting each capture when its
  move begins and again when it is complete, and SHALL be able to reverse the migration
  from it. The journal lives in a directory beside the landing root that is made
  git-ignored before the first record is written, wherever the root is.
- R6.6 WHEN the migration is interrupted THE SYSTEM SHALL, on being run again, first
  finish any capture the journal shows begun and not completed, from whatever state its
  files are in, and only then continue.
- R6.7 WHILE the landing zone is not wholly in the directory layout, because a migration
  was started and not finished, or was reversed, or because old-layout pairs are present
  with no migration at all, THE SYSTEM SHALL refuse to run a backfill or a sweep, saying
  that the migration must be run to completion first.
- R6.3 THE SYSTEM SHALL leave anything that is not a committed capture where it is during
  the migration, and report it.
- R6.4 WHEN the migration is run on a landing zone already in the directory layout THE
  SYSTEM SHALL do nothing.
- R6.5 THE SYSTEM SHALL move the committed fixtures by the same migration and write new
  fixtures in the directory layout.

## Expected values

Real landing zone, `data/raw/`, on 2026-10-05 after the settle-window refresh.

| Check | Expected | How to verify |
|---|---|---|
| Today, before this change | 5,118 committed captures (10,236 files); 201 payloads with no sidecar; 0 sidecars with no payload; 0 temporary files | `LandingZone.scan()` |
| The orphan, today | a failed sidecar write leaves 1 payload; the fetch logic says it does not need fetching; the loader inserts 0 | reproduced |
| The overwrite, today | a second write to one path replaces the payload with no error | reproduced; becomes a test expecting a collision error and the first capture intact |
| The rename this design relies on | onto a non-empty directory it fails; onto an empty directory it silently replaces it, so the writer checks first | reproduced on the landing zone's filesystem (btrfs) |
| Before the migration | #21 done: 0 payloads with no sidecar; 10,236 files; the owner's NAS backup of the old layout verified | scan; the owner's confirmation on #8 |
| Migration, dry run | 5,118 captures to move; 0 items left behind | `--dry-run` |
| Sweep dry run **before** the migration | refuses, naming the migration: the landing zone holds old-layout pairs (R6.7). Exit non-zero, nothing moved. This is the expected state of an unmigrated landing zone, not a failure | `front-office repair --dry-run` |
| After the migration | 5,118 capture directories, each with `payload.json` and `meta.json`; 10,236 files; 0 loose files | scan |
| Contents unchanged | every file's SHA-256 equals its entry in the manifest of 2026-10-05 (`59b4bf09…618f8c`) under its old path, through the recorded move list; no file missing or added | comparison script |
| Reversal | applied to a copy of the fixture tree, the reverse of the migration restores the original tree byte for byte | pytest |
| First sweep after the migration (dry run) | 0 items to move | `front-office repair --dry-run` |
| Raw table after rebuild | 5,118 rows, 5,118 distinct keys; every row equal to the current warehouse's in key, partitions and payload, and its `file_path` equal to the old one mapped through the journal | raw comparison in `verify_migration.py` |
| Warehouse comparison | every model relation identical between the current warehouse and the rebuilt one, compared exactly, with the same columns (builds are reproducible since #28) | `compare_warehouses.py --strict-columns`, no rounding |
| Fixtures | both committed trees in the directory layout; the gates and the isolation check pass | `.agentic/gates` |
| Fault injection | each failure point leaves the state in design.md's table; after the next run the entity is committed once and the landing root holds only captures | pytest, one case per point |
| Audit after all of it | exit 0, 0 errors, 0 warnings | `front-office audit --season 2026` |
