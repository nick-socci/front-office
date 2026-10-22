# The optimal lineup is chosen a matchup period at a time, within the games-started limit — tasks

Issue: #164 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #164 during the build, and this file is not edited to show it.

1. pytest for the solver's new parts, failing first: `required_per_role`, `forced`,
   `Infeasible`, `Option.is_start`, and every `solve_team_period` case of R5.1 (including
   the brute force over 2–3-day periods within a cap) — `impl` — R1.1–R1.8, R5.1
   - Verify: `uv run pytest ingestion/tests/test_lineup_solver.py` fails only on the new
     tests, with the functions missing.
2. Implement `required_per_role`, `forced`, `Infeasible`, `Option.is_start` and
   `solve_team_period(days, slots, start_limit, start_cap)` in
   `dbt/python_modules/lineup_solver.py`, as design.md *Detailed design* — `impl` —
   R1.1–R1.8
   - Verify: `uv run pytest ingestion/tests/test_lineup_solver.py` passes; the existing
     tests are unchanged and pass.
3. Model pytest first, then the model. `int_fantasy__optimal_lineups.py`:
   - groups by team-period and joins the periods and limits;
   - computes `start_cap` (R1.3);
   - blanks an unvalued period.

   Add the three cases to `test_optimal_lineups_model.py` — `impl` — R1.3, R1.4, R2.1
   - Verify: `uv run pytest ingestion/tests/test_optimal_lineups_model.py` passes.
4. Credit the optimal lineup:
   - in `fct_lineup_decisions`: `optimal_sum`, and `is_unvalued` per period;
   - in `int_fantasy__lineup_category_totals`: the `optimal` rows;
   - update both headers.

   — `impl` — R2.1, R3.1, R3.2, R3.3
   - Verify: CI build passes.
5. The tests per team-period, and the cap test:
   - restate the never-worse test per team-period (`gap_below_zero`), keeping
     `fewer_than_played` per day;
   - restate the no-churn test per team-period;
   - add `fct_lineup_decisions_keep_the_optimum_within_the_start_cap.sql`;
   - add the five plants of design.md.

   — `impl` — R3.4, R4.1, R4.2, R4.3, R5.2
   - Verify: `scripts/check_plants.py` on the new plant files passes. Each restated test,
     broken back to per-day, fails a plant, and the cap test fails one over the cap.
6. Run `.agentic/gates` — `impl` — R5.3
   - Verify: `All gates passed.`
7. Accept the ADRs and update the links: 0079 `superseded by` 0090; 0037 `amended by`
   0079 and 0090 — `impl` — (ADRs)
   - Verify: `uv run pytest ingestion/tests/test_adr_headers.py`.
8. (last) Verify every expected value against the real season — `judgment` — all
   - Build the eight-season warehouse from this branch, then run
     `scripts/compare_warehouses.py` against `main`'s:
     - only C9's 19 team-days change `optimal_value`, and only its 18 change lineup;
     - the 16 team-periods' sums equal C9's values (R4.4);
     - the category mart changes only on those 16 sides;
     - no team-period is over its cap;
     - `dbt test` passes;
     - the model's build time is reported.
   - Record the commands and results as a comment on #164.
