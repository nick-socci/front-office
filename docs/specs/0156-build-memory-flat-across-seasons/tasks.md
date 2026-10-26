# A full build's memory does not grow with the captures loaded — tasks

Issue: #156 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #156 during the build, and this file is not edited to show it.

1. Baseline: build `main` from empty for each landing root (`data/raw_2026`, `data/raw`)
   with today's profile, keeping the warehouses for the comparisons of task 10 —
   `judgment` — R2.1, R3.2, R6.3
   - Verify: both builds pass (2 GB / 4 GB rungs, C3); the paths are recorded on #156.
2. `scripts/check_plan_shapes.py`'s pure parts and their pytest
   (`ingestion/tests/test_check_plan_shapes.py`): finding readers from a manifest, the
   heavy views from compiled SQL, gathering operators and their endpoints from a plan,
   and the register's checks, on small hand-written plans and manifests — `impl` —
   R4.1, R4.2, R4.4, R4.6
   - Verify: `uv run pytest ingestion/tests/test_check_plan_shapes.py`; each case of the
     design's test strategy for R4.2–R4.4 is a test, and fails if its check is removed.
3. The check's command line and `dbt/plan_shapes.yml` with the three exempt nodes and
   their measurements (C6, at four threads: 0.5 / 0.75 GB each); the gate step after
   "planted failures" in `.agentic/gates` and in `.github/workflows/ci.yml` — `impl` —
   R4.1, R4.3, R4.5
   - Verify: on `main`'s fixture build it fails, naming exactly the four unregistered
     nodes of R2 (C5, C13), and nothing else.
4. Rewrite `stg_espn__matchup_days` (the marker after a `group by`, C9) — `impl` — R2.1,
   R2.2
   - Verify: its unit tests pass; the check no longer names it; on eight seasons the
     comparison with task 1's warehouse is identical for it.
5. Rewrite `stg_espn__matchup_player_lines` (`newest` from `fo_capture_keys()`) —
   `impl` — R2.1, R2.2
   - Verify: as task 4.
6. Find a streaming shape of `stg_espn__player_game_stats` and of
   `stg_espn__matchup_player_lines_one_line_per_player` — `judgment` — R2.1, R2.2, R2.3
   - Verify: as task 4; if no shape gives the same rows, stop and bring R2.3's proposal to
     the owner.
7. The schedule's structure: `stg_raw__mlb_schedule` (R3.1), `stg_mlb__games` and
   `stg_mlb__games_prefers_played_over_unplayed` reading `dates[].games[]`, their unit
   test mocks, and `test_capture_glob.py` for the new structure — `impl` — R3.1, R3.2,
   R3.3, R3.4
   - Verify: unit tests and `test_capture_glob.py` pass; the check reads the schedule's
     readers and names none of them; the comparison is identical for `stg_mlb__games`;
     R3.4's comparison of the view's games is equal on both roots.
8. The `dev` profile: `threads: 1`, `settings: {threads: 4}`, with its comment — `impl` —
   R1.1, R1.2
   - Verify: `dbt debug` shows 1 thread for `dev`; the `ci` and `bq` targets' text is
     unchanged.
9. AGENTS.md, *dbt gotchas* — `impl` — R5.1
   - Verify: the bullet names both shapes, the check and its register, and ADR 0100.
10. The BigQuery check of AGENTS.md (`dbt run --target bq --selector bigquery_slice
    --empty` and `dbt test`, with a `fo_schema_suffix`), then the slice on 2026 against
    the same build of `main` — `judgment` — R3.5
    - Verify: both empty runs pass; `compare_bigquery_slice.py` equal; billed bytes
      within 5%.
11. (last) Verify every acceptance criterion and expected value against the real season —
    `judgment` — all
    - Verify: the ladder (`probes/ladder.sh`) for both roots with the committed profile;
      `scripts/compare_warehouses.py --strict-columns` of each against task 1's warehouse,
      excluding only the schedule view's `payload` and `dates`, and R3.4's comparison; the plan check
      on fixtures; `.agentic/gates`. Record the commands and results on #156. If eight
      seasons does not reach 2026's rung, stop and bring the failing nodes to the owner.
