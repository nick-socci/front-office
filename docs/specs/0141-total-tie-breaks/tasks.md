# A tie where a ranking cuts stops the build — tasks

Issue: #141 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #141 during the build, and this file is not edited to show it.

1. Write `ingestion/tests/test_tie_macros.py`: the R4.1 cases through `dbt show --inline
   --target ci`, each asserting the rows returned or the error and its message (node,
   place, keys, `null` for a null key, `whole input` with no partition). It fails before
   task 2, because the macros do not exist. — `impl` — R1.1–R1.6, R4.1
   - Verify: `uv run pytest ingestion/tests/test_tie_macros.py` fails with the macros
     missing, not on a fixture or a dbt error.
2. Write `fo_keep_first`, `fo_row_number` and `fo_tie_message` in
   `dbt/macros/latest_by_entity.sql`, and render `fo_latest_by_entity` through
   `fo_keep_first`, as *Detailed design* gives them. Update the file's header comment. —
   `impl` — R1.1–R1.6
   - Verify: task 1's tests pass, including R1.1a's case. `.agentic/gates` passes, with the fixture build
     unchanged (C6: no tie).
3. Run task 1's literal cases on BigQuery: plain `bq query`, no table, with
   `--project_id` from `FO_BQ_PROJECT`, the SQL rendered by `dbt compile --inline` for
   `--target bq`. Record the results on #141. — `judgment` — R1.6, R4.2
   - Verify: raises on the tie cases, and returns the same rows as DuckDB otherwise.
4. Write `ingestion/tests/test_dbt_tie_rule.py` (R2.1, R2.2) with its own unit cases. Share
   the comment and string blanking with `test_dbt_ordered_aggregate_rule.py` through a
   helper module, not a copy. — `impl` — R2.1, R2.2
   - Verify: its unit cases pass. Over the tree, it flags exactly the hand-written sites in
     *Call sites*: 13 `row_number` (12 in models, 1 in `fo_espn_latest_paths`) and 2 `lag`.
     Record the list on #141.
5. Convert every call site in *Call sites*, including the four `tie-exempt:` comments, and
   R3.2 and R3.3. — `impl` — R2.3, R3.2, R3.3
   - Verify: task 4's test passes over the tree. `.agentic/gates` passes.
6. Write R3.4's dbt unit test of `stg_idmap__players` in
   `dbt/models/staging/idmap/_idmap__models.yml`, beside the existing one. It fails on
   the case ADR 0109 changes before task 7. — `impl` — R3.4
   - Verify: `dbt test --select stg_idmap__players,test_type:unit --target ci` fails on that
     case only, before task 7.
7. Apply ADR 0109's rule to `stg_idmap__players`, as accepted, with the model comment R3.1
   asks for. Update AGENTS.md rule 5 (R2.4). — `judgment` — R3.1, R2.4
   - Verify: task 6's test and `.agentic/gates` pass. The comment names the ADR.
8. `uv run --group bigquery dbt run --target bq --selector bigquery --empty --vars
   '{fo_schema_suffix: _141}'`, after `dbt seed` and `dbt build --select
   resource_type:function` with the same vars, then `dbt test` on the same datasets with
   `--exclude-resource-type unit_test`. — `impl` — R4.3
   - Verify: both pass. Record on #141, with the bytes billed.
9. (last) Verify every acceptance criterion and expected value against the real season. —
   `judgment` — R5.1–R5.3, all
   - Build the real season from the branch, and from `main` on the same raw data, each
     into its own `data/build141/…` directory (not the scratchpad). Compare them. Check
     every row of *Expected values*, including R5.3: remove R3.1's rule on a copy and
     build `stg_idmap__players`, expecting the error naming 5214984. Run the plan-shapes
     gate result as part of the gates.
   - Verify: record the commands, the results and the comparison on #141.
10. Draft, for the owner to file, an issue for null ordering across warehouses (*No-gos*).
   Count the nullable ascending order keys in the converted sites on the real season. —
   `judgment` — follow-up
   - Verify: draft text in the build's progress comment on #141, with the count.
