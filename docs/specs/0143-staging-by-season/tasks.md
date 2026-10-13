# Staging built a season at a time — tasks

Issue: #143 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #143 during the build, and this file is not edited to show
them. The build's first commit accepts ADRs 0058 to 0060.

1. Record the starting point — `judgment` — expected values, R2.1, R3.2
   - On `main`, on `data/warehouse_143.duckdb` (both seasons): a copy of the built
     warehouse; row counts of the five models; the build's result, time and peak memory;
     the same run under `memory_limit` 16 GB, expected to fail. The CI warehouse copied
     too. `.agentic/gates`.
   - Verify: posted on #143.
2. Can a microbatch model be unit-tested? — `judgment` — R5.1
   - On a scratch copy: one of the five made microbatch, its existing unit tests run.
   - Verify: they run and pass with the same expectations, or the build stops for the
     owner with dbt's error.
3. The view, `fo_year_start`, and their tests — `impl` — R1.2, R5.2, R4.2
   - Unit tests first. The macro with a DuckDB and a BigQuery form.
   - Verify: `.agentic/gates`; the portable-SQL rule test passes.
4. The `relation` argument of the two capture macros and of `fo_boxscore_players` —
   `impl` — R1.2
   - Verify: compiled SQL of every existing model unchanged (`diff` of `target/compiled`).
5. The pytest for R1.1 and R1.5, failing — `impl` — R5.4
   - Verify: it fails naming the five models as not yet batched.
6. The five models: config, `season_start`, the variable, the lookback macro, the
   singular test, the R2.4 unit tests — `impl` — R1.1, R1.3, R1.4, R1.6, R2.4, R5.3
   - One commit for the boxscore pair, one for the roster three.
   - Verify: task 5's test passes; `.agentic/gates`; CI warnings unchanged at 3.
7. CI rows unchanged — `judgment` — R2.2
   - Verify: `compare_warehouses.py` of task 1's CI copy against the new CI warehouse:
     no relation differs in rows; five columns only in the new one.
8. The real warehouse: migration, rows, a second run, memory — `judgment` — R1.7, R1.8,
   R2.1, R2.3, R3.1, R3.2
   - First, an ordinary build on a copy of task 1's warehouse: it must fail on the five
     models naming `--full-refresh` (R1.8). Then the full refresh.
   - Verify: the comparison against task 1's copy; a second, ordinary build identical to
     the first; batches of a model never overlapping in dbt's log; the build passes under
     16 GB; time and peak memory posted. R3.3 if not.
9. BigQuery — `judgment` — R4.1 to R4.4
   - The slice test's counts; the empty build; the real build; the comparison; bytes
     billed. The owner's project and credentials, as in #130.
   - Verify: 31 models; 30 of 30 relations; bytes billed within 10% of 5.35 GB.
10. AGENTS.md and the README — `impl` — R5.6
    - Verify: `uv run pytest ingestion/tests/test_readme.py`; the text names the five.
11. (last) Verify every acceptance criterion and expected value against real data —
    `judgment` — all
    - Verify: the expected-values table, filled in, as a comment on #143.
