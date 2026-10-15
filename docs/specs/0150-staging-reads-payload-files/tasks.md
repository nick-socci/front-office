# Staging reads payload files with a declared structure; the raw table holds no payloads — tasks

Issue: #150 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #150 during the build, and this file is not edited to show it.

1. Record the starting point: copy `data/warehouse_83.duckdb` to
   `data/pre150/warehouse.duckdb` (the comparison target of R6.3), and record `dbt test`'s
   result on it — `judgment` — R6.3, R6.4
   - Verify: the copy's relation list and row counts posted on #150; the copy is not
     deleted until the PR merges (#83 lost its copy)
2. Tests for the manifest loader: columns and rows of `raw.captures`, no payload read,
   `file_path` relative to the root from two working directories, an old
   `raw.api_responses` refused and unchanged, a stamp not ending in `Z` refused; keep the
   collision and append-only tests — `impl` — R1.1–R1.7
   - Verify: `uv run pytest ingestion/tests/test_load.py` fails on `main`'s loader
3. Rewrite `front_office/load.py` to write `raw.captures` (first pass only), and the
   audit's `loaded` check, `check_tenant_isolation.py`, `verify_migration.py` and the
   freshness sources to read it — `impl` — R1.1–R1.7
   - Verify: task 2's tests pass; `uv run mypy`; `uv run pytest`
4. `fo_landing_root()` and the capture-read macro in `dbt/macros/json.sql`: the glob of
   committed names, the join to the manifest, the empty case through `glob()`, the
   structure turned into `read_json` column types; the BigQuery variant over the
   uploaded table, with a map leaf; `fo_map_values` and `fo_map_entries` for both
   warehouses — `judgment` — R2.1–R2.5, R3.4, R5.1, R5.4
   - Verify: `test_capture_glob.py` (written first: the `.tmp-` directory, an unloaded
     directory, an unparseable payload listed and one not listed, an empty endpoint)
     passes; `dbt run --target bq --selector bigquery_slice --empty` compiles
5. The eleven capture views, with their unit tests (one row per capture for the small
   endpoints, the id map's array included; the declared fields for the heavy three); the
   heavy structures written from the fields today's models read — `judgment` — R3.1–R3.3
   - Verify: `dbt build --target ci --select path:models/staging/raw` green
6. Extend the rule test: no model or test outside the macro names `read_json`,
   `read_json_objects`, `raw.api_responses` or `raw.captures`; no model is microbatch —
   `impl` — R3.4, R3.5, R4.1
   - Verify: the rule test fails on `main` (models read the raw source) and is listed in
     the gates' pytest run
7. Move the nineteen staging models and `fo_espn_latest`, `fo_latest_boxscore_responses`,
   `fo_boxscore_players` to the capture views; the two latest-capture macros rank
   `raw.captures` only and semi-join the view on `file_path`; where a field is now typed,
   replace the `fo_json_*` extraction with field access, and read maps through
   `fo_map_*`; repoint the 24 unit tests at the views — `impl` — R3.5, R3.6, R5.4
   - Verify: `dbt build --target ci --vars '{anonymize: true}'` green; unit tests pass
8. Remove batching: the six models to plain tables; delete `stg_raw__season_responses`,
   `season_start`, `first_season_start`, `fo_batches_back_to_first_season`, the three
   tests that guard batching, `test_dbt_batched_models.py`; drop the event-time flags from
   `check_tenant_isolation.py` — `impl` — R4.1, R4.2
   - Verify: `.agentic/gates` green, tenant isolation 0 differences
9. Rewrite the five singular tests that read captures (design.md, *Tests that read
   captures*) — `impl` — R3.5, R6.4
   - Verify: CI green; each still fails on a fixture row it is meant to catch (one
     deliberate break per test, reverted, noted on #150)
10. The BigQuery upload reads keys from `raw.captures` and payloads through `LandingZone`;
    keep its privacy check and projections; its tests repointed — `impl` — R5.2
    - Verify: `uv run pytest ingestion/tests/test_spike_load_bigquery.py`; a `--dry-run`
      on 2026 reports the same rows per endpoint as #83's run (5,366 in 9 endpoints)
11. AGENTS.md: how dbt reads the landing zone (the glob, the manifest join), the batched
    section removed, rule 1's wording for capture views; README: the local-profile
    recipe removed, `FO_LANDING_ROOT` described — `impl` — R7.1, R7.2
    - Verify: a reader of AGENTS.md finds no instruction that contradicts the code
      (checked by the reviewer)
12. Give `compare_warehouses.py` named exclusions (a relation, or a relation's column),
    failing on anything else missing; then build the real warehouse from empty and
    compare: load, `dbt build`, `dbt test` with the committed profile;
    `compare_warehouses.py` against task 1's copy, excluding exactly what R6.3 names —
    `judgment` — R6.1, R6.3, R6.4
    - Verify: every relation identical; #146's two tests pass; the other failures exactly
      #147's, with the same rows; times and peaks posted on #150
13. The ladder: a landing root of 2026 alone (hard links under `data/`) and of all eight
    seasons; load, build and test at 1, 2, 4, 8 GB — `judgment` — R6.2
    - Verify: the lowest passing rung is the same for both, posted on #150; a difference
      is reported to the owner, not tuned away
14. BigQuery: upload 2026, build the slice, compare — `judgment` — R5.1–R5.3
    - Verify: `compare_bigquery_slice.py` passes on every relation; bytes billed within
      5% of 6.277 GB; the owner's project passed explicitly
15. (last) Verify every acceptance criterion and expected value against real data —
    `judgment` — all
    - Verify: record the queries and results as a comment on #150
