# A roster period settles after ESPN's counter stops — tasks

Issue: #75 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #75 during the build, and this file is not edited to show
them. No task runs anything against ESPN.

1. Record the starting point — `judgment` — expected values (2026 rows)
   - On the real landing zone, read-only: the count of committed roster captures, the
     greatest counter by period, the periods closed and not settled, and the roster lines
     of `front-office audit`. Post them on #75.
   - Verify: they match the first four rows of the expected values. If they do not, stop:
     the spec was written against a different landing zone.
2. `PeriodEvidence` and the extended counter — `impl` — R1.1, R1.3, R1.4, R1.5, R1.6, R1.9
   - pytest first, on plain sidecar dicts: the R1.3, R1.4/R1.5, R1.6 and R1.9 rows of
     the test strategy. The existing boundary tests stay as they are and must still pass.
   - Then: sightings, `PeriodEvidence`, `settled_through` returning it, `is_closed` and
     `is_settled` reading `latest` and `extended`.
   - Verify: `uv run pytest ingestion/tests/test_espn.py`; ruff; mypy.
3. The fetch path — `impl` — R1.2, R1.7, R1.8
   - pytest first, fake transport: the 2022 shape replayed day by day, parametrised with
     the 2020 and 2024 shapes; the season landed in one run; the in-run rebuild. Confirm
     the replay fails on the current code before changing it, and say so on #75.
   - Then: `backfill_rosters` keeps sightings per period and rebuilds the evidence after
     each fetch.
   - Verify: `uv run pytest ingestion/tests`; the nine-daily-runs test and the "payload
     reads raise" tests pass unmodified.
4. The audit — `impl` — R2.1, R2.2, R2.3
   - pytest first: the three audit cases of the test strategy; the existing re-check
     tests pass unmodified.
   - Then: `unclosed_season` reads `.latest`; the re-check line gains its clause.
   - Verify: `uv run pytest ingestion/tests/test_audit.py`.
5. The record — `impl` — R3.1
   - The module docstring of `espn/rosters.py` describes the extension and cites ADR
     0047 beside ADR 0018.
   - Verify: `.agentic/gates`.
6. (last) Verify every acceptance criterion and expected value against real data —
   `judgment` — all
   - On the real landing zone, read-only: repeat task 1 on the built code. 180 of 180
     periods settled, no period closed and unsettled, and the audit's roster lines
     identical to task 1's.
   - State on #75 that the new path has no real capture to run on (design, *Risks*), and
     which constructed cases stand in for it.
   - Verify: record the commands and their output as a comment on #75.
