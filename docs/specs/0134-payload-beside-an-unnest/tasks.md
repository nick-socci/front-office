# Rule 1 is checked: no payload is carried into an unnest — tasks

Issue: #134 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #134 during the build, and this file is not edited to show it.

1. Write the unit tests of design.md's *Test strategy* in
   `ingestion/tests/test_check_plan_shapes.py`, against the functions named in *Detailed
   design*. Forms (a) to (g) and the four passing forms are explained in an in-memory
   DuckDB over a table with a JSON `payload` column and a `fetched_at` column (C7). Each
   test's docstring says what it catches, as the existing ones do. — `impl` — R1.1–R1.4,
   R2.1–R2.7, R3.1, R4.1–R4.3
   - Verify: `uv run pytest ingestion/tests/test_check_plan_shapes.py` fails on the new
     tests only (the functions do not exist yet), and the existing tests pass.
2. Implement `payload_views`, `_projections`, `_is_unnest`, `_is_join`, `_emits`,
   `payload_carries`, `payload_problems`, `uncovered_pairs`, `missing_payload_column` and
   the probes in `scripts/check_plan_shapes.py`, and wire them into `main()`: register the solver, explain
   the union of heavy and payload readers once each, and extend the summary line. Update
   the module docstring. — `impl` — R1, R2, R3
   - Verify: `uv run pytest ingestion/tests/test_check_plan_shapes.py` passes; `uv run ruff
     check && uv run ruff format --check` pass.
3. Run the check on the fixture build and compare it with the ledger. — `judgment` — R1–R3,
   expected values
   - Verify: after `.agentic/gates` has built `dbt/ci.duckdb`, `uv run python
     scripts/check_plan_shapes.py --db dbt/ci.duckdb` exits 0 and reports 7 payload views,
     142 payload readers, 211 unnest operators and no node that cannot be explained (C5).
     Any difference is explained before going on.
4. Show the gate fails on a real model, then put the model back. — `judgment` — R2.2, issue's
   *Done when*
   - Verify: on a scratch copy of `stg_espn__teams.sql`, move `league_id` and `season` out
     of `header` and into the unnesting SELECT, reading `header.payload` (the form before
     #135). Rebuild the fixture warehouse and run the check: it fails, naming
     `stg_espn__teams` and `teams`. Do the same with `stg_espn__scoring_categories` as it
     was at fe591f1: `fo_unnest(fo_json_array('latest.payload', …), 'item')` beside the
     payload fields. It fails, naming the node and `settings`. (`stg_mlb__games`' fe591f1
     form cannot be written any more: its view has no payload since #156. Its shape is
     form (c) of the unit tests.) Restore both files. Record the two failure messages on
     #134. Nothing is committed from this task.
5. Update AGENTS.md rule 1, the step name in `.agentic/gates` and `.github/workflows/ci.yml`,
   and the header comment of `dbt/plan_shapes.yml`. — `impl` — R5.1, R5.2
   - Verify: `uv run pytest ingestion/tests/test_ci_workflow.py ingestion/tests/test_readme.py`
     passes.
6. Run the full gates and time the plan-shapes step before and after. — `impl` — all
   - Verify: `.agentic/gates` passes; the step's time on `main` and on the branch are
     recorded on #134 (design.md, *Open questions*).
7. (last) Verify against the real season. — `judgment` — expected values
   - Verify: confirm `git diff --stat main -- dbt/models dbt/macros dbt/tests` is empty, so
     the real warehouse is unchanged by construction. Then, against a current real-season
     warehouse (built from `main` after #150; `data/warehouse.duckdb` of 2026-10-11 is too
     old, C10), run `cd dbt && DBT_PROFILES_DIR=. uv run dbt compile --target dev --target-path
     <scratch>` and `uv run python scripts/check_plan_shapes.py --db <that warehouse>
     --manifest <scratch>/manifest.json --project-dir dbt`. Expected: exit 0, no payload
     carry, no node that cannot be explained. If no current real build exists, post the
     exact pending command and the expected result on #134 and report the work as awaiting
     this check (AGENTS.md).
