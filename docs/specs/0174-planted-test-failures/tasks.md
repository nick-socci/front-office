# A data test the CI fixtures cannot exercise is shown to fail on a planted row — tasks

Issue: #174 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #174 during the build, and this file is not edited to show it.

1. Record the starting point: build the CI warehouse from empty on `main`, recount C3 (412
   generic tests, 35 over zero rows, 4 by `where`, 7 empty relations), and take the
   checksum of `dbt/ci.duckdb` — `judgment` — R3, R4
   - Verify: the counts posted on #174 equal *Expected values*; if they differ, stop and
     report before writing plants.
2. pytest for the harness's pure functions, seen to fail first: register validation,
   stale names, the classifier, the result judge, and a statement that changes no row on
   a tiny DuckDB file (design.md, *Test strategy*) — `impl` — R1.1, R1.3, R1.4, R2.3,
   R2.4, R2.5, R3.2, R3.3, R5.3
   - Verify: the tests fail (the module does not exist), then pass after task 3.
3. `scripts/check_plants.py` as designed: load and validate, detect, plant, print, exit
   code; `dbt/plants/README.md` — `impl` — R1, R2, R3
   - Verify: task 2's tests pass. On the CI warehouse with an empty `dbt/plants/`, it exits
     1, naming the 4 tests and the 7 relations.
4. `dbt/plants/_empty_in_ci.yml` with the 7 relations, reasons and links of design.md —
   `impl` — R4.5
   - Verify: the harness then names only the 4 tests.
5. The 9 plant files and 24 plants of design.md, *The first register*. Each plant is run
   alone and its count confirmed before it is committed — `impl` — R4.1, R4.2, R4.3, R4.4
   - Verify: the harness exits 0 with 24 plants met (20 fail, 4 pass); the summary reads
     412 counted, 35 over zero rows, 35 accounted for. Any plant whose real count differs
     from design.md's comes back as a question, not an edited expectation.
6. Add the step to `.agentic/gates` and `.github/workflows/ci.yml`, in the same place;
   the `AGENTS.md` bullet — `impl` — R5.1, R5.2
   - Verify: `.agentic/gates` green; the step's time is under 90 s; the checksum of
     `dbt/ci.duckdb` taken just before the step equals the one just after.
7. (last) Prove each check can fail and verify every acceptance criterion — `judgment` —
   all
   - Break each, run the harness, see it fail by name, restore:
     - remove `_empty_in_ci.yml`'s entry for `rec_espn__register_rows` (R3.3);
     - delete `not_null_fct_matchup_results_winner.yml` (R3.2);
     - change a plant's matchup id to one that does not exist (R2.3);
     - change one `expect` count (R2.5);
     - name a missing test in a file name (R1.3);
     - revert `fct_matchup_category_scores_values_have_a_side` to its pre-#173
       expression in a scratch branch, and see the `pass` plants turn to failures.
   - Verify: each failure and the expected-values table, posted on #174. There is no
     real-season run: the harness runs on the CI warehouse only.
