# A season's scale becomes its own as its matchups are played — tasks

Issue: #161 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #161 during the build, and this file is not edited to show it.

1. Record the starting point on the real warehouse: build `main` from empty (or reuse a
   warehouse built from `main`'s current models), keep it as the comparison base, and
   recount the expected values' "before" figures — `judgment` — all
   - Verify: posted on #161: the one failing row (2023 SP, 0.3333 or as `main` then has
     it), each season's M, and the scales of C3.
2. Add `settings.scheduleSettings.matchupPeriodCount` to the fixture allowlist of
   `scripts/make_fixtures.py` and its copy in `ingestion/tests/test_make_fixtures.py`;
   regenerate the fixtures and `fixtures/landing_multi` — `impl` — R1.2
   - Verify: every fixture settings capture holds the count; pytest and
     `scripts/check_examples.py` pass, with no number in `expected_on_fixtures.yml`
     moving.
3. Extend the unit test of `stg_espn__league_settings` with the field, seen to fail; then
   stage `matchup_period_count` — `impl` — R1.2
   - Verify: the unit test fails first, then passes; the portable-SQL and slice tests pass.
4. Unit tests of `int_fantasy__category_scales` (design.md, *Test strategy*: n = 0, part-way,
   n = M, n > M, no M (the fallback weight), a rate's denominator, a `current_season`
   category; the existing tests given M = n + 2), seen to fail; then the weight,
   `scheduled_matchups`, `history_weight`, the contract and the header — `impl` — R1.1,
   R1.3–R1.8, R2.3
   - Verify: the new unit tests fail first, then pass; every existing unit test of the
     model passes with its expected scales unchanged.
5. Write the two warn-severity singular tests,
   `int_fantasy__category_scales_know_the_scheduled_matchups` and
   `int_fantasy__category_scales_decided_within_the_schedule` — `impl` — R1.8, R1.9
   - Verify: both pass on CI. The first warns on CI copies with a null
     `matchup_period_count` and with 0; the second warns on a copy with M below n. The
     slice pins move as the tests counted, with "spec 0161" comments.
6. Run `.agentic/gates`, the tenant-isolation check inside them, and `dbt run --target bq
   --selector bigquery_slice --empty` — `impl` — all
   - Verify: green.
7. (last) Build the real warehouse from empty and verify every expected value against
   task 1's base — `judgment` — all
   - Verify: `values_track_rescored_category_wins` 0 rows; every relation that moves is one
     the expected values name, by the counts given (or recounted with the reason it
     differs); rerun the backtest of design.md C17 on the new warehouse; record the
     queries and results as a comment on #161.
