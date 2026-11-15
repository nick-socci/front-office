# The daily pipeline as Dagster assets — tasks

Issue: #217 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #217 during the build, and this file is not edited to show it.

1. Add the `orchestration` dependency group (`dagster`, `dagster-dbt`, `dagster-webserver`, locked),
   install it in `.agentic/gates` and `ci.yml`, add `orchestration/front_office_pipeline` to the
   wheel's packages, and make ruff and mypy cover `orchestration/` — `impl` — R1.1, R1.3, R4.1
   - Verify: `.agentic/gates` green with the group installed; `uv sync --locked` without it still
     installs the default groups; from the repository root, `dagster definitions validate -m
     front_office_pipeline` finds the module (against an empty `Definitions`).
2. Decide how `season.is_over` reads the settings status (`LandingZone`, or a CLI subcommand that
   prints it), record it in design.md, and write `season.py` with its tests first — `judgment` — R3.1, R3.3
   - Verify: the unit tests of the design's test table for R3.1 and R3.3 pass; the 2026 and 2025
     real settings give "over" (C3), run read-only against `data/` and recorded on #217.
3. Prove `dagster-dbt` on what C1 did not try: build a BigQuery-target manifest
   (`dbt parse --target bq`, `FO_BQ_PROJECT` named) and a DuckDB one, load each through
   `@dbt_assets`, and materialize one seed and one view for real on the `ci` target. If a load or
   a run fails, stop and bring ADR 0128's fallback to the owner — `judgment` — R1.3
   - Verify: asset count 80 on both manifests; one materialization records its events; recorded on #217.
4. Write `cli.py` (the subprocess call with the allowlist and privacy filter) and `settings.py` (the landing root and the warehouse), the six hand-written assets with
   `fetch_complete`, the dbt assets and translator, the `daily` job with `in_process_executor`, and
   the tests of the design's table for R1.1 to R1.4, R2.1 to R2.4, R3.2, R3.4 and R4.1, each
   written before its code — `impl` after task 3 (the failure rule, the filter and the settings are
   specified) — R1.1, R1.2, R1.4, R2.1 to R2.4, R3.2, R3.4, R3.5, R3.6, R4.1, R4.2
   - Verify: `uv run pytest orchestration` green; a test per requirement as the table states; the
     R2.1 test fails when the check is made blocking, and the R2.4 test fails when the filter is removed.
5. Run `daily` once on the laptop against the real season: `FO_WAREHOUSE=duckdb`, through
   `dagster job execute` and then through `dagster dev` to see the lineage — `judgment` — R4.1, R3.3
   - Verify: the "Expected values" rows for asset counts and for the run: every step succeeds, the
     dbt step passes as many nodes as a direct `dbt build --exclude-resource-type unit_test` just
     after; the UI's lineage reaches `raw_in_warehouse`; a screenshot of the lineage is described on
     #217 (not committed). No ESPN credential or member name appears in the run's events (grep the
     instance's SQLite for the patterns of `privacy.py`).
6. Run `daily` with `ESPN_S2=invalid` exported in the run's environment (a non-secret value;
   `load_dotenv` does not override it, so `.env` is untouched) — `judgment` — R2.1, R2.3
   - Verify: ESPN rejects the cookie (if it answers with something other than `AuthExpired`, record
     what, and what the check carries); `espn_captures` materialized with `fetch_complete` failed and
     the message as metadata, `mlb_captures`, `raw_in_warehouse` and the dbt assets ran, and the run is not reported
     as plainly successful; recorded on #217.
7. Measure the memory of the daemon and the UI idle, and of `daily` beside them, with these
   definitions, on arm64 (the `mothership` VM, or a container with its limit), summed PSS once a
   second as 0216's `measure.sh` did — `judgment` — R4.3
   - Verify: peak PSS recorded on #217 against R4.3's 2 GB, replacing that proposal with the number;
     over 2 GB goes to the owner before #218.
8. Update the README's roadmap line for sub-project 4 and AGENTS.md's Commands block with the
   orchestration group and the `dagster` commands — `impl` — R4.1
   - Verify: `.agentic/gates` green; the docs test that checks AGENTS.md's commands, if any, passes.
9. (last) Verify every acceptance criterion and expected value against real data — `judgment` — all
   - Verify: record the queries and results as a comment on #217: the asset counts, task 5's run,
     task 6's failure run, task 7's memory, and the season unit tests.
