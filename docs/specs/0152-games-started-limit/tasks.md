# A league's games-started limit is applied to credited production — tasks

Issue: #152 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #152 during the build, and this file is not edited to show it.

1. Record the starting point on the real warehouse: save
   `rec_espn__matchup_stat_differences`, `int_fantasy__started_player_days` (row count and
   the 2023 matchup 110 team 7 rows), `int_fantasy__lineup_category_totals`,
   `fct_lineup_decisions`, `fct_player_season_value` and the
   failing rows of `fct_matchup_scores_match_espn`, `fct_matchup_results_match_espn` and
   `rec_espn__player_day_differences_are_registered`, outside the tree; recount the
   expected values that are counts — `judgment` — all
   - Verify: the counts are posted on #152; they are what task 11 compares against.
2. Add `settings.rosterSettings.lineupSlotStatLimits` to the fixture allowlist of
   `scripts/make_fixtures.py` and regenerate the fixtures — `impl` — R1.1
   - Verify: the fixture settings capture holds the entry; the privacy test and
     `scripts/check_examples.py` pass; no number in `docs/examples/expected_on_fixtures.yml`
     moves (if one does, stop and report it).
3. Write the dbt unit tests of `stg_espn__lineup_slot_stat_limits` (one entry, two, `{}`),
   then the model and its YAML (columns, `unique` on the three keys, `not_null`), to the
   two-warehouse rule — `impl` — R1.1, R1.2
   - Verify: the unit tests fail before the model exists and pass after;
     `test_dbt_portable_sql_rule.py` passes; `dbt run --target bq --selector
     bigquery_slice --empty` compiles the model.
4. Write the unit tests of `int_fantasy__start_limits` (7- and 12-day periods with a
   limit, a league-season with none) and the singular test
   `int_fantasy__start_limits_are_understood`, then the model — `impl` — R1.3, R1.4
   - Verify: the tests fail first, then pass; the singular test is seen to fail on a
     unit-test fixture with a stat-81 entry, on one with two stat-33 entries, and on one
     with a rotisserie league-season.
5. Write the unit tests of `int_fantasy__started_player_days` (the reaching day finishes,
   the later start uncredited with every pitching column zero, `games_pitched` included,
   relief kept, a hitter-slot start not counted, no limit, row count unchanged), then
   change the model, its contract and its docs — `impl` —
   R2.1, R2.2, R2.3, R2.4, R2.5, R2.6
   - Verify: the new cases fail before the change and pass after; every existing test of
     the model and of its six readers passes on the fixtures.
6. Write the unit test of `rec_espn__player_day_differences` for a marked day, add
   `is_over_start_limit: false` to the mocked rows of its existing unit tests, then
   filter the `ours` CTE and say why in its comment — `impl` — R3.1
   - Verify: the new case fails before the filter and passes after.
7. Write the unit test of `int_fantasy__lineup_category_totals` for an optimal lineup
   past the limit, then apply the rule to both lineups — `impl` — R4.1, R4.2
   - Verify: the new case fails first, then passes;
     `lineup_category_totals_reproduce_the_actual_totals` passes on the fixtures.
8. Write the unit test of `fct_lineup_decisions` (an actual and an optimal lineup each
   past the limit on different days), then apply the rule to `actual_value`,
   `optimal_value` and `value_gap`; add the filter of R4.4 to
   `candidate_day_values_add_back_to_season_value` — `impl` — R4.3, R4.4
   - Verify: the unit test fails first, then passes; the add-back test passes on the
     fixtures.
9. Run `.agentic/gates` — `impl` — all
   - Verify: green.
10. Build the real warehouse and compare it with task 1's saved relations — `judgment` —
   R2.6, R3.2, R4.1, R4.2, R4.3, R4.4
   - Verify: `compare_warehouses.py` shows only the relations this spec moves, and in
     them only the rows the expected values name; the add-back test is seen to fail on
     Fried's pair with its new filter removed.
11. (last) Verify every acceptance criterion and expected value against real data —
   `judgment` — all
   - Verify: each row of *Expected values* checked, and each new test seen to fail; the
     queries and results posted as a comment on #152, and #147's table updated.
