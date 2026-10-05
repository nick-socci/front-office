# Committed captures — tasks

Issue: #29 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #29 during the build, and this file is not edited to show
them.

1. Confirm the starting point — `judgment` — R3
   - #21 done (0 payloads with no sidecar), or the owner has said to proceed without it.
     Record the scan counts.
   - Verify: `LandingZone.scan()` counts posted on #29.
2. Publish without replacing; record size and checksum — `impl` — R1.1–R1.3, R1.5, R1.6
   - pytest first: publish order, the three collision cases, size and SHA-256, and the
     five-step fault-injection matrix up to "what is left on disk".
   - Verify: `uv run pytest ingestion/tests/test_landing.py`; ruff; mypy.
3. One definition of committed, used by every reader — `impl` — R2.1–R2.8
   - `LandingZone.check` (shallow and deep) with the audit's path-agreement rule moved
     into it; `LandingZone.committed`; `has_landed` and `iter_landed` rebuilt on it; the
     two `_has_landed` helpers removed; `scan` gains `invalid`; readers tolerate a
     vanished file; the loader fails on an unparseable committed payload.
   - Verify: pytest, including "a settled game with a lone payload needs fetching" and
     "`needs_fetch` reads no payload".
4. The sweep and the writer lock — `impl` — R3.1–R3.3, R4.1–R4.4
   - pytest first: each kind moved with its relative path; never overwritten; dry run;
     a second writer refused; the lock free after the holder is killed; `deep` mode.
     The sweep writes an ignore-everything file into the quarantine first; test with an
     arbitrary landing root inside a git work tree. Add `data/raw_quarantine/` and
     `data/*.lock` to `.gitignore`.
   - Verify: pytest.
5. Wire the CLI and the backfill loops — `impl` — R1.4, R3.4, R3.5, R4.1, R4.2, R4.5
   - `backfill` takes the lock, sweeps, fetches; a collision stops the run;
     `front-office repair [--dry-run] [--deep]`. Complete the fault-injection matrix
     from design.md: each failure point's stated disk state, then the second run.
   - Verify: pytest; `front-office repair --help`.
6. Audit: checksum, quarantine — `impl` — R5.1–R5.3
   - Verify: pytest.
7. Dry-run the sweep on the real landing zone — `judgment` — R3.5
   - `front-office repair --dry-run` only. Show the owner the list before any backfill
     runs with the new code.
   - Verify: 0 files after #21 (or exactly the 201); posted on #29.
8. Update the README and AGENTS.md — `impl` — all
   - What a committed capture is, the lock, the quarantine and that nothing is deleted.
   - Verify: `.agentic/gates` green.
9. Verify every acceptance criterion and expected value against real data — `judgment` — all
   - Read-only on the real landing zone: 5,118 committed, equal to the raw table's rows;
     audit result. No real fetch is needed to verify this change.
   - Verify: record the commands and results as a comment on #29.
