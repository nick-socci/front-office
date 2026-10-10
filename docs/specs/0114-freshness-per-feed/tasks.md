# Source freshness is one age per feed — tasks

Issue: #114 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #114 during the build, and this file is not edited to show
them.

The first commit of the build accepts ADR 0050.

1. Record the starting point — `judgment` — R1.1, R4.1, expected values
   - On the fixture warehouse the gates build at the base commit: the `dbt build` counts,
     and `dbt source freshness --target ci`: one result, for `raw.api_responses`, with
     its `max_loaded_at`.
   - Read the order of calls in `backfill mlb` and `backfill espn` again at the base
     commit. If the schedule is no longer the first thing a full `mlb` run lands, or
     settings no longer the first call of an `espn` run that needs the login, stop and
     ask the owner: the run markers of R1.1 rest on it.
   - Verify: the counts, the result and the order of calls posted on #114. If the counts
     differ from the expected values, say so and carry on with the counts found: they
     are the "before" of R4.1.
2. The tests of the declarations, seen to fail — `impl` — R1.1, R1.3, R2.1, R2.2, R3.1,
   R3.2, R3.3
   - `ingestion/tests/test_source_freshness.py`, with the six pytest rows of the
     design's test strategy, each with what it catches in its docstring. The tests read
     the YAML under `dbt/models/staging/`, and the fixtures only through
     `LandingZone.committed`.
   - Verify: `uv run pytest ingestion/tests/test_source_freshness.py` fails on every new
     test. A test that passes before task 3 is reported, not committed.
3. The declarations — `impl` — R1.1, R1.3, R2.1, R2.2, R5.1, R5.2
   - `dbt/models/staging/_raw_feeds__sources.yml` as the design writes it; `freshness`
     and `loaded_at_field` removed from `api_responses` in `_mlb__sources.yml`, and its
     comment replaced as the design says.
   - Verify: the tests of task 2 pass; `cd dbt && DBT_PROFILES_DIR=. uv run dbt parse
     --target ci` reports 4 sources and no warning.
4. Freshness on the fixtures, by hand — `judgment` — R1.2, R1.4, R1.5, expected values
   - `dbt source freshness --target ci` on the fixture warehouse; read
     `target/sources.json`.
   - On scratch copies of the fixture warehouse, never the one the gates build:
     the `espn` settings rows' `fetched_at` set to one hour ago (R1.4); one
     `pro_schedule` row's `fetched_at` set to one hour ago, settings untouched (R1.5);
     the `idmap` rows deleted, to record what dbt reports for a filter that matches no
     row.
   - Verify: the results of all four runs posted on #114, with the expected
     `max_loaded_at` and statuses, and no result for `raw.api_responses` in any.
5. Freshness on the real season — `judgment` — R1.2, expected values
   - With the owner's go-ahead, since dbt opens the warehouse for writing:
     `dbt source freshness` on `data/warehouse.duckdb`, against
     `select source, endpoint, max(fetched_at) from raw.api_responses group by all`.
   - Verify: the three `max_loaded_at` equal the query's for the three run markers, and
     each status follows its own age; posted on #114.
6. The README — `impl` — R5.1, R5.2
   - The paragraph "Source freshness is defined, and dormant" says one age per feed,
     which capture marks a run, the thresholds, and the two remaining limits. The
     sentence about one age for three sources and its link to #114 go.
   - Verify: `git diff README.md` is that paragraph alone.
7. (last) Gates, and every expected value — `judgment` — R4.1, R4.2, all
   - `.agentic/gates`: the `dbt build` counts equal task 1's.
   - `git diff --stat origin/main`: no `.sql` file, nothing under `.agentic/`,
     `.github/` or `ingestion/src/`.
   - Verify: every row of the expected values recorded as a comment on #114, with the
     commands.
