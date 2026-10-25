# ESPN's rate stats are not staged — tasks

Issue: #194 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #194 during the build, and this file is not edited to show it.

1. Measure the baseline. Record the row counts of both line models, the count of each of
   the 7 unnamed stat ids, and C1's non-finite counts, on the current real warehouse and
   on a CI build of `main`. Keep both warehouses for task 8. — `judgment` — R2.3, R2.4,
   R4.1
   - Verify: the numbers equal C8 to C10; if not, stop and say why before building.
2. Extend `ingestion/tests/test_make_espn_seeds.py`: the column is written; exactly the 15
   ids are true; an id missing from `STATS_MAP` stops generation. Watch the new tests fail
   (the names do not exist yet). Then add `RATE_STAT_IDS`, the check and the column to
   `scripts/make_espn_seeds.py`, regenerate the seeds, and add `is_rate` with `not_null`
   to the seed's YAML. — `impl` — R1.1, R1.2, R1.3
   - Verify: `uv run pytest ingestion/tests/test_make_espn_seeds.py`; `git diff dbt/seeds`
     changes only `espn_stat_ids.csv`, by the new column (15 `true`, 63 `false`).
3. Add the dispatched `fo_is_finite` to `dbt/macros/portable.sql` (design.md). — `impl` —
   R3.4
   - Verify: `dbt run --target bq --selector bigquery_slice --empty` compiles (task 7
     runs it with the tests); a DuckDB select of `fo_is_finite` over 1.0, NaN, infinity
     and null gives true, false, false, null.
4. Write the two singular tests and their plant files (design.md, *Tests*). Run them on
   the CI build of `main` and watch the no-rate test fail on its 2,834 + 656 rate rows. —
   `impl` — R3.1, R3.2, R3.3
   - Verify: the no-rate test fails on `main`'s CI build with one row per model and rate
     stat id; the value test passes there (C10).
5. Drop the rates in `stg_espn__player_game_stats` and `stg_espn__matchup_player_lines`
   (left join to the seed, keep a null `is_rate`), and rewrite their opening comments
   and YAML descriptions. — `impl` — R2.1, R2.2, R2.3, R4.2
   - Verify: both tests pass on a CI build of the branch; `scripts/check_plants.py`
     passes with every new plant giving its expected result.
6. Run `.agentic/gates`. — `impl` — all
   - Verify: green; the plant gate runs the two new files; tenant isolation 0 differing
     pairs.
7. Check BigQuery: `dbt build --target bq --selector bigquery_slice --empty`, with
   `FO_BQ_PROJECT` set as for #135. `build`, not `run`, so that the two singular tests
   (and so `fo_is_finite`) run on BigQuery, on empty tables, at no cost. Update
   `test_bigquery_slice.py`'s pinned test count for the two new singular tests. —
   `judgment` — R3.4
   - Verify: the `--empty` build succeeds, with both new tests in its output;
     `uv run pytest ingestion/tests/test_bigquery_slice.py`.
8. (last) Verify every acceptance criterion and expected value against real data. —
   `judgment` — all
   - Build the branch on a copy of the real warehouse (after `dbt seed --full-refresh`
     there). `compare_warehouses.py` against task 1's baseline: only the two line models
     differ, by removed rows only (1,343,928 and 334,395). The 7 reconciliation models
     are identical. The 7 unnamed ids keep their counts. Both new tests pass, and the
     non-finite count is 0.
   - On CI builds of `main` and the branch: only the two line models differ (2,834 and
     656 rows out).
   - `espn_stat_ids`, which `compare_warehouses.py` does not read (it is in the `main`
     schema): compared directly on both CI builds. The same 78 rows with the same three
     columns, plus `is_rate`: 15 `true`, 63 `false`.
   - Record each expected-values row, with its query and result, as a comment on #194.
