# The production raw loader for BigQuery — tasks

Issue: #140 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #140 during the build, and this file is not edited to show it.

1. Move the wanted-field lists, projections, privacy check and account-id logic from
   `scripts/spike_load_bigquery.py` into `ingestion/src/front_office/upload.py`, with their tests,
   the fixtures importing the lists from the package — `impl` — R6.1, R6.2, R6.3, R6.6
   - Verify: the moved tests pass; `scripts/make_fixtures.py` regenerates the fixtures unchanged.
2. Test, then write, `capture_structures.py`: structures read from the macro file, schema, `reduce`,
   the refusals; compared with DuckDB's reading of the fixtures — `judgment` — R1.2, R1.6, R5.1 to R5.4
   - Verify: the new tests fail on a planted drift, and pass.
3. Test, then write, the run against a fake client: listing, what each table lacks, collisions,
   schema refusal, append order, the lock, the checks after, `--dry-run`, `--rebuild`, `--verify` —
   `judgment` — R1.1, R1.3, R1.4, R1.5, R3.1 to R3.8, R4.1 to R4.4, R6.3 to R6.5, R6.7, R7.2
   - Verify: every row of the design's test table for these requirements, each planted failure red.
4. Add the BigQuery calls and the `front-office upload` command, with `google.*` imported only where
   a job runs — `impl` — R7.1, R6.5
   - Verify: `uv run mypy`; `--dry-run` on the fixtures in an environment without the `bigquery` group.
5. Change `bigquery__fo_captures` and `fo_capture_keys`, the raw sources, the unit tests' manifest
   inputs, and `test_dbt_portable_sql_rule.py` — `impl` — R2.1, R2.2, R2.3, R2.4
   - Verify: `.agentic/gates`, and a DuckDB real-season build identical to `main`'s.
6. Remove `scripts/spike_load_bigquery.py` and what only it used; update `AGENTS.md`, `README.md`
   and the docs that name `raw.api_responses` as current — `impl` — R7.3
   - Verify: `.agentic/gates`; a grep shows `api_responses` only in history (ADRs, specs).
7. Link the records this one amends or supersedes in their `Status` lines: 0052, 0054, 0070, 0114 —
   `impl` — all
   - Verify: the ADR tests in `.agentic/gates`.
8. On the real data, into new tables, naming `FO_BQ_PROJECT` explicitly: `front-office upload`
   `--dry-run`, then the upload, then `--verify` on all eleven, then a second upload that must send
   nothing — `judgment` — R1, R3, R4, expected values
   - Verify: the row counts; record them on #140.
9. Build on BigQuery into `_140` datasets, reading the new tables: `dbt seed`, the function, the
   populated `dbt build --selector bigquery --exclude-resource-type unit_test`, `compare_bigquery.py
   --suffix _140`, then the unit tests — `judgment` — R2, expected values
   - Verify: every relation exact; no more than 20 GB billed, otherwise stop and report; unit tests pass.
10. (last) Verify every acceptance criterion and expected value against real data, and with the owner's
    agreement on the issue, drop `raw.api_responses`, and rebuild the unsuffixed datasets on the new
    tables — `judgment` — all
    - Verify: record the queries and results as a comment on #140.
