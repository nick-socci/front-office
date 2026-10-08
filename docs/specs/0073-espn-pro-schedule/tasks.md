# ESPN's pro schedule — tasks

Issue: #73 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #73 during the build, and this file is not edited to show
them.

The first commit of the build accepts ADRs 0023 and 0024 and sets ADR 0021 to
`superseded by 0023`, in the file and in the index.

1. Record the starting point — `judgment` — expected values
   - Copy `data/warehouse.duckdb` to `data/warehouse_pre73.duckdb`, and save the 180
     rows of `stg_espn__scoring_periods` as a table in a gitignored `.duckdb` file (the
     model is a view; see the amendment of spec 0070).
   - Verify: 180 rows, 2026-03-25 to 2026-09-20, posted on #73.
2. Fetch the pro schedule — `impl` — R1.1–R1.6, R7.1
   - pytest first, with a fake transport, seen to fail. Then `game_url` and
     `espn_public_client` in `espn/client.py`, `espn/pro_schedule.py`, and `--only
     pro-schedule` and the first step of the run in `cli.py`.
   - Verify: `uv run pytest`, ruff, mypy. No request to ESPN.
3. Land the 2026 schedule — `judgment` — expected values
   - One unauthenticated request: `uv run front-office backfill espn --season 2026 --only
     pro-schedule`. Nothing else is fetched.
   - Verify: one committed capture under `data/raw/espn/pro_schedule/season=2026/`; the
     first six expected values, read from its payload, posted on #73.
4. Fixtures and isolation — `impl` — R6.1–R6.4
   - `build_espn_pro_schedule` in `scripts/make_fixtures.py`; the 2026 copy and the 2027
     derivation in `scripts/make_multi_fixtures.py`; `copy_single` in
     `scripts/check_tenant_isolation.py`; regenerate both fixture trees.
   - Verify: `git status fixtures` shows only new `pro_schedule` directories. If any
     existing fixture file changed, stop and report the diff. Periods 1 and 2 hold 15
     and 11 games on 2026-04-29 and 2026-04-30. The fixture privacy test passes.
5. Stage the games — `impl` — R2.1–R2.6, R7.2
   - Unit tests and YAML tests first, then `stg_espn__pro_games.sql` with its header, then
     `stg_espn__pro_games_fall_on_one_date_per_scoring_period.sql`.
   - Verify: `dbt build --target ci --vars '{anonymize: true}' --select
     stg_espn__pro_games` passes; the unit tests failed before the model existed in the
     way stated.
6. Date periods from the schedule — `impl` — R3.1–R3.5, R4.1–R4.4, R7.3
   - Replace the unit tests of `stg_espn__scoring_periods` (seen to fail against the
     model as it is), then the model and its header, the header of the opening-day test,
     and `stg_espn__player_game_stats_games_are_scheduled.sql`.
   - Verify: the full CI build passes with periods 1 and 2 on 2026-04-29 and 2026-04-30
     and 6 warnings; the model has no `ref` to `stg_mlb__games`.
7. The audit — `impl` — R5.1–R5.5, R7.4
   - pytest first, seen to fail; then `check_espn` and `_check_league`.
   - Verify: `uv run pytest ingestion/tests/test_audit.py`; ruff and mypy clean.
8. Describe it — `impl` — R4.1
   - The ESPN row of the model table and the ingestion paragraph in `README.md`; the
     model descriptions in the YAML; the comment on the fixture stamp in
     `scripts/make_fixtures.py`, which mentions ADR 0021.
   - Verify: `.agentic/gates` passes, isolation at 0 differing pairs.
9. (last) Verify against the real season — `judgment` — all, expected values
   - `uv run front-office load`, a full `dbt build`, the audit. Compare the 180 rows with
     the saved ones, `EXCEPT` both ways, and every other built table with
     `warehouse_pre73.duckdb` as multisets apart from `fetched_at`.
   - Verify: every row of the expected values, recorded as a comment on #73. If the 180
     rows differ, or the one-date test or the scheduled-games test returns a row, stop
     and take it to the owner.
