# 0104. The solver rounds each option value to 12 decimals, so both warehouses break ties alike

- Status: proposed
- Date: 2026-10-26
- Spec: [0137-lineup-solver-on-bigquery](../specs/0137-lineup-solver-on-bigquery/design.md) · Issue: #137

## Context

BigQuery cannot be told the order of a float aggregate, so its floats can differ from
DuckDB's in the last digits (ADR 0053, #139). The solver's input is a float,
`option_value`. On the real season, BigQuery's values equal DuckDB's exactly in 106,110 of
437,559 options. The largest relative difference is 1.05e-11 (spec 0137, C8). That is
well inside ADR 0053's tolerance, but the solver picks among exact ties, and noise picks
for it. BigQuery's lineups differ from DuckDB's in 1,896 rows over 1,187 team-days. In
each of those team-days the two lineups are worth the same to within 4.4e-16. In 1,093 of
them the same players sit in other slots, and in 94 other players are chosen (C9). Since
those rows are integers and text, ADR 0053 holds them exactly, and they fail.

The tie bonus of spec 0012 is 1e-9 per slot. Option values run from 6.6e-6 to 5.31 (C12).

## Decision drivers

- BigQuery's solver gives DuckDB's rows, so the readers' non-float columns compare exactly.
- The solver's rules do not change. No lineup becomes worse, and none is chosen by noise.
- The change to the DuckDB warehouse is small, measured and explained.
- Independent of #139.

## Considered options

1. **Round each value to 12 decimals, in Python, inside the function, on both
   warehouses.** The noise (≤ 1.8e-15) vanishes except where it straddles a rounding
   boundary. The rounding error (≤ 5e-13 a value, ≤ 2e-10 over a 367-option period) stays
   under the 1e-9 tie bonus.
2. **Round to 9 decimals.** Fewer straddles (none measured), but the rounding error per
   lineup is of the order of the tie bonus.
3. **Leave the inputs as they are and compare the solver by value.** BigQuery's rows may
   differ from DuckDB's only within ties. The comparison would check, per team-day, equal
   value and kept count instead of equal rows, and the readers' integer columns would need
   the same exception. A BigQuery build would not repeat itself (ADR 0053).
4. **Wait for #139** to make BigQuery's floats DuckDB's. That issue is undecided, and it
   may decide on a tolerance, which would leave this unsolved.

## Decision

Chosen by the owner on 2026-10-26, going through the spec's decisions, as recommended:
**option 1**.

The entry point applies `round(value, 12)` before solving. That is Python's correctly
rounded `round`, the same on 3.11 and 3.13, so both warehouses round a given double alike.
Solving both warehouses' inputs this way gives identical rows on the real season (C10). 16
values straddled a boundary there, and none of them changed a lineup. On DuckDB it re-breaks
1,231 team-days of 911 team-periods (1,987 rows each way). Each change is a tie: the value
gap is at most 6.7e-16, the size and kept count are unchanged, and each team-period credits
the same value under the start rule (C11). Under BigQuery's own runtime (Python 3.11,
SciPy 1.17.1) the rounded solve gives the same rows from either warehouse's inputs (C19).

Option 2 trades a straddle risk for a rounding error as large as the tie bonus. Option 3
gives up exact comparison for the four relations that matter most to a reader of this
project, and keeps a build that does not repeat itself. Option 4 leaves the solver off
BigQuery for an undecided issue.

## Consequences

- Good: both warehouses give the same lineups, and the readers' integer and text columns
  compare exactly.
- Good: DuckDB's own choice among ties no longer depends on the last digit of a float sum.
- Bad / accepted cost: DuckDB's optimal lineups change once, in 1,231 team-days, all ties.
  The readers change with them, in those team-periods only.
- Bad / accepted cost: a straddle can still split the warehouses where it meets a tie. That
  fails the comparison (spec 0137, R3.2), which prints the team-days (R3.3), and goes to the
  owner. The choices then are another number of decimals, option 3, or waiting on #139.
- Follow-ups: if #139 makes BigQuery's floats exact, the rounding becomes unnecessary but
  harmless.
