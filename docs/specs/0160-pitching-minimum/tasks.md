# A side below the league's pitching minimum loses its ratio categories — tasks

Issue: #160 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #160 during the build, and this file is not edited to show it.

1. Record the starting point on the real warehouse: build `main` from empty (or reuse a
   warehouse built from `main`'s current models), keep it as the comparison base, and
   recount the expected values that are counts — `judgment` — all
   - Verify: the counts posted on #160 equal *Expected values* (1 side below 30 outs; 6
     unexplained category results; the results test's rows).
2. Add `settings.scoringSettings.statQualificationMinimum` to the fixture allowlist of
   `scripts/make_fixtures.py` and its copy in `ingestion/tests/test_make_fixtures.py`;
   regenerate the fixtures and `fixtures/landing_multi` — `impl` — R1.1
   - Verify: the fixture settings hold the minimum as the real league does; pytest and
     `scripts/check_examples.py` pass, with no number in `expected_on_fixtures.yml` moving.
3. Extend the unit test of `stg_espn__league_settings` (a capture with the minimum, one
   without), seen to fail; then stage `qualification_stat_id` and `qualification_minimum`
   — `impl` — R1.1
   - Verify: the unit test fails first, then passes; the portable-SQL and slice tests pass.
4. Write the singular test `stg_espn__league_settings_qualification_is_understood` — `impl`
   — R1.2
   - Verify: passes on CI; fails on CI warehouse copies with a planted stat-41 minimum and
     with a non-head-to-head scoring type.
5. Unit tests, seen to fail, then `int_fantasy__league_seasons.pitching_minimum_outs` and
   `int_fantasy__categories.is_bound_by_minimum` — `impl` — R1.3, R2.1
   - Verify: the unit tests fail first, then pass; on the real data the bound categories
     are WHIP, ERA, K/9 and L from 2021 on.
6. The macro `fo_category_result`; unit tests of `fct_matchup_category_scores` (design.md,
   *Test strategy*, R2.2–R2.5), seen to fail; then the fact with its two new columns —
   `impl` — R2.2, R2.3, R2.4, R2.5, R3.1, R3.4, R3.5
   - Verify: the unit tests fail first, then pass; every existing test of the fact and its
     readers passes on CI; the slice tests pass.
7. Unit test of `fct_lineup_decision_categories` (an optimal lineup below the minimum),
   seen to fail; then `outs_recorded` on `int_fantasy__lineup_category_totals` and the
   optimal result by the macro — `impl` — R3.2, R3.4
   - Verify: the unit test fails first, then passes.
8. Unit test of `rec_fantasy__category_wins_added` (a swap that takes a side below the
   minimum), seen to fail; then the actual and the rescored results by the macro — `impl`
   — R3.3, R3.4
   - Verify: the unit test fails first, then passes; every existing unit test of the model
     passes.
9. Run `.agentic/gates`, and `dbt run --target bq --selector bigquery_slice --empty` —
   `impl` — all
   - Verify: green.
10. (last) Build the real warehouse from empty and verify every expected value against
    task 1's base — `judgment` — all
    - Verify: `scripts/compare_warehouses.py` shows only the relations and rows the
      expected values name; record the queries and results as a comment on #160.
