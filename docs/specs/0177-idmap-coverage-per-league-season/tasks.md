# The id-map coverage test judges each league-season by its share of started players — tasks

Issue: #177 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #177 during the build, and this file is not edited to show it.

1. Write `dbt/plants/stg_idmap__covers_started_players.yml` with the four plants of
   design.md (`map_misses_more_than_a_twentieth`, `map_misses_exactly_a_twentieth`,
   `map_is_empty`, `a_healthy_league_season_does_not_dilute_another`). Each materializes
   `staging.stg_idmap__players` (see the design's 2026-10-21 amendment), and
   picks among started players with counts computed from the fixture — `impl` — R3.1,
   R3.2, R3.3, R3.4, R1.3
   - Verify: `uv run python scripts/check_plants.py --db dbt/ci.duckdb` after a CI build
     fails on this file against today's test, because it lists players, not league-seasons.
     That failure is expected; record its output on #177.
2. Rewrite `dbt/tests/stg_idmap__covers_started_players.sql` as in design.md: started by
   the seed's `is_starting_slot`, one row per league-season over 5%, integer comparison,
   `severity='error'` with no `warn_if` / `error_if`, and the header of R2.3 — `impl` —
   R1.1, R1.2, R1.3, R2.1, R2.2, R2.3, R4.1
   - Verify: the CI build passes the test with 0 rows, and `check_plants.py` passes all
     three plants.
3. Reword the clause "the nine players the crosswalk test warns about" in the header of
   `int_fantasy__roster_days.sql` so it no longer says the test warns. Comment only —
   `impl` — R2.3
   - Verify: `git diff` touches comment lines only.
4. Run `.agentic/gates`, and compile the test for BigQuery
   (`cd dbt && FO_BQ_PROJECT=<project> DBT_PROFILES_DIR=. uv run dbt compile --target bq --select stg_idmap__covers_started_players`,
   with the project named explicitly) — `impl` — R4.1
   - Verify: `All gates passed.` (portable-SQL rule, plants). The
     compiled SQL is shown on #177.
5. (last) Verify every acceptance criterion and expected value against the real season —
   `judgment` — all
   - On the eight-season warehouse:
     `cd dbt && DBT_PROFILES_DIR=. uv run dbt build --select stg_idmap__covers_started_players`
     gives `PASS` with no warning, and the full build reports one warning fewer than `main`. The C2 query gives the shares in requirements.md
     *Expected values* (max 9 of 481).
   - Record the commands and results as a comment on #177.
