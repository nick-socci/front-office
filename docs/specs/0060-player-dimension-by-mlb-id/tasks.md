# The player dimension is keyed by MLB id — tasks

Issue: #60 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #60 during the build, and this file is not edited to show
them.

The first commit of the build accepts ADRs 0033 to 0036 and marks ADR 0012 as amended
by 0033, in the ADRs and in the index.

1. Record the starting point — `judgment` — expected values
   - On the real season, copy `dim_players`, `dim_player_league_seasons` and the three
     facts to a scratch database outside the repo; record their row counts. In CI, the
     build's counts and warnings, and the counts in the CI table of the expected values.
   - Build the multi-league fixture once and query whether any platform player has two
     MLB ids across its league-seasons (the open question on R2.3).
   - Verify: the "now" column posted on #60. A count that differs from the spec is
     reported with its cause before anything is changed.
2. The player-list ingestion, tests first — `impl` — R5.1–R5.6
   - `test_mlb_players.py`, the audit case and the loader case, seen to fail; then
     `mlb/players.py`, the `backfill mlb` step and `--only players`, the audit finding.
   - Verify: `uv run pytest`, `uv run ruff check`, `uv run mypy` pass.
3. Land and load the 2026 list — `judgment` — R5.1, the real season
   - With the owner's go-ahead from the spec PR: `front-office backfill mlb --season
     2026 --only players`, `front-office audit`, `front-office load`.
   - Verify: one committed `mlb/players` capture for 2026; the audit has no new error;
     the people count posted on #60 against the probe's 1,511.
4. Fixtures — `impl` — R7.1, R7.2
   - The generators' test cases first; then `build_mlb_players` and the 2027 capture;
     regenerate both fixture roots with the scripts, never by hand.
   - Verify: the fixture tests pass; `git diff --stat fixtures/` shows only new
     `mlb/players` captures; the fixture list holds only allowlisted keys.
5. `stg_mlb__players`, tests first — `impl` — R6.1–R6.3
   - The unit test and the YAML, seen to fail; then the model.
   - Verify: `dbt build --target ci --select stg_mlb__players` passes;
     `test_dbt_json_rule.py` passes.
6. The dimension's tests — `impl` — R1.1–R1.7, R2.2, R4.2–R4.4
   - The unit test (nine cases), the singular test of R4.2, the YAML for the new columns
     and key, the `relationships` test from `dim_player_league_seasons.mlbam_player_id`.
     Remove the singular test and unit test named in R4.4.
   - Verify: `dbt build --target ci --select dim_players` fails on the missing columns.
7. The dimension — `impl` — R1.1–R1.7, R2.4
   - Rewrite `dim_players.sql` with its header comment; update the YAML description and
     the stale comment lines in `dim_player_league_seasons.sql` and
     `fo_replacement_group.sql`.
   - Verify: `dbt build --target ci --select dim_players dim_player_league_seasons`
     passes; `git diff` shows no change to `dim_player_league_seasons.sql` outside
     comments.
8. The warning test — `impl` — R2.3
   - `dim_player_league_seasons_a_player_keeps_one_mlb_id.sql`, `severity: warn`.
   - Verify: it runs and returns what task 1 measured.
9. The facts' tests, then the facts — `impl` — R3.1–R3.4
   - First the unit-test expectations, the YAML (`mlbam_player_id` and its
     `relationships` test; the one-column `platform_player_id` test removed) and the
     singular test of R3.4, seen to fail on the missing column; then the three models.
   - Verify: `dbt build --target ci --select fct_player_category_value
     fct_player_season_value fct_transaction_impact` passes; `git diff` shows each
     fact's select list changed only by one appended column.
10. The isolation script's comment — `impl` — R4.1
    - Verify: `uv run python scripts/check_tenant_isolation.py` reports 0 differing
      pairs; `git diff` shows no logic change in the script.
11. (last) Verify — `judgment` — all requirements, expected values
    - `.agentic/gates`. On the real season, `dbt build --select stg_mlb__players+
      dim_player_league_seasons+`, then every row of the expected values, with the
      `except all` comparisons against task 1's copies.
    - Verify: the table of expected against measured, as a comment on #60. A count that
      differs is reported with its cause before the PR is opened.
