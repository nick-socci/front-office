# Every unit test runs on both warehouses — tasks

Issue: #138 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #138 during the build, and this file is not edited to show it.

1. Extend `test_dbt_portable_sql_rule.py` to unit-test fixtures (design §6): the SQL
   fixtures through `refused_constructs`, the two new constructs, the literal-manifest
   rule and the capture-fixture rule. Each gets planted-example tests that fail and pass
   (R6.3). Macros called from fixtures, nested calls included, and `bigquery__safe_cast`
   are added to what the rule reaches (design §6). — `impl` — R2.2, R3.4, R5.1, R5.2, R5.3, R6.3
   - Verify: the planted-example tests pass. The project-wide test fails and lists
     today's offenders: the 20 manifest inputs, the 14 capture fixtures, and the 26
     other SQL fixtures (design §5). Record the count on #138. If the new patterns flag
     any model or macro, stop and report it: that is not in the plan.
2. Move the four structures into `fo_capture_structure` and point the views at it
   (design §1). — `impl` — R3.3
   - Verify: `dbt compile` of the 11 `stg_raw__*` views on `main` and on the branch,
     `--target ci` and `--target bq`: `diff -r` of the compiled SQL is empty.
     `uv run python scripts/check_plan_shapes.py` still finds the four heavy views.
3. Write the R3.2 test in `test_capture_glob.py` (design, Test strategy), then
   `fo_sql_string` and `fo_capture_rows` (design §2). — `impl` — R3.1, R3.2
   - Verify: the new test passes. Before the macro exists it fails because the macro is
     undefined. The rest is verified through task 5's fixtures.
4. Write `bigquery__safe_cast` (design §4), and the new unit test
   `stg_mlb__players_keep_a_name_exactly_as_mlb_gives_it` (`Travis d'Arnaud`, and a name
   holding `\"` and `\\`). — `impl` — R4.1, R4.2, R4.3
   - Verify: the new test passes on `ci`. On `bq` it is run in task 9.
5. Rewrite the 14 capture fixtures with `fo_capture_rows`. The `games_*` and `pitching_*`
   payloads keep a key outside the structure. — `impl` — R3.1, R3.2, R1.4
   - Verify: for each fixture, the old and the new rows on DuckDB, compared with
     `except all` both ways, and the column names and types compared. All equal. The
     compiled fixture SQL of both is in `target/`. Record one line per fixture on #138.
6. Rewrite the 20 manifest inputs in §3's spelling. — `impl` — R2.1
   - Verify: the unit tests of the touched models pass on `ci`.
7. Rewrite the 26 other SQL fixtures (design §5). — `impl` — R5.1, R5.4, R1.4
   - Verify: R1.4's comparison for each, as in task 5. The project-wide rule of task 1
     now passes.
8. AGENTS.md: the fixture entry and the BigQuery unit-test commands (design §7). —
   `judgment` — R6.1, R6.2
   - Verify: read against §2–§7. No rule is stated that the gates do not hold or that
     the design does not give.
9. (last) Verify every acceptance criterion against BigQuery and DuckDB. — `judgment` —
   all
   - `.agentic/gates` green: 224 unit tests pass on DuckDB (R1.1).
   - `git diff main -- dbt/models` changes no `expect:` block and removes no test (R1.3).
   - Name the BigQuery project, then run design §7's commands with `fo_schema_suffix:
     _138`. Expect 220 pass, exactly the four #139 tests failing, and 0 errors (R1.2).
     Record `totalBytesBilled` for the run's jobs: expect 0.
   - Record the commands, counts and per-test outcome on #138.
