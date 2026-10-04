# League and season identity through raw storage and every model — tasks

Issue: #28 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #28 during the build, and this file is not edited to show
them.

1. Add `request_path` and `partitions` to the raw table and key — `impl` — R1.1–R1.5, R1.7, R5.4
   - pytest first: the path function on every real URL shape; 4 captures → 4 rows; a
     collision fails naming both files; an old-shaped table is refused; a rerun inserts
     nothing. Update the dbt `sources:` YAML.
   - Verify: `uv run pytest`; `ruff`; `mypy`.
2. Make the audit compare on the full key — `impl` — R1.6
   - Verify: `uv run pytest ingestion/tests/test_audit.py`; `front-office audit --season
     2026` against a freshly loaded scratch warehouse reports what it reports today.
3. Select the latest response per league and season — `impl` — R2.1–R2.3
   - dbt unit tests first (two leagues through the macro; two transaction runs). Add the
     payload-identity singular test.
   - Verify: fixture build green; staging row counts unchanged on the fixture.
4. Give `stg_espn__transactions` its league and season; scope scoring periods — `impl` — R3.1–R3.3
   - Scope `stg_espn__scoring_periods_start_on_opening_day` to each season's own first
     MLB game.
   - Verify: fixture build green; uniqueness tests on full keys pass.
5. Carry league and season through the three models; split the player dimension — `impl` — R4.1–R4.3, R4.6–R4.9
   - dbt unit tests first: two leagues of different sizes for the pools; a short season
     for the window; a position-less player whose role differs between two seasons; a
     player in two leagues and two seasons with one `dim_players` row. Uniqueness on full
     keys; the relationships test. Grep for every reader of the five moved columns and
     point each at `dim_player_league_seasons`. Move the two singular `dim_players_*`
     tests that are about league-season attributes.
   - Verify: fixture build green; fixture row counts unchanged.
6. Generate the combined fixture — `impl` — R5.1, R5.2
   - `scripts/make_multi_fixtures.py` from `fixtures/landing/` only; pytest that it
     reproduces the committed tree; the privacy test scans the new root.
   - Verify: `uv run pytest`; `.agentic/pre-commit-guard` passes.
7. Build the isolation check and the warehouse comparison — `impl` — R5.3, R6.1
   - pytest first for the diff function (changed value, missing row, added column,
     missing relation, equal counts with different duplicates). Make the `ci` target's
     path `env_var('FO_CI_DUCKDB_PATH', 'ci.duckdb')`. Single builds load only their
     own season's MLB folders.
   - Verify: the check runs and prints a per-relation, per-league-season report.
8. Work the isolation report to zero — `judgment` — R4.4, R4.5
   - Each differing relation is a missing league or season in a join, window or group.
     Fix the model; delegate mechanical ones. Anything needing more is an amendment, and
     a grain or meaning question goes to the owner.
   - Verify: the check reports 0 differences for 4 league-seasons; recorded on #28.
9. Add the check to the gates and CI; document the rebuild — `impl` — R5.3, R6
   - `.agentic/gates`, `.github/workflows/ci.yml`, README section with the three
     commands. Report the added gate time.
   - Verify: `.agentic/gates` green.
10. Rebuild the real warehouse beside the old one and compare — `judgment` — R6.2
    - Run the three commands. Do not rename, replace or delete either file.
    - Verify: 2,688 raw rows; 0 relations differing in a shared column; the five columns
      of `dim_player_league_seasons` equal today's `dim_players` columns for all 498
      players; results on #28.
11. Verify every acceptance criterion and expected value against real data — `judgment` — all
    - Verify: record the queries and results as a comment on #28. The owner swaps the
      warehouse files.
