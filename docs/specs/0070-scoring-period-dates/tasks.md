# Scoring-period dates — tasks

Issue: #70 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #70 during the build, and this file is not edited to show
them.

1. Record the starting point — `judgment` — expected values
   - Copy `data/warehouse.duckdb` to `data/warehouse_pre70.duckdb` (local, gitignored).
     Do not run `front-office load`.
   - Post on #70: the 180 rows' first and last dates, the game counts, and the audit's
     `loaded` and `espn` sections as they are.
   - Verify: matches the first two rows of the expected values.
2. Unit tests for the model — `impl` — R1.1–R1.6, R5.1–R5.3
   - In `dbt/models/staging/espn/_espn__models.yml`: replace
     `scoring_period_dates_use_the_eastern_day_boundary`, give
     `scoring_periods_run_to_each_leagues_own_final_period` its `stg_mlb__games` input,
     and add the three tests of R5.3. Each description says what it catches.
   - Verify: `dbt test --target ci --select stg_espn__scoring_periods,test_type:unit`
     fails on the new tests against the current model, for the stated reason.
3. The game-line tests — `impl` — R3.1, R3.4, R3.5
   - `dbt/tests/stg_espn__scoring_periods_agree_with_espn_game_lines.sql`, as in the
     design, with a header saying what it catches, that it compares counts, and that it
     is empty-handed in CI.
   - `dbt/tests/stg_espn__scoring_periods_have_game_lines_to_check.sql`, `severity:
     warn`, driven from league-seasons that have rows in `stg_espn__roster_entries`.
   - Verify: on the real warehouse, before the model changes, both return 0 rows; with
     `scoring_date + 1` substituted by hand in a scratch query the first returns 63. In
     CI the second returns 2 rows and the build still passes.
4. The model — `impl` — R1.1–R1.6, R2.1, R2.2, R3.2
   - Rewrite `stg_espn__scoring_periods.sql` as in the design, with its header. Describe
     `latest_scoring_period` in the YAML and add `not_null` to `final_scoring_period`
     (R2.2). Rewrite the header of
     `stg_espn__scoring_periods_start_on_opening_day.sql`; its SQL does not change.
   - Verify: `dbt build --target ci --vars '{anonymize: true}'` passes, with periods 1
     and 2 on 2026-04-29 and 2026-04-30.
5. The audit — `impl` — R4.1–R4.8, R5.4
   - pytest first, seen to fail; then opening day in `check_mlb` and the anchor block of
     `_check_league`, as in the design.
   - Verify: `uv run pytest ingestion/tests/test_audit.py`; ruff and mypy clean.
6. Describe it — `impl` — R2.1, R3.2
   - The stale comment on `FIXTURE_FETCHED_AT` in `scripts/make_fixtures.py`; the model
     description in the YAML; any sentence in `README.md` or `docs/README.md` that says
     dates are anchored on a settings capture.
   - Verify: `git diff --stat main` shows nothing under `fixtures/` or `dbt/seeds/`;
     `.agentic/gates` passes.
7. (last) Verify against the real season — `judgment` — all, expected values
   - Same load: build `stg_espn__scoring_periods+` on the real warehouse and compare the
     model with `warehouse_pre70.duckdb`, `EXCEPT` both ways. Run the shifted queries.
     Count `rec_espn__player_day_differences` (22 before).
   - Then `uv run front-office load`, a full `dbt build`, and the audit. Compare the
     model again. List which mart totals moved and by how much, for the owner.
   - Verify: every row of the expected values, recorded as a comment on #70. If the 180
     rows differ at either step, stop before the next one.
