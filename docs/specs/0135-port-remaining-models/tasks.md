# Every SQL model on both warehouses: the 26 models outside the BigQuery slice — tasks

Issue: #135 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #135 during the build, and this file is not edited to show it.

Tasks 1 to 9 need no BigQuery. Tasks 10 to 15 use the owner's application-default
credentials and `FO_BQ_PROJECT`, and run in the main session.

**Depends on #188.** Tasks 2 to 7 may be written before #188 merges. The branch is rebased
onto `main` once it has, and task 1, then tasks 8 onward, run only after that (R3.5).

1. Keep the baseline, once #188 has merged: build the real season from `main` into
   `data/warehouse_135_base.duckdb`, recording wall time and peak memory, with
   `stg_espn__roster_entry_slots`' own time. Build the CI warehouse from the fixtures and
   keep it too. Retake *Expected values*' counts from the baseline where `main` has moved
   — `judgment` — R3.1, R3.3, R3.4, R3.5
   - Verify: #188 is closed by a merged PR that `main` contains; the baseline's `count(*)` per relation recorded on #135
2. Widen the rule test to the whole project, and add the `md5(` and `concat_ws(` patterns
   with their one-line cases. Teach the ordered-aggregate test `fo_corr_in_order`. Seen to
   fail on `main` naming the 26 models' and 9 singular tests' files and no file of the
   slice — `impl` — R2.1, R2.2, R2.3
   - Verify: `uv run pytest ingestion/tests/test_dbt_portable_sql_rule.py ingestion/tests/test_dbt_ordered_aggregate_rule.py` fails as stated, then passes after task 6
3. Turn the selector around (design, *The selector*) and update `test_bigquery_slice.py`
   to C1's names and counts, with the contract and seed type scans over every model and
   seed — `impl` — R1.1, R1.2, R1.3, R1.4, R2.4
   - Verify: `dbt ls --selector bigquery_slice` gives 71 models (39/30/2), 7 seeds, 436 data tests, 187 unit tests; `uv run pytest ingestion/tests/test_bigquery_slice.py` passes except the contract scan, which passes after task 6
4. Add `fo_corr_in_order`, `fo_md5_hex` and `fo_instant_from_millis` to `dbt/macros/portable.sql`, each with `duckdb__` and `bigquery__` forms and no
   `default__`. Teach `compare_bigquery_slice.py`'s `slice_relations` to list the selected
   seeds, with a test first — `impl` — R2.2, R4.3
   - Verify: `dbt compile --target ci` succeeds, and the compiled SQL in `target/compiled` is unchanged from before this task; `uv run pytest ingestion/tests/test_compare_bigquery_slice.py`
5. Port staging: `stg_espn__lineup_slot_limits`, `stg_espn__roster_entry_slots`,
   `stg_espn__teams`, `stg_espn__transactions` (as #188 leaves it, with `transacted_at`
   through `fo_instant_from_millis`), `stg_mlb__players`, by the design's table and notes.
   One commit — `impl` — R2.1
   - Verify: no staging file is in task 2's failure list; `dbt build --target ci --select staging` green
6. Port intermediate, marts and reconciliation, the three solver readers included, and the
   9 singular tests, and the contract types in YAML. One commit per layer. Each `greatest`,
   `least` and ascending window order is read against its model's tests, as the design's
   table says — `impl` — R2.1, R2.4, R5.1
   - Verify: task 2's and task 3's tests pass; `.agentic/gates` green
7. Update AGENTS.md's dbt gotcha (every SQL model is written once for both warehouses, and
   `bigquery_slice` is what BigQuery builds) and README's BigQuery section (what it builds,
   and `--exclude-resource-type unit_test`) — `impl` — R2.5
   - Verify: `git diff AGENTS.md README.md` says that and nothing else
8. Build the real season on `dev` from the port, compare with task 1's baseline over
   every relation and every column type, and compare the CI warehouse with task 1's. Record
   time and peak memory against task 1's — `judgment` — R3.1, R3.2, R3.3, R3.4
   - Verify: `scripts/compare_warehouses.py data/warehouse_135_base.duckdb data/warehouse.duckdb --strict-columns` exits 0; the `information_schema.columns` diff is empty; peak memory within a quarter of the baseline's
9. Compile the three solver readers for BigQuery — `judgment` — R5.2
    - Verify: `dbt compile --target bq --select int_fantasy__lineup_category_totals fct_lineup_decisions fct_lineup_decision_categories` succeeds
10. Settle O1 with constant queries (0 bytes): `to_hex(md5('x'))` and
    `cast('0x9dd4e461' as int64)` on BigQuery, against DuckDB's
    `9dd4e461268c8034f5c8564e155c67a6` and 2647975009 — `judgment` — R4.3
    - Verify: both equal, recorded on #135
11. `dbt build --target bq --selector bigquery_slice --empty --exclude-resource-type unit_test`, repeated until clean. A
    failure with a row in the design's table, or the spike's, goes back to task 5 or 6. One
    without a row is decided by ADR 0051's rule, added to the rule test and to the table's
    record on #135, and taken to the owner if it has no form on one side — `judgment` —
    R4.1, R2.2
    - Verify: the empty build ends clean; task 8's comparison is run again if a shared file changed
12. Run the three solver readers over no rows (design, *The solver readers on BigQuery*):
    the empty solver table by DDL, the `--empty` build of the three, then drop all four.
    Comment on #137 — `judgment` — R5.2, R5.3
    - Verify: the build ends clean; `bq ls` shows none of the four afterwards; the comment's link
13. `dbt build --target bq --selector bigquery_slice --exclude-resource-type unit_test` on
    the uploaded real season, with `anonymize: false`. Fix what fails in a `bigquery__` form, never in a model's logic.
    Then run the 23 models' unit tests on `bq` on their own
    (`dbt test --target bq --selector bigquery_slice,resource_type:unit_test`) and table them — `judgment` — R4.2, R4.5, R4.7
    - Verify: every selected model, seed and data test passes; bytes billed per model and test from `run_results.json`; each unit test listed as passed, failed or not runnable
14. Compare the two builds. Trace each difference by R4.6 and take it to the owner before
    any fix — `judgment` — R4.3, R4.4, R4.6
    - Verify: `scripts/compare_bigquery_slice.py --db data/warehouse.duckdb --project "$FO_BQ_PROJECT"` exits 0, the 7 seeds and `stg_espn__roster_entry_slots` among the relations compared exactly
15. (last) Verify every acceptance criterion and expected value against real data; post the
    figures on #135, the not-runnable unit tests on #138, and any tie found on #141 —
    `judgment` — all
    - Verify: record the queries and results as a comment on #135
