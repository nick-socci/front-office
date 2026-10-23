# The member-data endpoints on BigQuery: teams, transactions and MLB's player list — tasks

Issue: #136 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #136 during the build, and this file is not edited to show it.

1. On the owner's approval, before anything else: set ADRs 0093, 0094 and 0095 to
   `accepted`. Move 0061's amendment of 0054 to an `- Amends:` line, and set 0061 to
   `accepted; amended by 0093`. Set 0054 to `accepted; amended by 0061, 0093, 0094, 0095`.
   Add `/data/` to `.gitignore`. — `impl` — R6.2, R6.3
   - Verify: `.agentic/gates` passes. The decisions page shows every amendment.
     `git check-ignore -q data/proj136` exits 0.
2. Write the tests for what is read and how it is projected: R1.1 to R1.5 in the design's
   test strategy. Replace `test_only_the_seven_endpoints_are_read` and
   `test_a_transactions_capture_goes_up_with_no_payload`. Each new test fails on `main`'s
   loader. — `impl` — R1.1, R1.2, R1.3, R1.4, R1.5
   - Verify: `uv run pytest ingestion/tests/test_spike_load_bigquery.py` fails on exactly
     the new tests, each for the reason its docstring names.
3. Add `mlb/players` to `ALLOWLIST`. Add `project_teams`, and a new `project_transactions`
   built from the lists imported from `make_fixtures`, with the loader's own rebuild that
   keeps single values only. Leave `project_matchup_day` alone. — `impl` — R1.1 to R1.6
   - Verify: task 2's tests and the existing matchup-day tests pass.
4. Write the tests for the check and the run's snapshot: R2.1 to R2.7 in the design's test
   strategy, including `known_accounts` on a small landing root. — `impl` — R2.1 to R2.7,
   R3.1
   - Verify: each fails on task 3's loader for its stated reason.
5. Implement the check and the snapshot:
   - `ManifestRows` reads the manifest once;
   - the `mlb/players` name exception;
   - the transaction-id GUID exception, with its whole-GUID condition;
   - `known_accounts` over the snapshot, and the `accounts` argument of
     `check`/`privacy_hits`;
   - the empty-set hit;
   - the dry run's two new counts.

   — `impl` — R2.1 to R2.7
   - Verify: `uv run pytest ingestion/tests/test_spike_load_bigquery.py`, and
     `uv run mypy`.
6. Write the tests for `--write-landing` (R4.1, R4.3), then implement it as the design says.
   It writes after the check passes, the projected endpoints' rows only, through
   `LandingZone.write`, under each capture's own partitions, name, request and stamp. It
   refuses a root that exists or that git does not ignore. — `impl` — R4.1, R4.3
   - Verify: the tests pass. Nothing is written when the check stops, or when the root is
     refused.
7. Update the loader's docstring. — `impl` — R6.1
   - Verify: `.agentic/gates` passes.
8. Dry run on the real season: `--dry-run --write-landing data/proj136`. Compare its row
   counts with a dry run of `main` on the same landing zone. — `judgment` — R5.1
   - Verify: 0 privacy hits; new endpoints 13 / 7 / 9; existing endpoints unchanged; 17
     known accounts; 34,882 exempt ids. Post the output on #136.
9. The DuckDB comparison of the design: load `data/proj136`, build the eight relations from
   it and from a fresh load of `data/raw`, and compare. — `judgment` — R4.2
   - Verify: `scripts/compare_warehouses.py <real> <projected> --strict-columns` exits 0.
     Post the per-relation row counts on #136.
10. With the owner's go-ahead (credentials, billing), run the upload. Then build the three
    capture views with `--target bq` and count their rows on both warehouses, passing the
    project explicitly. — `judgment` — R5.2, R5.3
    - Verify: the loader exits 0 with every row of 11 endpoints paired and equal. The views
      hold 13 / 7 / 9 rows on each warehouse. Post both on #136.
11. (last) Check every acceptance criterion and expected value against the real season, and
    record the results on #136. — `judgment` — all
    - Verify: the *Expected values* table, row by row, in one comment on #136.
