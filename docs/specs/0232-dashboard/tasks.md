# The dashboard over the marts, on `mothership` — tasks

Issue: #232 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #232 during the build, and this file is not edited to show it.

1. `int_fantasy__league_seasons` gains `scoring_type` and `latest_scoring_period` (its contract too). Then `dim_fantasy_teams` and `fct_team_standings`: schema YAML with contracts and generic tests, the
   unit tests (decided, tied and in-progress matchups; a `ROTO` league-season), and the singular test
   `fct_team_standings_record_matches_espn` (error for a complete regular season, warn for one in
   progress) with its plant in `dbt/plants/`. Then the two models — `impl` — R1.1 to R1.5
   - Verify: the unit tests fail before the models and pass after; `.agentic/gates`; `dbt build
     --select +fct_team_standings` on the real season gives *Expected values* rows 1 to 3 (C21's counts).
2. The same two models on BigQuery: `dbt run --empty` and `dbt test` into suffixed datasets, as
   AGENTS.md says, and the unit tests there, since they add a fixture form only if the build finds
   one. Record the result on #232 — `impl` — R1.1 to R1.4
   - Verify: both pass on BigQuery; `scripts/compare_warehouses.py` (or its bounded form) shows the
     two marts equal on the real season.
3. Judge the real-season standings: the 6 differences are C6's and no others, and 2026 matches
   ESPN's final standings as the owner remembers them — `judgment` — R1.2, R1.4
   - Verify: the query and the owner's word, on #232.
4. `ingestion/tests/test_extract.py`: the type map, the refusals (R2.5), rename-publish with a reader
   open, `extract_info`, a fake BigQuery reader that fails on any query, and the DuckDB path over
   `dbt/ci.duckdb` equal to its source. Then `front_office/extract.py` and `front-office
   extract-marts` — `impl` — R2.1 to R2.5, R2.7, R7.3
   - Verify: the tests fail first, then pass; `uv run mypy`; `ruff`.
5. The `marts_extract` asset, its deps on the exposure's dbt assets, `FO_DASHBOARD_EXTRACT`, and the
   code server unit's `/dashboard` volume. Tests first in `orchestration/tests/`: it is in `daily`,
   and an ephemeral instance with a failing dbt step skips it — `impl` — R2.1, R2.6
   - Verify: `uv run dagster definitions validate -m front_office_pipeline`; the tests.
6. `scripts/check_dashboard.py` and its planted failing queries (aggregate, window, arithmetic, an
   unlisted mart), as a gates step after the dbt build and in CI; the `dashboard` dependency group;
   ruff and mypy over `dashboard/` — `impl` — R4.1 to R4.3, R7.1
   - Verify: the plants fail the check; the gates run it green on no queries.
7. The app: `data.py`, `format.py` (with its unit tests), the freshness banner and the no-extract
   page, then the five pages and their `queries/*.sql`, with `AppTest` per page over an extract of
   the CI warehouse. Rewrite the `front_office_dashboard` exposure to name what the queries read —
   `impl` — R3.1 to R3.4, R4.1, R6.1 to R6.3, R7.2
   - Verify: `check_dashboard.py` and the `AppTest`s green in the gates; `streamlit run` on the laptop
     over an extract of the real DuckDB warehouse opens every page.
8. Read every page over the real season on the laptop: labels say what the columns mean (R3.2),
   innings read as thirds, flags appear where the marts set them. The owner looks at it before it is
   deployed — `judgment` — R3.1 to R3.4
   - Verify: the owner's notes on #232, and any change they ask for.
9. The image: `.containerignore` keeps `dashboard/`, the `dashboard` group, `ENV FO_GIT_COMMIT`, and
   the smoke import. Then `deploy/quadlet/front-office-dashboard.container`, and the
   runbook's *The dashboard*, plus the deploy and roll-back lines. Deploy to `mothership` by the
   runbook, with the owner's go-ahead. Make the first extract by hand in the code server (R2.7).
   Measure the peak PSS over a session that opens every page for every season, with and without a
   `daily` beside it, and set `--memory=` from it. Show what the container can reach (127.0.0.1:4266
   and :3000 refused from inside it) and that the port answers only on the loopback. Record the
   image's size and build time — `judgment` — R5.1 to R5.5
   - Verify: the evidence on #232, as *Expected values* rows "Dashboard memory" and
     "Reachability" say.
10. (last) Verify every acceptance criterion and expected value against real data — `judgment` — all
    - Verify: on #232, the extract equals the laptop's DuckDB marts (`except all` both ways, per
      mart); 0 bytes billed by `marts_extract` in the run's job list; the standings rows; the
      memory and reachability evidence; the monthly cost row left open until #218's R7.3, and said
      so.
