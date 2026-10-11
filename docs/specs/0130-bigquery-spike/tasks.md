# Spike: a representative slice of the dbt project on BigQuery — tasks

Issue: #130 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #130 during the build, and this file is not edited to show it.

Tasks 1 to 9 need no BigQuery and no credentials. Tasks 10 to 17 use the owner's
application-default credentials and `FO_BQ_PROJECT`, and run in the main session.

1. Keep the baseline: copy the real warehouse built from `main` at the spike's base
   commit to `data/warehouse_before.duckdb`, rebuilding it first if it is older than that
   commit; record the build's time and peak memory — `judgment` — R4.4
   - Verify: `compare_warehouses.py data/warehouse.duckdb data/warehouse_before.duckdb --strict-columns` exits 0
2. Add `dbt/selectors.yml` with `bigquery_slice`, the `bq` target, and the `bigquery`
   dependency group; with their tests first (the slice's 30 model and 6 seed names; its
   204 data tests and 59 unit tests, none reading an unselected model; `dev` and `ci`
   parse with `FO_BQ_PROJECT` unset; `dbt-bigquery` only in its group; the target has
   `method: oauth` and no `keyfile`) — `impl` — R1.1, R1.2, R1.4, R2.1, R2.2, R2.3, R2.4,
   R2.5, R2.6
   - Verify: `uv run pytest ingestion/tests/test_bigquery_slice.py`; `.agentic/gates`
3. Write `ingestion/tests/test_dbt_portable_sql_rule.py`: the refused constructs of
   design.md's table, scanned over the slice's models and singular tests and every macro
   they reach through the manifest, skipping `duckdb__` forms; and teach
   `test_dbt_ordered_aggregate_rule.py` the two `fo_*_in_order` macros. Seen to fail on
   the slice as it is, naming each file — `impl` — R4.2, R4.3
   - Verify: before task 5 the test fails listing the slice's files and `boxscore_players.sql`, `espn_latest_response.sql`, `innings_to_outs.sql`, `request_param.sql`, and no model outside the slice
4. Add `dbt/macros/portable.sql` (`fo_type_float`, `fo_type_text`, `fo_safe_cast`,
   `fo_unnest`, `fo_unnest_pair`, `fo_int_series`, `fo_sum_in_order`, `fo_avg_in_order`,
   `fo_any_true`, `fo_timestamp_from_millis`) and dispatch `fo_parse_fetched_at`,
   `fo_eastern_date`, `fo_request_param` and every macro of `json.sql` (with the
   wildcard split in `fo_json_array` and the `JSON` leaf in `fo_json_parse`), each with
   `duckdb__` and `bigquery__` forms and no `default__` — `impl` — R4.1, R4.2
   - Verify: `dbt compile --target ci` succeeds; the compiled SQL of every existing model is unchanged from before this task (diff of `target/compiled`)
5. Port the slice's models, singular tests and shared macros by design.md's table, and
   `stg_espn__pro_games` by its own section; one commit per layer (shared macros,
   staging, intermediate, marts and reconciliation) — `impl` — R4.1, R4.2
   - Verify: task 3's test passes; `.agentic/gates` green
6. Build the real season on `dev` from the ported models at four threads and compare
   with the baseline; compare column types; record time and peak memory against task 1's
   — `judgment` — R4.4, R4.5, R4.6
   - Verify: `compare_warehouses.py data/warehouse_before.duckdb data/warehouse.duckdb --strict-columns` exits 0; the `information_schema.columns` query returns no row that differs
7. Write `scripts/spike_load_bigquery.py`, with its privacy check tested first on small
   payloads (a GUID in an `espn` row; a `gameGuid` in an `mlb` schedule row, allowed;
   `firstName` under `members`; `firstName` under `playerPoolEntry.player`, allowed;
   `owners` under `playerPoolEntry.player`; an endpoint off the allowlist) and its row
   comparison on pairs that differ in one payload field, in `file_path`, in key order
   only (equal), and by a missing row — `impl` —
   R3.1, R3.2, R3.3, R3.4, R3.5
   - Verify: `uv run pytest ingestion/tests/test_spike_load_bigquery.py`; `--dry-run` on the real warehouse lists 5,179 rows in seven endpoints and uploads nothing
8. Write `scripts/compare_bigquery_slice.py`, its type mapping and float rule tested
   first on two small DuckDB databases (an equal pair; a float inside and one outside
   the tolerance; a null on one side; a differing integer; a key that does not join) —
   `impl` — R5.2, R5.3, R5.4, R5.5
   - Verify: `uv run pytest ingestion/tests/test_compare_bigquery_slice.py`
9. Add the `fo_schema_suffix` variable to `generate_schema_name`, applied on the `bq`
   target only — `impl` — R5.5
   - Verify: `dbt compile --target ci` output unchanged; a unit of pytest on the rendered schema names
10. The owner links a billing account and creates a budget with an alert, and says so
    on #130; the build confirms billing is enabled and makes no BigQuery job before
    that — `judgment` — R2.7
    - Verify: `gcloud billing projects describe "$FO_BQ_PROJECT"` shows `billingEnabled: true`; the owner's comment on #130
11. Run the loader on the real warehouse — `judgment` — R3.1, R3.3, R3.4
    - Verify: 5,179 rows paired and equal as parsed JSON, endpoint by endpoint as in *Expected values*; none on one side only
12. `dbt build --target bq --selector bigquery_slice --empty`, repeated until BigQuery
    raises no error. A failure with a row in design.md's table goes back to task 5; one
    without is decided here by ADR 0051's rule, added to the rule test, and listed for
    the findings; one with no form on a side goes to the owner — `judgment` — R4.7, R6.3
    - Verify: the empty build ends clean; task 6's comparison is run again if any shared file changed
13. `dbt build --target bq --selector bigquery_slice` on the real rows. Fix what fails in
    the `bigquery__` form of a macro, never in a model's logic; a failure that needs a
    model changed beyond design.md is written up and taken to the owner before it is
    made — `judgment` — R1.3, R5.1, R6.3
    - Verify: the build ends with every model, seed and data test of the slice passing; task 6's comparison is run again if any shared file changed
14. Run the slice's unit tests on `bq` and table the results — `judgment` — R5.6
    - Verify: 59 unit tests each listed as passed, failed or not runnable
15. Compare the two builds, then build a second time on `bq` and compare BigQuery with
    itself — `judgment` — R5.2, R5.3, R5.4, R5.5
    - Verify: `compare_bigquery_slice.py` exits 0; its output is kept for the comment
16. Measure: bytes billed per model and test; one boxscore model against a `STRING`
    payload; the changed files by construct and the same constructs counted in the 27
    unported models; and the external table over a private bucket for `mlb/boxscore`,
    bucket and table deleted afterwards — `judgment` — R6.1, R6.2, R6.4, R6.6
    - Verify: every figure is read from `run_results.json` or a query, none estimated
17. (last) Verify every acceptance criterion and expected value against real data; post
    the findings; file the milestone's remaining issues, including the lineup solver's
    and the two member-data endpoints'; say what ADRs 0051 to 0054 now look like in the
    light of it — `judgment` — all, R6.5
    - Verify: record the queries and results as a comment on #130
