# A group's correlation is the same on every build — requirements

Issue: #115 · Tier: M · Status: draft

## Problem

`reconciliation.rec_fantasy__category_wins_by_group` is a view with one row per
league-season and replacement group. Its `correlation` column is `corr(category_wins_added,
total_value)` with no stated order, and the last digit of that aggregate depends on the
order its rows arrive in. Two builds of the same commit (`0df7e6e`) from the same raw
table differ in `correlation` on all three rows, by 1e-16 to 8e-16, and
`scripts/compare_warehouses.py --strict-columns` exits 1: 55 of 56 relations identical
(#115).

The cause is confirmed (read-only, 2026-10-10, DuckDB 1.5.5): the 580 pairs of the real
2026 season, written to a table in 12 different row orders, gave 12 different
correlations, with one thread and with four. The view's `slope`, three lines above in
the same CTE, is summed `order by platform_player_id, fantasy_team_id` and gave one
value in all 12.

The rule already exists. Spec 0028's R4.13 (owner, 2026-10-04) says every sum or average
of non-integer values in a model is computed in a fixed order, and the README says builds
are reproducible to the last digit since #28. `corr` was added afterwards, in #94, and is
the third aggregate to break the same way (`stddev_pop` in #55, `avg` in #58).

## Goals

- Two builds of the same commit from the same raw table are equal in every relation,
  compared exactly.
- The README's sentence about exact comparison is true without an exception.
- The rule is written where the next aggregate will be checked against it.

## No-gos

- **No change to what the view means.** Same grain, same columns, names, order and
  types; `slope`, `pairs`, `pairs_unmeasured`, `matchups_rescored`, `is_judged` and
  `problem` keep their expressions, and their 2026 values exactly. `correlation` moves once, in its last digits.
- **No rounding** of any column, and no change to `compare_warehouses.py` or its
  defaults.
- **No change to the thresholds** the view judges on (100 matchups, 100 pairs, 0.75,
  0.34 to 0.47): those are ADR 0009 and #94's.
- **No change to any other model.** The other `avg()` and `median()` calls are named
  below and left as they are.
- **No BigQuery variant.** An ordered aggregate is DuckDB syntax, as the ordered sums of
  R4.13 already are; porting them is that sub-project's work.

## Rabbit holes

- A lint or test that finds every unordered floating-point aggregate in the project →
  not built. The rule is written down (R3) and the real-season check (R2) catches a
  breach in any relation, not only this one.
- Making `rec_fantasy__category_wins_added` non-empty in CI so the view has rows there →
  not here; it is ADR 0030's follow-up. The view is tested through dbt unit tests, as
  today.
- Asking why DuckDB's `corr` is order-dependent with one thread → not needed: any
  floating-point sum is, and the fix does not depend on the answer.

## Requirements

### R1. The correlation does not depend on row order

- R1.1 THE SYSTEM SHALL compute `correlation` in `rec_fantasy__category_wins_by_group`
  over a group's pairs taken in the order (`platform_player_id`, `fantasy_team_id`), the
  order `slope` already uses.
- R1.2 WHEN the rows of `rec_fantasy__category_wins_added` are stored in a different
  physical order THE SYSTEM SHALL return the same `correlation` for every group, bit for
  bit.
- R1.3 THE SYSTEM SHALL leave a pair with a null `category_wins_added` or a null
  `total_value` out of the correlation, as `corr` does today.
- R1.4 THE SYSTEM SHALL leave the view's grain, column names, column order and column
  types unchanged, and the expression of every column other than `correlation`. On the
  2026 season every other column keeps its value. (`is_judged` and `problem` read
  `correlation >= 0.75`, so for a group within 1e-15 of 0.75 they could differ from what
  an unordered build happened to give; the nearest 2026 group is 0.056 away.)

### R2. The build is reproducible, and that is shown on the real season

- R2.1 WHEN the real season is built twice from the same raw table at the same commit
  THE SYSTEM SHALL produce two warehouses that `compare_warehouses.py --strict-columns`
  reports as identical in every relation, with no `--round-doubles`.
- R2.2 WHEN a copy of the real warehouse has the rows of
  `rec_fantasy__category_wins_added` rewritten in another order, THE SYSTEM SHALL give
  an exact comparison of the copy with the original that reports no difference. (This is
  the check that does not rely on two builds happening to store rows differently.)
- R2.3 The same check as R2.2, run on the view as it is before this change, SHALL report
  `rec_fantasy__category_wins_by_group` as differing: the control that shows the check
  can fail.

### R3. The rule is written down

- R3.1 THE SYSTEM SHALL record, as an ADR, that every floating-point aggregate whose
  result depends on the order of its rows is computed in a fixed, stated order, and that
  a sum or average is exempt only where it is exact: every input integer-valued and
  the sum of their magnitudes below 2^53, the largest range in which a `double` holds
  every integer.
- R3.2 `AGENTS.md` SHALL carry the rule in one entry under *dbt gotchas*, naming the
  three aggregates that have broken it. (Decision for the owner: see the PR.)
- R3.3 The comment on `correlation` in the model SHALL say why the order is stated, in
  the terms the comment on `slope` uses.

## Expected values

Measured read-only on `data/warehouse.duckdb`, 2026-10-10, DuckDB 1.5.5. The `after`
correlations were measured by a probe that re-wrote the view's join by hand; the build
confirms them from the view itself, and a difference from this table is reported, not
adjusted to.

| Check | Expected | How to verify |
|---|---|---|
| Rows of the view, 2026 | 3: RP, SP, hitter | `select count(*)` |
| `matchups_rescored` | 143 on each row, unchanged | query |
| `pairs` / `pairs_unmeasured` | RP 107 / 0, SP 212 / 0, hitter 261 / 0; 580 in all, unchanged | query |
| `slope` | RP 0.3253481364697923, SP 0.4264251626413973, hitter 0.40030259479853525, unchanged to the digit | query, before against after |
| `correlation`, after | RP 0.6943751430614886, SP 0.8428935642957394, hitter 0.811007608129785 | query |
| `correlation`, movement | at most 1e-15 on each row from the value before | query, before against after |
| `is_judged` / `problem` | SP and hitter judged, RP not; `problem` null on all three, unchanged | query; `values_track_rescored_category_wins` passes |
| Reordered copy, after the change | 56 relations compared, 56 identical | R2.2 |
| Reordered copy, before the change | 55 identical, `rec_fantasy__category_wins_by_group` differs | R2.3 |
| Two builds of the commit | 56 identical, exact, `--strict-columns` | R2.1 |
| Every other relation, before against after | identical, exact | `compare_warehouses.py` old against new: the one difference is this view's `correlation` |
| CI | the view has 0 rows on the fixtures, as today; counts of the gate unchanged but for the one unit test added | `.agentic/gates` |
