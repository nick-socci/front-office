# 0115. On BigQuery, a floating-point aggregate is a JavaScript fold over its rows in the stated order

- Status: proposed
- Date: 2026-10-29
- Spec: [0139-float-order-on-bigquery](../specs/0139-float-order-on-bigquery/design.md) · Issue: #139
- Amends: [0046](0046-an-order-dependent-aggregate-is-computed-in-a-stated-order.md), for BigQuery

## Context

ADR 0046 gives every floating-point aggregate an `order by` on the grain's key, so that
two DuckDB builds agree to the last digit. BigQuery refuses that syntax for `sum`, `avg`
and `corr`, so the BigQuery forms of `fo_sum_in_order`, `fo_avg_in_order` and
`fo_corr_in_order` leave the order out. ADR 0053 accepted the consequence for the spike: a
BigQuery build is held to DuckDB's within 1e-9 on float columns. It also left open whether
that tolerance would be the lasting rule.

What came of it. Two BigQuery builds of the same rows differ from each other, in 7 of 17
rows of `int_fantasy__category_scales` and 5,718 of 20,183 of
`int_fantasy__reported_matchup_margins` (#130). Four unit tests that assert the last digit
fail on BigQuery (#138). Float noise has already changed a column that is not a float:
`fct_lineup_decisions` named a different missed start in 4 rows until its order was
rounded (#137, ADR 0104). The 35 ordered aggregates sit in 13 models (spec 0139, C1).

Measured for this decision (spec 0139):

- DuckDB's ordered `sum` and `avg` are a plain left-to-right fold. On the real season,
  138 of 138 groups equal `s += x` in key order, and `s / n`. A correctly rounded sum
  (`math.fsum`) matches only 31 (C2).
- DuckDB's ordered `corr` is a one-pass fold: Welford's updates for the co-moment and the
  two variances, then `covar_pop / (stddev_pop(x) * stddev_pop(y))`. A port of it equals
  DuckDB in 96 of 96 real groups, and gives both unit tests' expected values (C3).
- On BigQuery, a JavaScript function over `array_agg(x order by key)` gives DuckDB's
  digits exactly in all six cases tried, the reversed orders included. The query billed
  0 bytes (C4). At the scale of the largest caller, 200,000 groups of 12 terms, it took
  3.8 s against 0.6 s for a native `sum`, and billed 0 bytes (C5).

## Decision drivers

- A BigQuery build repeats itself, and equals DuckDB's, to the last digit (ADR 0046's
  guarantee, on both warehouses).
- DuckDB's SQL and numbers do not change.
- One macro per aggregate, so no model chooses a form for itself.
- Nothing billed, and no service or runtime to own (as for ADR 0103).

## Considered options

1. **A JavaScript fold over an ordered array.** On BigQuery, `fo_sum_in_order(x, k)`
   becomes `sum_in_order(array_agg(x ignore nulls order by k))`, a dbt function resource
   in JavaScript that adds the values in order. `fo_avg_in_order` is that sum over the
   count, and `fo_corr_in_order` calls `corr_in_order` on an ordered array of `(y, x)`
   structs, porting DuckDB's algorithm. DuckDB's forms do not change.
2. **Exact decimals** (ADR 0053, option 5): sum `cast(x as numeric)` on both warehouses.
   A decimal sum is exact, so it is the same in any order.
3. **Keep the tolerance** as the lasting rule, and make each discrete decision taken on
   a float robust to it by rounding, as ADR 0104 does for the lineup order.
4. **A Python UDF** doing the fold, as the solver does (ADR 0103).

## Decision

Chosen by the owner on 2026-10-29, going through the spec's decisions, as recommended:
**option 1**.

It is the only option that gives ADR 0046's guarantee on BigQuery and leaves DuckDB as it
is. Option 2 changes DuckDB's numbers too: at scale 9, which is BigQuery's `NUMERIC`,
every one of the 138 sums of C2 moves. At scale 18, DuckDB's cast from a double is not the
exact rounding of its value (1,420 of 7,921 values), so the two engines would round the
same input differently (C6). And `corr` has no decimal form. Option 3 is what the project
has now. Rounding narrows the noise but does not remove it: two values either side of a
rounding boundary still round apart. And it holds only where someone has thought to
round. Option 4 needs a container image built and billed (ADR 0103, C20 there) for
arithmetic JavaScript does in the query itself.

## Consequences

- Good: ADR 0046's guarantee holds on BigQuery: the same rows give the same digits, on
  every build, on both warehouses. ADR 0116 then holds the comparison of the two builds
  to exact equality.
- Good: the four unit tests that assert last digits pass on both warehouses, unchanged.
- Good: DuckDB compiles to the same SQL as before, so the DuckDB warehouse does not move.
- Bad / accepted cost: the two JavaScript functions copy DuckDB 1.5.5's algorithms. A
  DuckDB upgrade that changes them would break the agreement, and pytest is the tripwire
  (spec 0139, R3.3): it compares DuckDB's ordered aggregates with the same fold on random
  inputs.
- Bad / accepted cost: a BigQuery query that folds is slower than a native `sum`, by
  about 3 s per 200,000 groups (C5). It is not billed: BigQuery charges for bytes read,
  and an ordered `array_agg` reads the same bytes.
- Bad / accepted cost: two more function resources, built on BigQuery only and disabled
  on DuckDB, like `solve_lineup_period`.
- Follow-ups: none. ADR 0104's rounding of the lineup order stays: it decides between
  options of equal value, which is a tie-break, not a guard against noise.
