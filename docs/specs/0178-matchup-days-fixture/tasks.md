# The CI fixtures carry ESPN matchup-days captures of their own matchups — tasks

Issue: #178 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #178 during the build, and this file is not edited to show it.

1. Write the unit tests for the side rebuild and for the two generation checks, in
   `ingestion/tests/test_make_fixtures.py` (design.md, *Tests*). They must fail, because
   the functions do not exist yet. — `impl` — R1.3, R1.4, R1.6, R1.7
   - Verify: `uv run pytest ingestion/tests/test_make_fixtures.py -k matchup_day` fails on
     the missing names only.
2. Add the allowlist constants, `rebuild_matchup_day_side`,
   `check_matchup_days_match_the_matchups_fixture` and `build_espn_matchup_days` to
   `scripts/make_fixtures.py`. `main()` runs the check with the other checks and the
   builder after `build_espn_matchups()`. — `impl` — R1.1 to R1.7
   - Verify: task 1's tests pass; `uv run mypy`; `uv run ruff check`.
3. Regenerate `fixtures/landing` (`uv run python scripts/make_fixtures.py`) and check the
   diff. The only changes allowed are the 6 new files under `espn/matchup_days/`. Any other
   file that changes is a regeneration drift, and the build stops and reports it, so the
   other fixtures are not committed. — `judgment` — R1.1, R1.5
   - Verify: `git status --short fixtures/landing` lists only the new directory;
     `du -b` of each payload is 116,550.
4. Write the committed-file tests: three periods, league `111111`, matchups equal to the
   matchups fixture's, the list-walking allowlist check, and the lines-against-totals
   check (design.md, *Tests*). Add `("espn", "matchup_days")` to
   `test_the_2026_fixture_season_is_untouched_by_the_past_season`. — `impl` — R2.2, R3.5,
   R3.6
   - Verify: `uv run pytest ingestion/tests/test_make_fixtures.py ingestion/tests/test_fixture_privacy.py`.
5. Write the multi-fixture test (each 2027 league holds exactly one `matchup_days`
   capture, of period 1; each 2026 league holds three), add `matchup_days` to the endpoint
   set of `test_four_league_seasons_are_present`, and watch the new test fail on the
   current generator. Then skip a `matchup_days` capture of a period other than 1 in
   `build_2027_espn`, update the module docstring, and regenerate `fixtures/landing_multi`.
   — `impl` — R4.1 to R4.3
   - Verify: `uv run pytest ingestion/tests/test_make_multi_fixtures.py`; the regenerated
     tree adds only `espn/matchup_days/` captures.
6. Remove the two `#178` entries from `dbt/plants/_empty_in_ci.yml`. — `impl` — R3.3
   - Verify: run in task 9.
7. Reword the comments and descriptions listed in design.md (*`dbt/`: comments and the
   register only*). Before committing `dbt/macros/json.sql`, send the coordinator a
   message ("main", the session that coordinates with #135's work), as agreed on
   2026-10-23. — `impl` — R3.4
   - Verify: the `git grep` from design.md's list returns nothing that says CI has no
     matchup-days capture; `git diff dbt/models dbt/tests dbt/macros` changes comments and
     descriptions only.
8. Compare the CI warehouses. Build one from `main`'s fixtures and one from the branch's,
   each from empty, and run
   `uv run python scripts/compare_warehouses.py <main ci> <branch ci> --strict-columns`.
   — `judgment` — R3.1, R3.2
   - Verify: DIFFERS only `stg_raw__espn_matchup_days`, `stg_espn__matchup_days`,
     `stg_espn__matchup_player_lines` and `rec_espn__matchup_stat_differences` (80 rows,
     `matchup_line_value` only). The expected-values queries give the rows stated in
     requirements.md.
9. Run `.agentic/gates`. — `impl` — R3.3, R4.4, all
   - Verify: dbt build PASS 776 / WARN 3 / ERROR 0; the plant gate reports "reading zero
     rows: 18" and passes; tenant isolation reports 0 differing pairs.
10. (last) Verify every acceptance criterion and expected value, including the real
    season. — `judgment` — all, R5.1
    - R5.1: run `dbt compile` (target dev) on `main` and on the branch, and diff
      `target/compiled` with SQL comments stripped. Expected: no difference, so the real
      warehouse cannot change.
    - On the branch, build `stg_raw__espn_matchup_days stg_espn__matchup_days
      stg_espn__matchup_player_lines` with their tests against the real season. Expected:
      all pass. Record their row counts beside those of the current real warehouse:
      expected equal.
    - Record each expected-values row, with its query and result, as a comment on #178.
