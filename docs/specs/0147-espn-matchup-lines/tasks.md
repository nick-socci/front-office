# ESPN's own matchup lines settle the past seasons' differences — tasks

Issue: #147 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #147 during the build, and this file is not edited to show it.

1. Save the pre-change state from the eight-season warehouse: `rec_espn__matchup_stat_differences`,
   `rec_espn__category_result_differences`, `rec_espn__player_day_residuals`,
   `stg_espn__matchup_days`, and the failing rows of the three tests, to Parquet under
   `data/` — `impl` — R6.1, R6.2
   - Verify: row counts of the saved files equal the tables' (requirements, *Expected
     values*, "before" column)
2. Unit tests for `stg_espn__matchup_days` that pin today's existence rule on a declared
   side; then change the capture view `stg_raw__espn_matchup_days` to the declared side
   structure and the matchup `id`, and the model to ask the declared member — `impl` —
   R1.4, R6.2
   - Verify: the unit tests pass; on the real warehouse `stg_espn__matchup_days` equals the
     saved table (`except all` both ways: 0 and 0); `test_capture_glob.py` passes
3. Unit tests for `stg_espn__matchup_player_lines` (design.md, *Test strategy*, R1 rows),
   seen to fail; then the model, its YAML (grain, `unique`, `not_null`), and the singular
   tests `stg_espn__matchup_player_lines_cover_played_sides` and the one-line-per-player
   check — `impl` — R1.1, R1.2, R1.3, R1.5
   - Verify: `dbt build --select stg_espn__matchup_player_lines+1` on the real warehouse; 0
     played sides without lines
4. Add the matchup `id`, the side's `teamId` and the lines to the BigQuery projection
   `project_matchup_day`, with its test asserting the `id` is kept and no name or member
   key is — `impl` — R1.4
   - Verify: `uv run pytest` for the projection test; the privacy patterns find nothing in
     a projected real capture
5. Unit tests for `rec_espn__matchup_stat_differences` covering R2 and R3 (design.md,
   *Test strategy*), seen to fail; then `rec_espn__matchup_line_totals` (ephemeral), the
   composite game lines, the recovery, the new shift and status, and the two new columns
   — `impl` — R2.1, R2.2, R2.3, R2.4, R3.1, R3.2, R3.3, R3.4, R3.5
   - Verify: unit tests pass; `sqlfluff lint`; `test_dbt_portable_sql_rule.py`
6. Unit test for a bye in `rec_espn__category_result_differences`, seen to fail; then the
   `bye` status and `explained_by_matchup_lines` in `accounted` — `impl` — R4.1
   - Verify: unit tests pass
7. Unit tests for `rec_espn__winner_differences`, seen to fail; then the view, the
   winner branch of `fct_matchup_results_match_espn` reading it, and its entry in
   `bigquery_slice` — `impl` — R4.2, R4.3
   - Verify: unit tests pass; `test_bigquery_slice.py` passes
8. Unit tests for `rec_espn__player_day_residuals` (carried, #152's shape, a cancelling
   pair), seen to fail; then the `carried` rule — `impl` — R5.1, R5.2, R5.3
   - Verify: unit tests pass
9. Model headers and YAML descriptions for every changed model; the test comments that
   name the old rules (`fct_matchup_results_match_espn`,
   `rec_espn__player_day_differences_are_registered`) — `impl` — all
   - Verify: `.agentic/gates`
10. BigQuery: `dbt run --target bq --selector bigquery_slice --empty`; DuckDB:
    `scripts/compare_warehouses.py` against the pre-change warehouse — `judgment` — R6.2
    - Verify: the empty run compiles and runs; every model outside `staging/espn`, the
      capture view and `reconciliation/espn` is identical
11. (last) Build all eight seasons from empty and verify every expected value and
    acceptance criterion against real data, including the build's time and peak memory —
    `judgment` — all
    - Verify: record the queries and results as a comment on #147. Any count that differs
      from *Expected values* goes to the owner before the PR leaves draft
