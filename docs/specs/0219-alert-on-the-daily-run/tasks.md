# Tell the owner when a daily run fails or a feed goes stale — tasks

Issue: #219 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #219 during the build, and this file is not edited to show it.

1. `orchestration/tests/test_alerts.py`: `ping_key`, `outcome`, `failed`, `report`, `alert_lines`
   and `send`, as the *Test strategy* rows for R1.1, R1.2, R1.5, R2.1, R2.2, R2.5 and R3.1 to R3.3
   say; runs on an ephemeral instance, a fake opener, a planted key file — `impl` — R1.1, R1.2,
   R1.5, R2.1, R2.2, R2.5, R3.1 to R3.3
   - Verify: the tests fail (no module).
2. `orchestration/front_office_pipeline/alerts.py`, as *Detailed design* — `impl` — same
   - Verify: task 1's tests pass; `uv run mypy` and `ruff` clean.
3. `sensors.py`, the three run-status sensors, and their place in `build_defs()`; tests first in
   `test_definitions.py` (three sensors, `RUNNING`, exactly `daily` and `idmap`) and a sensor-body
   test for the missing key (R1.4). Record on #219 what a cancelled run and a run monitor's timeout
   leave in the events, from an ephemeral instance — `impl` — R1.3, R1.4
   - Verify: `uv run dagster definitions validate -m front_office_pipeline` loads, with and without
     `FO_HEALTHCHECKS_PING_KEY_FILE`.
4. The dbt step's `failed_nodes`: a `run_results.json` fixture test, then the catch in
   `front_office_dbt` — `impl` — R3.4
   - Verify: the fixture test; the existing dbt asset tests still pass.
5. `_raw_feeds__sources.yml` branches on `target.type` (the exact text in *Detailed design*), and
   its header comment is rewritten; a test parses the manifest for `ci` and `bq` (a dummy project)
   and asserts each `loaded_at_field` and filter — `impl` — R4.1
   - Verify: `dbt source freshness --target ci --select source:raw_feeds` gives C12's statuses
     (rc 1, error, error, warn); `--target bq` exits 0 with three results, as C11.
6. `source_freshness` as a multi-asset with three checks from `sources.json`, and in `daily` on both
   warehouses; `sources.json` fixture tests first, and 0217's R3.5 test replaced — `impl` — R4.2 to
   R4.4
   - Verify: the fixture tests; `test_definitions.py` for both settings.
7. `front-office-code.container` mounts the key file and sets the variable; `test_deploy_files.py`
   holds that only the code unit has either — `impl` — R5.1
   - Verify: the deploy tests.
8. Docs: the runbook's *Alerts* and *When an alert arrives*; AGENTS.md (rule 3 names the ping key;
   the freshness sentence); ADR 0050's status `amended by 0143`; 0217's design gets an *Amendments*
   line that R3.5 is replaced by 0219 R4.2 — `impl` — R5.2, R5.3
   - Verify: the ADR status tests; `.agentic/gates`.
9. Rehearse every failure on the laptop, on the real channel — `judgment` — R1 to R4, *Done when* of
   #219
   - The owner first creates a second healthchecks.io project for rehearsals, its two checks with
     the production slugs, and its ping key in a file on the laptop: an agent never handles the key.
   - The laptop's own Dagster instance (a scratch `DAGSTER_HOME`), `dagster dev` so the daemon
     launches the runs and evaluates the sensors, with `FO_WAREHOUSE=duckdb`, the laptop's
     landing zone and warehouse, and `FO_HEALTHCHECKS_PING_KEY_FILE` naming the rehearsal key.
   - Expired cookies, and with them a stale `espn` feed: `ESPN_S2` set to a bad value in the
     environment of `dagster dev` (C14; `.env` is not touched). If the laptop's newest settings
     capture is under 36 h old, the stale feed is forced on its own instead (for example an
     uncommitted lower `warn_after`), and that is recorded.
   - A new tie and a red dbt test: each an uncommitted change on a local branch that makes the
     condition true in the laptop's warehouse, reverted after, and the warehouse rebuilt. The
     change chosen, and its revert, are recorded.
   - A missed run: the rehearsal check's cron set to a time with the daemon stopped.
   - Recovery: a clean run after a failure gives the UP email.
   - Verify: each email and each body recorded on #219 (bodies as received: they hold no secret by
     R3); every body searched for the key, `league_id=`, `/data`, `ESPN_S2=` and `SWID=`, and the
     instance's events and the logs for the key, and none found.
10. Deploy to `mothership` — `judgment` — R1.3, R2.3, R4.2, R5.1
   - The owner creates the production project's two checks (slug, cron, `America/New_York`, grace 2 h
     30 min), its email integration, and `~/secrets/healthchecks-ping-key` (0400).
   - Deploy as the runbook says; the sensors show `RUNNING` in `dagster sensor list`.
   - One hand-launched `daily` pings `front-office-daily` (the body shows the three freshness checks
     passing on BigQuery), and one `idmap` pings `front-office-idmap`.
   - Restart the daemon between a run's end and its sensor tick: exactly one ping (*Open questions*).
   - Verify: the check's log; `INFORMATION_SCHEMA.JOBS` for the run's three freshness queries and
     their bytes billed, recorded on #219.
11. (last) Verify every acceptance criterion and expected value against the real season's
    deployment — `judgment` — all
    - Verify: each row of *Expected values* with its result, as a comment on #219.
