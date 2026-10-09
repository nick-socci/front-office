# Who is a starter — tasks

Issue: #92 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #92 during the build, and this file is not edited to show
them.

The build waits for #93's build to be merged (R4.1). Its first commit accepts ADR 0031.

1. Record the starting point — `judgment` — expected values
   - On `main`, real warehouse: the start rows of the levels; a copy of the warehouse
     for the row diff; the medians and top 20 of `fct_player_season_value`. In CI: the
     start pool and the warnings.
   - Verify: the "today" column of the expected values, posted on #92.
2. Unit tests — `impl` — R3.1, R3.2
   - The new cases, and the three existing tests of R3.2 revised for first starts. Seen
     to fail on today's model for the right reason. A fourth existing test that fails
     once the model changes is reported on #92 before it is touched.
   - Verify: `dbt test --select int_fantasy__replacement_levels,test_type:unit --target ci`
     fails on exactly the new and revised expectations.
3. The macro and the model — `impl` — R1.1–R1.6, R2.1, R2.2
   - `fo_is_starter_at_the_time`, the `pitching_days_to_date` CTE, the filter.
   - Verify: the unit tests pass; `git diff` touches no other model or macro.
4. The words — `impl` — R6.1, R6.2
   - Verify: `git diff scripts` shows comment lines only.
5. Gates and CI — `judgment` — R3.3, R4.2, R4.3
   - `.agentic/gates`; query `dbt/ci.duckdb`.
   - Verify: 4 starts, 3 pitchers, 51 outs; the same three warnings; isolation 0;
     `git status fixtures` clean.
6. (last) The real season — `judgment` — R5.1–R5.4, expected values
   - Build the real warehouse; diff every model against the copy; record the level, the
     halves and the value movements.
   - Verify: every row of the expected values and R5.4's figures as a comment on #92. A
     difference, a model outside R5.2 that changed, or a failing value test stops the
     build for the owner before the PR is opened.
