# Player value and transaction impact — tasks

Issue: #11 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. Check a box only when its verification passes.

- [x] 1. Rename the staging message fields and select `for` — `impl` — R2.3
  - Grep for readers of `to_team_id` / `from_team_id` first; report any outside staging.
    Update the model, its YAML contract and descriptions. `author` stays unselected.
  - Verify: `dbt build --select stg_espn__transactions`; `.agentic/pre-commit-guard` passes.
- [x] 2. Extend `espn_activity_types` and build `int_fantasy__transactions` — `impl` — R2.1, R2.2, R2.4, R2.5
  - Seed columns via `scripts/make_espn_seeds.py`, never by hand. Tests first: `unique`,
    `not_null` on `movement` and `fantasy_team_id`, `relationships` to teams, and the
    singular "drop names the rostering team" test.
  - Classify the eleven 179/181 drops not on the named team the day before; report.
  - Verify: `dbt seed --full-refresh && dbt build --select +int_fantasy__transactions`; 737
    rows, 374 adds, 363 drops.
- [x] 3. Check the fixtures can feed a replacement pool — `judgment` — R3.4
  - Count unrostered MLB player-days per group in the CI warehouse. If any group is empty,
    extend `scripts/make_fixtures.py` (allowlist) and regenerate.
  - Verify: `.agentic/gates` green; `test_fixture_privacy.py` passes.
- [x] 4. Build `dim_players` — `impl` — R1.1, R1.2, R1.3, R1.4
  - Tests first, including the unit test for a transaction-only pitcher's group. Report
    how the five transaction-only players resolve and which group each gets.
  - Verify: 498 rows on the real season; 0 unresolved among rostered players.
- [x] 5. Build `int_fantasy__replacement_levels` — `impl` — R3.1, R3.2, R3.4, R3.5
  - Tests first: pool size ≤ N, deterministic tie-break, one-sided played days, and the
    unit test that an empty RP pool still yields null-level RP rows.
  - Verify: real season gives hitters AVG .237, SP ERA 5.15, RP ERA 4.13 at N = 12.
- [x] 6. State the replacement definition and sensitivity in the model header — `judgment` — R3.3
  - Re-measure N/2 and 2N; write the bias statement. Count started days where a
    hitter-default player sits in a pitcher slot, and report before relying on the `RP` rule.
  - Verify: header numbers match a fresh query, recorded on #11.
- [x] 7. Write the category-value macro with its unit tests — `impl` — R4.2, R4.3, R4.7, R4.8, R6.5
  - Unit tests first: lower-is-better signs (ERA, B_SO), a rate with a zero denominator,
    a pair with no played day on a category's side, a pitcher-slot day with batting
    only, and a category with zero standard deviation.
  - Verify: `dbt test --select test_type:unit`.
- [x] 8. Build `fct_player_category_value` and `fct_player_season_value` — `impl` — R4.1, R4.4, R4.5, R4.6
  - Tests first: grain uniqueness, category set equals `int_fantasy__categories`, day-count
    identities, "the pool is worth zero".
  - Verify: 580 and 9,860 rows on the real season.
- [x] 9. Add the reconciliation tests to #10's totals — `impl` — R5.1, R5.2
  - R5.1 is per matchup side (286 of them), not per team.
  - Verify: both pass on the real season with no tolerance; 38,665 = 38,420 + 245.
- [x] 10. Build `fct_transaction_impact` — `impl` — R6.1, R6.2, R6.3, R6.4
  - Unit tests first: add-then-drop window, drop-then-re-added window, pre-season start.
  - Verify: 737 rows; 49 windows start on 2026-03-25.
- [x] 11. Judge the numbers — `judgment` — R4, R6
  - Read the top and bottom 20 by `total_value` and the best and worst adds and drops. Do
    they pass the eye test of someone who watched the season? Anything absurd is a
    finding about the definitions, not something to tune away.
  - Verify: observations recorded on #11.
- [x] 12. Spot-check two transactions against the ESPN activity log — `judgment` — R6.2, R6.3
  - One add, one drop, chosen by the person. No member names in what gets recorded.
  - Verify: recorded on #11.
- [x] 13. Verify every acceptance criterion and expected value against real data — `judgment` — all
  - Verify: record the queries and results as a comment on #11.
