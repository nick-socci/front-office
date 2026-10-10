# 0039. The optimal lineup is solved in a dbt Python model, with SciPy

- Status: accepted
- Date: 2026-10-09
- Spec: [0012-lineup-decisions](../specs/0012-lineup-decisions/design.md) · Issue: #12

## Context

Filling a lineup is an assignment problem: 18 slots with counts, 21 to 23 candidates,
each eligible for some slots. A greedy pass in SQL assigns a player eligible at two
slots twice, or blocks a better lineup. The issue names
`scipy.optimize.linear_sum_assignment` in a dbt Python model. The project has no Python
model, and neither `scipy` nor `numpy` installed; every transform so far is SQL, with
BigQuery planned.

Read from dbt-duckdb 1.11: a Python model runs in the dbt process, may return a DuckDB
relation, and can import local modules through the profile's `module_paths`. dbt cannot
unit-test a Python model. A prototype solved all 2,160 team-days of 2026 in 0.3 seconds.

## Decision drivers

- Exact, not approximately right.
- As little solver code to own as possible.
- In the dbt lineage, the tests and the isolation gate.
- Deterministic totals across builds.

## Considered options

1. **A dbt Python model calling SciPy**, the cost matrix in a plain module tested with
   pytest.
2. **A dbt Python model with a solver written here.**
3. **Greedy SQL.**
4. **A script outside dbt** that writes the result table.

## Decision

Recommended, for the owner to decide: **option 1**.

`int_fantasy__optimal_lineups` is a Python model. It reads the legal (player, slot)
pairs, calls `solve_team_day` in `dbt/python_modules/lineup_solver.py` per team-day,
and returns only (team-day, player, slot). Every value and total is computed in SQL
from that. `scipy` joins the dev dependency group.

Option 2 avoids two dependencies by owning the one piece of code most worth not
owning. Option 3 is not exact. Option 4 takes the result out of the DAG.

## Consequences

- Good: exactness comes from a library; what is tested here is the matrix and the
  rules.
- Good: no floating-point sum is made in Python, so totals are ordered sums in SQL like
  the rest of the project.
- Bad / accepted cost: `scipy` and `numpy` in the dev environment and CI.
- Bad / accepted cost: the first model dbt cannot unit-test. Its function is tested
  with pytest and its output with singular tests.
- Bad / accepted cost: not portable to BigQuery as it stands: a Python model there
  needs a Spark or BigQuery DataFrames runtime. This mart either stays DuckDB-only or
  the solver moves; decided in sub-project 3.
- Bad / accepted cost: a new directory of Python inside `dbt/`, on the profile's
  `module_paths`.
- Follow-ups: none.
