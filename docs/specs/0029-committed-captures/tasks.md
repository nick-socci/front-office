# Committed captures — tasks

Issue: #29 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #29 during the build, and this file is not edited to show
them.

1. Confirm the starting point — `judgment` — R6
   - The owner's NAS backup of the current layout is verified (#20) and #21 is done: 0
     payloads with no sidecar. Record the scan counts and the manifest's checksum on #29.
   - Verify: 5,118 committed, 0 other; posted on #29.
2. Write a capture as a directory, published by one rename — `impl` — R1.1–R1.3, R1.5, R1.6
   - pytest first: the directory and its two files; the final name absent during the
     write; collision on an existing directory, empty or not; size and SHA-256; the
     fault-injection matrix up to "what is left on disk".
   - Verify: `uv run pytest ingestion/tests/test_landing.py`; ruff; mypy.
3. One definition of committed, used by every reader — `impl` — R2.1–R2.8
   - `LandingZone.check` (shallow and deep) with the audit's path-agreement rule moved
     into it; `committed`; `has_landed` and `iter_landed` rebuilt on it; the two
     `_has_landed` helpers removed; `scan` with the new kinds; readers tolerate a
     vanished entry; the loader fails on an unparseable committed payload.
   - Verify: pytest, including "`needs_fetch` reads no payload".
4. The sweep, its limit and the writer lock — `impl` — R3.1–R3.3, R3.6, R4.1–R4.4
   - pytest first: each kind moved whole with its relative path, empty directories
     included; never overwritten; dry
     run; `deep`; the size limit and `force`; the ignore file under an arbitrary root; a
     second writer refused; the lock free after the holder is killed; a writer not
     refused by a reader's probe. Add the three `.gitignore` entries.
   - Verify: pytest.
5. Wire the CLI and the backfill loops — `impl` — R1.4, R3.4, R3.5, R4.1, R4.2, R4.5, R4.6
   - `backfill` takes the lock, sweeps, fetches; a collision or an over-large sweep stops
     the run; `front-office repair`; `load` and `audit` warn when a writer is active.
     Complete the fault-injection matrix with the second run.
   - Verify: pytest; `front-office repair --help`.
6. Audit: the shared check, checksums, quarantine — `impl` — R5.1–R5.3
   - Verify: pytest.
7. The migration script and its verifier — `impl` — R6.1–R6.4, R6.6, R6.7
   - pytest first: moves by rename only with contents unchanged; a lone payload left and
     reported; dry run; the begin/done journal in an ignored directory; resumption after
     a kill at each of a capture's four steps; reversal from a finished and from each
     interrupted state; a second run does nothing; `backfill` and `repair` refuse while
     a migration is unfinished. `scripts/verify_migration.py` (files and raw rows);
     `compare_warehouses.py --strict-columns`.
   - Verify: pytest.
8. Move the fixtures and update the generators — `impl` — R6.5
   - Run the migration on `fixtures/landing` and `fixtures/landing_multi` (their journals
     are ignored and not committed); both generators read and write the new layout;
     `make_multi_fixtures.py` reproduces its tree byte for byte; the privacy test and the
     pre-commit guard still cover every ESPN payload. The lead runs `make_fixtures.py`
     against a migrated reflink copy of `data/raw/` in an ignored directory, reports any
     difference from the committed base fixture, and removes the copy.
   - Verify: `.agentic/gates` green, including the isolation check.
9. Update the README, AGENTS.md and the module docstrings — `impl` — all
   - The layout, what a committed capture is, the lock, the quarantine, the migration and
     that nothing is deleted.
   - Verify: `.agentic/gates` green.
10. Dry-run the migration on the real landing zone — `judgment` — R6.1
    - `migrate_landing_layout.py --dry-run` only. Show the owner the list and wait.
      (`front-office repair --dry-run` at this point is expected to refuse: an
      unmigrated landing zone is some 10,236 loose files, far over the sweep's limit.)
    - Verify: 5,118 captures to move, 0 left behind; posted on #29.
11. Migrate the real landing zone and verify it — `judgment` — R6.1, R6.2
    - With the owner's go-ahead. Then `verify_migration.py` against the manifest, and
      `make_fixtures.py` against the real root.
    - Verify: the journal is finished; every manifest line accounted for; 5,118 capture
      directories; `front-office repair --dry-run` lists nothing; the audit's landing
      section is clean.
12. Rebuild the warehouse beside the old one and compare — `judgment` — all
    - The three commands in design.md. Do not rename, replace or delete either file.
    - Verify: 5,118 raw rows, each equal to the current warehouse's through the journal;
      every model relation identical with `--strict-columns`, compared exactly; on #29.
13. Verify every acceptance criterion and expected value against real data — `judgment` — all
    - Verify: record the commands and results as a comment on #29. The owner swaps the
      warehouse files and refreshes the NAS backup.
