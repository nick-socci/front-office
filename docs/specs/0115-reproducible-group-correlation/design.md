# A group's correlation is the same on every build — design

Issue: #115 · Requirements: [requirements.md](requirements.md) · Tasks: [tasks.md](tasks.md)

## Overview

Three expressions change, and one of them changes a value. In the `groups` CTE of `rec_fantasy__category_wins_by_group`,
`corr(category_wins_added, total_value)` gains the `order by platform_player_id,
fantasy_team_id` that the two sums of `slope` beside it already carry. An ordered
aggregate (new dbt/DuckDB concept here only in that it is applied to `corr`: DuckDB lets
any aggregate take an `order by` inside its parentheses, and then feeds it the group's
rows in that order) gives the same digits whatever order the table's rows are stored in.
A unit test pins the value, the rule goes into an ADR and `AGENTS.md`, and the real
season is checked with a copy of the warehouse whose input rows are deliberately stored
in another order.

The two remaining `avg()` calls gain an order as well (R4; owner, 2026-10-10), which
moves no value on 2026.

No model's rows, grain or columns change. `correlation` moves once, in its last digits
(up to 1.2e-15 from the build it was measured against).

## Alternatives considered

Measured on the real 2026 pairs (580 rows, 3 groups), 12 row orders each, with 1 and
with 4 threads.

| | A — ordered `corr` (chosen) | B — formula from ordered sums | C — round the column | D — excuse the relation |
|---|---|---|---|---|
| Distinct results over 12 row orders | 1 | 1 | 1 at 12 decimals, on this data | 12 |
| Reproducible in principle | yes | yes | no: results either side of a rounding boundary round apart | no |
| Exact comparison passes | yes | yes | almost always | no, by design |
| Column means what it did | yes | yes, value differs in the 16th digit | no: a rounded figure | yes |
| Size of the change | one `order by` | five ordered sums and a formula | one `round()` | README and the compare habit |
| Follows R4.13 of spec 0028 | yes, the same device | yes | no | no |

**A — ordered `corr`.** The device the project already uses for sums, on the same key as
the line above it. Result on 2026: RP 0.6943751430614886, SP 0.8428935642957394, hitter
0.811007608129785, in all 24 runs.

**B — formula from ordered sums.** `(n·Σxy − Σx·Σy) / (√(n·Σxx − (Σx)²) · √(n·Σyy − (Σy)²))`
with each sum ordered. Stable (one result in 24 runs) and free of any dependence on how
DuckDB implements `corr`. It loses on cost and on numerics: five sums with matching
`filter` clauses to keep nulls out of each, where a mistake in one is a wrong
correlation rather than a wrong last digit; and the textbook formula subtracts two large
near-equal numbers, which `corr`'s running-mean method avoids.

**C — round the column.** Hides the symptom at 12 decimals on this data. It is not
reproducibility: a value within 1e-15 of a rounding boundary can still round two ways.
It also stores a figure that is neither the correlation nor a stated approximation of
it. The no-gos exclude it.

**D — excuse the relation.** What happens today by hand (`--round-doubles 12`). The
exact comparison then exits 1 on every rebuild, and a real difference in this view would
have to be told apart from the excused one by eye.

## Decisions

| ADR | Decision | Status |
|---|---|---|
| [0046](../../adr/0046-an-order-dependent-aggregate-is-computed-in-a-stated-order.md) | A floating-point aggregate that depends on row order is computed in a stated order; exact aggregates are exempt | accepted |

## Detailed design

### The model

`dbt/models/reconciliation/fantasy/rec_fantasy__category_wins_by_group.sql`, CTE
`groups`:

```sql
-- In the same fixed order as the sums above: corr() is a floating-point aggregate too,
-- and its last digit follows the order of its rows (ADR 0046).
corr(category_wins_added, total_value order by platform_player_id, fantasy_team_id)
    as correlation
```

- **The order is unique within a group.** A group is (`platform`, `league_id`, `season`,
  `replacement_group`), and `pairs` holds one row per (`platform_player_id`,
  `fantasy_team_id`) within a league-season: 580 rows, 580 distinct keys on 2026. A
  player has one replacement group in a league-season, so the two columns are a total
  order of each group's rows. An order with ties would leave the fault in place.
- **Nulls.** `corr` skips a pair in which either value is null, ordered or not (R1.3).
  2026 has no such pair (`pairs_unmeasured` is 0 on all three rows).
- **Nothing else in the file changes**: not the header comment's quoted correlations
  (0.85, 0.81, 0.69, which hold to two decimals), not `is_judged`, not `problem`.
- **If #116 has merged first**, the line is written as sqlfluff formats it; the change
  must pass `sqlfluff lint`. `slope`'s sums show the form the linter accepts.

`_rec_fantasy__models.yml`: `correlation` gains a description, which it lacks today:
"Pearson correlation of wins added and total_value over the measured pairs, taken in
player and team order so that it is the same on every build."

### The other aggregates

Every statistical aggregate in `dbt/models`, `dbt/macros` and `dbt/tests` on `main`
(`corr`, `avg`, `stddev*`, `var*`, `covar*`, `regr_*`, `median`, `quantile*`):

| Where | Aggregate | Order-dependent? |
|---|---|---|
| `rec_fantasy__category_wins_by_group` | `corr(category_wins_added, total_value)` | yes: this change |
| `int_fantasy__category_scales` | `avg(denominator)` | not on 2026 (0 of 1,144 non-null values are non-integer, the largest is 369), but only while that holds: ordered by this change (R4.1) |
| `int_fantasy__reported_matchup_margins` | `avg(score)`, counting categories only | not on 2026 (largest reported score 369), but a league with a non-integer counting category would make it so: ordered by this change (R4.2) |
| `int_fantasy__reported_matchup_margins` | `sum(parts.weight * reported.score)`, a rate category's denominator on one side | not read by the spec; found on 2026-10-10 while the owner's decisions were applied. A sum of two terms is the same either way round; of three or more non-integer terms it is not. How many components a denominator has, and whether their weights are whole numbers, was not checked: see Open questions |
| `int_fantasy__reported_matchup_margins` | `median(...)`, twice | no: a median is chosen, not summed |

The two averages become:

```sql
-- int_fantasy__category_scales, CTE side_denominators
avg(denominator order by matchup_id, is_home) as side_denominator

-- int_fantasy__reported_matchup_margins, CTE period_means
avg(score order by matchup_id, side) as mean_side_total
```

each with a comment in the terms of the one on `margin_scale` in the first model.
`scored_values` holds one row per matchup side and category, and `side_totals` one per
decided matchup, side and category, so within a group (one category of one
league-season; one category of one period) each order should identify one row. That is
read from the CTEs, not measured: task 1 measures it (R4.3).

Sums of doubles without an order were not swept by pattern (a `sum(` is not
recognisable as floating-point from the SQL alone). The evidence that none is exposed is
the comparison itself: 55 of 56 relations are identical across two builds.

### `AGENTS.md`

One entry under *dbt gotchas*:

> A floating-point aggregate (`sum`, `avg`, `corr`, `stddev`…) takes an `order by` on
> the grain's key inside its parentheses: the last digit depends on row order, row order
> changes between builds, and warehouses are compared exactly. Broken three times
> (`stddev_pop`, `avg`, `corr`); see ADR 0046. Exempt only if exact: integer-valued
> inputs whose magnitudes sum below 2^53, said in a comment starting `order-exempt:`.

### The reordered-copy check (R2.2, R2.3)

Local only, on the real season, and read-only on `data/warehouse.duckdb`:

1. Copy `data/warehouse.duckdb` to `data/warehouse_reordered.duckdb` (gitignored).
2. In the copy only, rewrite the rows of `reconciliation.rec_fantasy__category_wins_added`
   in another order, keeping the table and its constraints: move the rows to a temporary
   table, `delete`, and `insert … order by hash(platform_player_id, fantasy_team_id)`.
   Confirm 580 rows before and after.
3. `uv run python scripts/compare_warehouses.py data/warehouse.duckdb
   data/warehouse_reordered.duckdb --strict-columns`. A view is read from its own file
   (#101), so each side computes `correlation` from its own row order.

Run once on a warehouse built before the change (expected: the view differs, R2.3) and
once on one built after (expected: 56 identical, R2.2). The copy is deleted afterwards.
This is a procedure recorded on the issue, not a committed script: it is needed once.

## Test strategy

| Requirement | Test | Catches |
|---|---|---|
| R1.1, R1.2 | dbt unit test `category_wins_by_group_take_the_correlation_in_player_order`: five hitters whose wins and values are not multiples of one another, listed in the inputs in descending player order, with `correlation` expected to the last digit of the player-order result. Written first and seen to fail on the unordered `corr` | the `order by` removed, or put on a column that does not order the rows |
| R1.3 | the existing `category_wins_by_group_measure_the_slope_over_measured_pairs`, with `correlation` added to its expected row: the value the ordered `corr` gives over the three measured pairs alone, which is 1.0000000000000002 on DuckDB 1.5.5 and not 1 (wins are half of value, and the arithmetic is not exact). The fourth pair has a value of 100 and no wins | a null pair entering the correlation |
| R1.4 | the model's contract (names, order, types), and `compare_warehouses.py` before against after: this view differs in `correlation` only | a column, type or other value moved |
| R2.2, R2.3 | the reordered-copy check, before and after | order dependence left in this view; a check that cannot fail |
| R2.1 | two builds of the commit, compared exactly | order dependence anywhere else |
| R4.1, R4.2 | one dbt unit test for each average, with non-integer inputs listed in descending key order and the result pinned to the last digit; committed only if seen to fail on the unordered `avg()` | the `order by` removed |
| R4.3 | a query on the real season for a repeated key within a group | an order with ties |
| R4.4 | `compare_warehouses.py` before against after, exact | a value moved by the order |
| R3 | read by the owner in the PR | — |

What the unit test cannot do is change the physical order of a table: dbt gives a unit
test's rows as a `union all` in the order listed. Spiked outside dbt (DuckDB 1.5.5): on
400 random five-pair inputs listed in descending key order, `corr` in listing order and
`corr(... order by key)` differed in the last digit on 327, stably with 1 and 4 threads.
Whether the listing order survives the view's two joins inside a dbt unit test is not
known; see Open questions.

## Risks

- The unit test does not fail on the unordered `corr` — plausible, since a hash join may
  reorder five rows — R1.2 then rests on the reordered-copy check alone, which is local.
  Task 2 stops and reports instead of committing a test that cannot fail.
- A pinned 16-digit value breaks on a DuckDB upgrade that changes `corr`'s arithmetic —
  low likelihood, loud when it happens, and the real-season digits would have moved with
  it. Accepted: that is a change worth being told about.
- The measured `after` values came from a hand-written join, not the view — low — the
  build reads them from the view and reports any difference.

## Open questions

- Does a dbt unit test compare a `double` exactly, and does listing order reach `corr`
  through the joins? — task 2 answers both by seeing the test fail, and pass.
- Is `sum(parts.weight * reported.score)` in `int_fantasy__reported_matchup_margins`
  order-dependent? It is if some rate category's denominator has three or more
  components whose weighted scores are not all whole numbers. — task 1 reads the rules
  and answers. If it is, the owner decides whether it joins this change; it is not
  ordered without that decision.
- Can a unit test of either average fail on the unordered `avg()`? The same question as
  for `corr`, and the same rule: task 2 commits a test only if it is first seen to fail.
- Is `data/warehouse.duckdb` built from current `main`? The stored correlations match
  the issue's to 15 digits, which suggests so. — task 1 rebuilds or confirms.

## Review log

| Source | Finding | Resolution |
|---|---|---|
| design-review | F1 (P1): an average of integer-valued doubles is not always exact (`avg` of 1e16, 1, -1e16 depends on order) | The exemption in R3.1, ADR 0046 and the `AGENTS.md` entry is narrowed to integer-valued inputs summing below 2^53; the two exempt `avg()` calls are shown to be inside it (largest value 369) |
| design-review | F2 (P1): the three measured pairs of the existing unit test correlate at 1.0000000000000002 under the ordered `corr`, not 1 | The test pins the value DuckDB gives, read in task 2; design and tasks say so |
| design-review | F3 (P2): R1.4 said every other column is unchanged for any input, but `is_judged` and `problem` read the correlation | R1.4 now fixes the other columns' expressions, and their values on 2026, and names the boundary case |

## Amendments

- 2026-10-10, owner, on spec PR #118, before approval. Decisions 1 to 3 taken as
  proposed: the ordered `corr`, tier M with ADR 0046, and the entry in `AGENTS.md`.
  Decision 4 changed: the two remaining `avg()` calls are ordered in this change
  instead of being left as exempt (R4), because the exemption held for one league's
  2026 categories and not for the models. The question about `is_rate` goes with it.
  An unordered `sum` in `int_fantasy__reported_matchup_margins`, found while this was
  applied, is an open question and not part of the change.

- 2026-10-10, build, task 6. The expected values bound the movement of `correlation` at
  1e-15 on each row; SP moved by 1.2e-15 (0.8428935642957381 to 0.8428935642957394). The
  value after is the expected one to the digit. The value before is whatever an
  unordered build happened to give, and the bound was taken from the two builds #115
  compared, which is not a bound on a third. Nothing in the requirements depends on it:
  R1.4's remark about a group within 1e-15 of 0.75 concerns `is_judged`, and the nearest
  2026 group is 0.056 away.
- 2026-10-10, build, task 2. Both open questions about unit tests are answered: dbt
  compares a `double` exactly, and a listing order reaches the aggregate through the
  joins, but not on every run. On the unordered aggregates each new test fails on the
  last digit in most runs and passes in some (DuckDB's row order inside a unit test
  varies), so a removed `order by` is caught often, not always. The reordered-copy
  check on the real season is the one that cannot miss.
- 2026-10-10, owner, on PR #120 (review round 1 and one open question).
  - F1: the expected movement of `correlation` is corrected to what was measured, and
    said not to be a bound (requirements, *Expected values*; *Overview* above).
  - F2: a check that cannot miss is added (R5): `test_dbt_ordered_aggregate_rule.py`
    reads every model, singular test and macro, and fails on a statistical aggregate
    with no `order by` inside its parentheses and no `order-exempt:` comment. It runs
    in pytest, so in the gates and CI, as `test_dbt_json_rule.py` does for the JSON
    rule. A check that stores inputs in two physical orders, as the reviewer
    suggested, could not fail on the fixtures: the view's input is empty there and
    the averages' inputs are whole numbers. `sum` is not checked (R5.3). This lifts
    the first rabbit hole for the aggregates it names.
  - F3: the exemption in the `AGENTS.md` entry is on the sum of the inputs'
    magnitudes, as R3.1 and ADR 0046 have it, and names the comment the check reads.
  - The open question: `sum(parts.weight * reported.score)` is ordered by `component`
    (R4.5), with a unit test on a made-up rate of three components, seen to fail on
    the unordered sum in 2 of 6 runs (0.6000000000000001 against 0.6) and to pass
    in 4 of 4 with the order. `denominator_parts` carries `component` for it;
    (`platform`, `stat_key`, `part`, `component`) is unique in
    `int_fantasy__stat_components`, so the order has no ties.
- 2026-10-10, owner, on PR #120, after five review rounds of the check of R5. Each round
  found a narrower input the check misread, none of them written in this repository. The
  check reads SQL text and is a tripwire for the ordinary way of writing an aggregate; a
  rule that could not be fooled would read the SQL dbt compiles, parsed, and is not built
  here. What it now knows: `--`, `/* */` and `{# #}` comments, string literals, and that
  an order inside a Jinja block or expression may render nothing (R5.4). Two limits are
  accepted because they fail safe, and are pinned by a test: an exemption in a `/* */`
  comment is not read, and an order between two Jinja blocks of one call is flagged. No
  further review round is run on it.
