# Past seasons' rosters and boxscores — tasks

Issue: #83 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #83 during the build, and this file is not edited to show
them. The build's first commit accepts ADRs 0055 to 0057, except that 0055 is accepted
only after task 5.

1. Record the starting point — `judgment` — expected values, R6.6, R6.7
   - On `main`: a copy of the real warehouse; row counts of the relations this spec
     touches; the real build's result, wall time and peak memory; `.agentic/gates`.
   - Verify: posted on #83.
2. Tests for the two `--only` values — `impl` — R5.1, R1.7
   - pytest with a fake transport, seen to fail for the right reason.
   - Verify: `uv run pytest` fails on exactly the new tests.
3. `--only rosters`, `--only matchup-days`, `espn/matchup_days.py` — `impl` — R1.1–R1.5,
   R1.7
   - Verify: `uv run pytest`, `ruff`, `mypy` clean; no request made.
4. dbt tests, then `stg_espn__matchup_days` and the combined
   `int_fantasy__matchup_periods` — `impl` — R2.1–R2.7, R5.2, R5.3, R5.5
   - Unit tests and the three singular tests first; then the models, the repointed
     tests and the yml.
   - Verify: `.agentic/gates`; CI warnings unchanged at 3; `git status fixtures` clean.
5. Land the marker for 2026 and 2025 and compare — `judgment` — R1.6, R6.1
   - One request first for R1.6. Then `--only matchup-days` for both seasons, load,
     build the two models on the real warehouse.
   - Verify: 368 scoring periods, 0 differing from `pointsByScoringPeriod`, posted on
     #83 with the periods of interest named (final period, All-Star period, a playoff
     period with a bye). Any difference stops the build for the owner.
6. Complete games — `impl` — R3.1–R3.3, R5.4
   - The unit test first; then the macro, the accepted values, the seed row.
   - Verify: the unit test passes; CI `dbt build` clean; 2026 rows unchanged in CI.
7. `has_transaction_log` — `impl` — R4.1–R4.4, R5.5
   - Verify: unit tests and the singular test pass; `.agentic/gates`.
8. Land 2025 whole — `judgment` — R6.2, R6.4, R6.10
   - First, R6.10's five requests; a served log stops the build.
   - `backfill mlb --season 2025`, `backfill espn --season 2025 --only rosters`, load,
     real build.
   - Verify: 2025 is covered and builds; its reconciliation rows posted on #83.
9. Land 2018, 2019 and 2021 to 2024 — `judgment` — R6.2, R6.5
   - Per season: `backfill mlb`, `--only rosters`, `--only matchup-days`. Every command's
     exit code and request count recorded.
   - Verify: R6.2's captures present per season, by query on `raw.api_responses`.
10. Build the real seasons and take what does not hold to the owner — `judgment` —
    R6.3–R6.6, R6.8
    - Every season built before anything is reported; findings reported together.
    - Verify: `dbt build` result, the differences per season, the audit's findings per
      season, time and memory, posted on #83.
11. (last before the PR) Verify every acceptance criterion and expected value against
    real data, except R6.9 — `judgment` — all but R6.9
    - Including R6.7's `EXCEPT ALL` for 2026 against task 1's copy.
    - Verify: the expected-values table, filled in, as a comment on #83. The PR says
      that R6.9 is still owed and when it falls due.
12. (owed after the PR, at least seven days after task 9; #83 stays open until it is
    done) The second boxscore pass — `judgment` — R6.9
    - Verify: boxscores changed per season and model rows moved, posted on #83.
