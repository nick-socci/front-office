# A tied playoff matchup goes to the higher seed — tasks

Issue: #159 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #159 during the build, and this file is not edited to show it.

1. Record the starting point on the real warehouse: build `main` from empty (or reuse a
   warehouse built from `main`'s current models) and keep it as the comparison base;
   recount every expected value that is a count — `judgment` — all
   - Verify: the counts posted on #159 equal requirements.md's *Expected values* "before"
     figures (10 level playoff matchups; 47 regular-season ties; the results test 16;
     the winner view 15 rows).
2. Add `settings.scoringSettings.playoffMatchupTieRule` and `…matchupTieRule` to the
   fixture allowlist of `scripts/make_fixtures.py` and to the copy in
   `ingestion/tests/test_make_fixtures.py`; regenerate the fixtures (and
   `fixtures/landing_multi`) — `impl` — R1.1
   - Verify: every fixture settings capture holds both as `NONE`; pytest passes;
     `scripts/check_examples.py` passes and no number in
     `docs/examples/expected_on_fixtures.yml` moves.
3. Extend the unit test of `stg_espn__league_settings` with both settings (one not
   `NONE`), seen to fail; then stage `playoff_matchup_tie_rule` and `matchup_tie_rule`, and
   their YAML — `impl` — R1.1
   - Verify: the unit test fails first, then passes; `test_dbt_portable_sql_rule.py`
     passes.
4. Write the singular test `stg_espn__league_settings_tie_rules_are_understood` — `impl` —
   R1.2
   - Verify: passes on the CI build; fails on a copy of the CI warehouse with a planted
     playoff rule other than `NONE`, and on one with a null `matchup_tie_rule`.
5. Write the unit test of `fct_matchup_results` (design.md, *Test strategy*, R2.1–R2.3),
   seen to fail; then the `winner` rule, `is_decided_by_tiebreak` with its YAML and
   `not_null` test, and the rewritten header — `impl` — R2.1, R2.2, R2.3, R2.5
   - Verify: the unit test fails first, then passes; `test_bigquery_slice.py` passes
     unchanged, or its pins move only by the new `not_null` test, with a "spec 0159"
     comment.
6. Write the singular test `fct_matchup_results_home_is_the_better_seed` — `impl` — R2.4
   - Verify: passes on the real warehouse (136 matchups); fails on a real warehouse copy
     with two teams' seeds swapped; `dbt ls --selector bigquery_slice` does not list it.
7. Write the unit test of `rec_fantasy__category_wins_added` for level playoff and
   regular-season matchups (home and away pairs), seen to fail; then carry the home side
   and the playoff flag into `matchup_draws` and score a level playoff matchup as
   ADR 0080 says — `impl` — R3.1, R3.2
   - Verify: the new case fails first, then passes; every existing unit test of the
     model passes.
8. Run `.agentic/gates`, and `dbt run --target bq --selector bigquery_slice --empty` —
   `impl` — all
   - Verify: green; the empty run passes.
9. (last) Build the real warehouse from empty and verify every expected value against
   task 1's base — `judgment` — all
   - Verify: `scripts/compare_warehouses.py` shows only the relations and rows the
     expected values name; record the queries and results as a comment on #159.
