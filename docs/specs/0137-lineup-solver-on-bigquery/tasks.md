# The lineup solver on BigQuery — tasks

Issue: #137 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #137 during the build, and this file is not edited to show it.

0. Baseline: build `main` on the real season into a scratch warehouse under `data/`, the
   whole project with tests. It is what R4.1 to R4.3 compare against. — `judgment` — R4
   - Verify: `PASS` with the counts recorded on #137, and the commit it was built from.
1. Answer open question 1: in a throwaway copy, a dbt unit test on DuckDB of a table model
   that calls a plugin-registered function. — `judgment` — R6.2
   - Verify: the unit test passes, or the error is recorded on #137 and R6.2 takes the
     pytest route.
2. `git mv dbt/python_modules/lineup_solver.py dbt/functions/solve_lineup_period.py`.
   Point `test_lineup_solver.py` at it. Write the entry-point tests first (rounding, null
   skip, bound and no-period messages naming the team-day, cap), then the entry point.
   — `impl` — R1.2, R2.2 to R2.5, R3.1, R6.1
   - Verify: `uv run pytest ingestion/tests/test_lineup_solver.py`
3. `dbt/functions/_functions.yml`: the BigQuery signature, `runtime_version`, `entry_point`,
   pinned packages, `enabled` on BigQuery only. Tests first: pins and runtime (R5.2), and the
   YAML against the plugin's types (R6.3). — `impl` — R1.3, R5.2, R6.3
   - Verify: those pytests; `dbt ls --target ci` lists no function, and `--target bq` lists it.
4. The plugin `dbt/python_modules/fo_duckdb_functions.py`, and `plugins:` plus
   `module_paths` in the `dev` and `ci` profiles. — `impl` — R1.4
   - Verify: R6.3's pytest; a `dbt build --target ci` of a model that calls it.
5. Macros `fo_struct` and `fo_solve_lineup_period` in `dbt/macros/portable.sql`, with
   their cases in the portable rule's tests. — `impl` — R1.1, R6.5
   - Verify: `uv run pytest ingestion/tests/test_dbt_portable_sql_rule.py`
6. Move the ten behaviours of `test_optimal_lineups_model.py` to dbt unit tests (or pytest,
   by task 1), and add the manifest pytest of R6.4. Then write
   `int_fantasy__optimal_lineups.sql`, delete the Python model, and rewrite its YAML
   description. — `impl` — R1.1, R1.5, R2.1 to R2.5, R6.2, R6.4
   - Verify: the moved tests; `dbt build --target ci --vars '{anonymize: true}'`
7. Selector rename and exclusion (ADR 0105): `dbt/selectors.yml`,
   `scripts/compare_bigquery.py` and its test, `test_bigquery_slice.py` (renamed, counts
   recomputed and asserted with the function node). The script prints the solver's
   differing team-days with their rows; its test plants one. — `impl` — R5.1, R3.3
   - Verify: those pytests; `dbt ls --selector bigquery --target bq` holds the solver,
     its readers and the function.
8. Docs: README, AGENTS.md, `profiles.yml` comments, the model's description. ADR
   statuses wait for acceptance (task 11). — `impl` — R7.2
   - Verify: `git grep -n "bigquery_slice\|python_modules/lineup_solver\|Python model"`
     outside `docs/specs`, `docs/adr` and `docs/design` shows nothing stale; `.agentic/gates`
     passes.
9. Real season on DuckDB: build the branch into a new warehouse. Compare with task 0's
   using `scripts/compare_warehouses.py`. Then run `probes/compare_solves.py compare` on
   the two solvers' rows with task 0's values, for R4.2 per team-day and per team-period.
   Count the readers' changed rows by team-period (R4.3). — `judgment` — R4.1 to R4.3
   - Verify: only the four relations differ. 1,231 team-days change, every one a tie. The
     solver node takes about 9 s. Results are recorded on #137.
10. Real season on BigQuery, project named explicitly and datasets suffixed: `--empty`
    (R5.5, open question 3). Then two UDF calls on literal arrays, one value beyond the
    bound and one null matchup period, each expected to fail naming its team-day (R2.3,
    R2.4). Then `dbt build --selector bigquery --exclude-resource-type unit_test`,
    `compare_bigquery.py` against task 9's warehouse, and a second build for R5.4. Drop
    the suffixed datasets afterwards. — `judgment` — R2.3, R2.4, R3.2, R3.3, R5.3 to R5.5
    - Verify: `PASS`; both calls fail with the team-day named; every relation passes the
      comparison, the solver 0/0. Times, bytes, slot-ms and `externalServiceCosts` of both
      builds are recorded on #137, and the owner is asked for the UDF cost billed that day
      (open question 2).
11. On acceptance: ADRs 0103 to 0105 `accepted`, and ADR 0039 `amended by` 0103, ADR 0096
    `amended by` 0105. Record the solver's new time on #201. — `impl` — R7.1
    - Verify: the ADR status tests pass in `.agentic/gates`.
12. (last) Verify every acceptance criterion and expected value against real data.
    — `judgment` — all
    - Verify: a comment on #137 with each row of *Expected values* and its result.
