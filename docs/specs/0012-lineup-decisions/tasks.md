# Lineup decisions: what was left on the bench — tasks

Issue: #12 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #12 during the build, and this file is not edited to show
them.

Built after #60 merges (PR #106). The first commit of the build accepts ADRs 0037 to
0039.

1. Spike: a Python model that imports a local module and returns a relation —
   `judgment` — R3.2, R3.3, the design's risks and open questions
   - On a scratch branch or in the worktree, uncommitted: add `scipy` to the dev group;
     a throwaway Python model that imports a function from `dbt/python_modules`, calls
     `linear_sum_assignment`, and returns a DuckDB relation built from Python rows;
     a throwaway SQL model with a dbt unit test that gives the Python model as an input.
   - Verify: `dbt build --target ci --select` of the two passes, and the same with
     `check_tenant_isolation.py`'s way of running dbt (another working directory for
     the warehouse). The findings are posted on #12. If any of the three does not work,
     stop and say so before writing anything else.
2. Record the starting point — `judgment` — expected values
   - Real season and CI: the gates' counts and warnings; the counts in the expected
     values that exist before the build (team-days, candidates, sides).
   - Verify: posted on #12.
3. The seed column — `impl` — R1.1
   - `make_espn_seeds.py` and its test first; regenerate the seed with the script.
   - Verify: `git diff dbt/seeds/` shows one added column; `dbt seed --target ci`
     passes; on the real warehouse, `dbt seed --full-refresh --select
     espn_lineup_slots` once.
4. Day values, tests first — `impl` — R1.2–R1.5
   - The unit test and YAML, seen to fail; then `int_fantasy__candidate_day_values`
     and the singular test of R1.5.
   - Verify: `dbt build --target ci --select int_fantasy__candidate_day_values` passes.
5. Slots and options, tests first — `impl` — R2.1–R2.4
   - Verify: `dbt build --target ci --select int_fantasy__lineup_slots
     int_fantasy__lineup_options` passes.
6. The solver, tests first — `impl` — R3.1, R3.2, R3.4, R3.6, R6.1
   - `test_lineup_solver.py` with the cases of R6.1, seen to fail; then
     `dbt/python_modules/lineup_solver.py`; `pyproject.toml` and the lock.
   - Verify: `uv run pytest`, `uv run ruff check`, `uv sync --locked` pass.
7. The Python model — `impl` — R3.3, R3.5, R6.2
   - `optimal_lineups_are_legal` and the YAML first; then the model and the
     `module_paths` setting.
   - Verify: `dbt build --target ci --select int_fantasy__optimal_lineups` passes.
8. `fct_lineup_decisions`, tests first — `impl` — R4.1–R4.8
   - Verify: `dbt build --target ci --select fct_lineup_decisions` passes.
9. `fct_lineup_decision_categories`, tests first — `impl` — R5.1–R5.4
   - Verify: `dbt build --target ci --select fct_lineup_decision_categories` passes.
10. Headers and descriptions — `judgment` — R6.4
    - Every new model's header and the two marts' YAML descriptions say: hindsight
      opportunity, the rule of R3.1, what eligibility this is, that the starts limit is
      not applied, and (Python model) the BigQuery implication.
    - Verify: read against ADRs 0037 to 0039.
11. (last) Verify — `judgment` — all requirements, expected values
    - `.agentic/gates`. On the real season, `dbt build --select
      int_fantasy__candidate_day_values+`, then every row of the expected values.
    - Verify: the table of expected against measured, real season and CI, as a comment
      on #12, with the worst team-day read by hand against ESPN's box score as the issue asks. A number
      that differs from the prototype's is reported with its cause before the PR is
      opened.
