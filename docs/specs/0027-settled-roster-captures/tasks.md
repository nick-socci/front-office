# Settled roster captures — tasks

Issue: #27 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #27 during the build, and this file is not edited to show
them.

1. Record the starting point — `judgment` — expected values
   - On the real landing zone: 180 committed roster captures, none with `source_status`;
     the audit's roster line. Post both on #27.
   - Verify: matches the first and fourth rows of the expected values.
2. An optional `source_status` on `LandingZone.write` — `impl` — R1.3, R1.4
   - pytest first: given, the sidecar holds a copy under `source_status`; not given, the
     sidecar's key set is today's; captures with, without and with a malformed value all
     pass `check`.
   - Verify: `uv run pytest ingestion/tests/test_landing.py ingestion/tests/test_landing_check.py`; ruff; mypy.
3. The roster fetcher records the response's status — `impl` — R1.1, R1.2
   - pytest first, fake transport: the two numbers come from the roster response, not
     the run's status; no `status`, a string counter and a boolean counter land with null
     and a warning.
   - Verify: `uv run pytest ingestion/tests/test_espn.py`.
4. `settled_through` and `is_settled` — `impl` — R2.1, R2.2, R2.7, R3.1, R3.2, R3.4
   - pytest first, on plain dicts: own status past, at and below the period; two captures
     of one period; legacy with and without same-run settings; key present but null does
     not fall back.
   - Verify: `uv run pytest ingestion/tests/test_espn.py`.
5. The fetch path uses the evidence — `impl` — R2.3–R2.7, R3.3, R4.1, R5.1, R5.2
   - pytest first: delete `test_roster_is_skipped_once_its_period_is_over` and
     `test_period_is_over`; add the transition, outage, lagging-status and cross-league
     tests from design.md; re-point the two roster tests in `test_landing_check.py` at
     the new signature, keeping "roster payload reads raise"; settings payloads without a
     legacy stamp raise when read.
   - Then: the evidence pass in `backfill_rosters`, the pure `needs_fetch`,
     `summary.unsettled`, `period_is_over` removed, and the command's stderr line and
     exit code.
   - Verify: `uv run pytest ingestion/tests`; ruff; mypy.
6. The audit calls the same function — `impl` — R4.2
   - pytest first: one new test where the evidence is `source_status` and no settings
     capture shares the run; the existing roster-finality tests pass unchanged.
   - Verify: `uv run pytest ingestion/tests/test_audit.py`.
7. Describe it — `impl` — goals
   - `espn/rosters.py` module docstring; the README's capture paragraph gains one
     sentence on `source_status`; no status tables.
   - Verify: `.agentic/gates`.
8. (last) Verify against the real season, reading only — `judgment` — all
   - The evidence function over the real landing zone: 180 settled, 0 missing, 0 without
     evidence; the fetch decision says 0 of 180; the audit's roster line is unchanged;
     the one-off payload cross-check (latest 186 in all 180); `git diff --stat main`
     shows nothing under `dbt/` or `fixtures/`.
   - No request is made to ESPN. A live `backfill-espn` is the owner's to run; expected
     output is `rosters: fetched=0 skipped=180 failed=0`, and its settings, teams,
     matchups and transactions captures land as on any run.
   - Verify: commands and results posted as a comment on #27.
