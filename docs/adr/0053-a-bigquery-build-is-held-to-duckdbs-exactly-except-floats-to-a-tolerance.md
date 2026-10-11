# 0053. A BigQuery build is held to DuckDB's exactly, except floating-point columns, which are held to a tolerance

- Status: proposed
- Date: 2026-10-11
- Spec: [0130-bigquery-spike](../specs/0130-bigquery-spike/design.md) · Issue: #130

## Context

Two DuckDB builds of this project are compared exactly, digit for digit, and that is
enforced: ADR 0046 gives every floating-point aggregate an `order by` inside its
parentheses, because the last digit of a float sum depends on the order of its rows.

BigQuery refuses that syntax for `sum`, `avg` and `corr` (dry run, 2026-10-11), and its
float sum depends on order all the same: summing 0.3, 0.2, 0.1 gave 0.6 and summing
0.1, 0.2, 0.3 gave 0.6000000000000001. So on BigQuery the order of a float aggregate
cannot be stated, and a BigQuery build may not equal DuckDB's, or its own previous
build, in the last digits.

Of the slice's 29 relations, 7 have floating-point columns (21 columns), and each has a
declared unique key. Everything else is integers, text, dates, booleans and timestamps:
on the whole warehouse 54 of 785 columns are `DOUBLE`. The components the project
stores (rule 4: at-bats and hits, never AVG) are integers.

## Decision drivers

- A wrong number must not hide behind a tolerance.
- The check must be one that can pass.
- What the tolerance costs should be measured, not assumed.
- DuckDB's exactness is kept.

## Considered options

1. **Everything exact but floats; floats within a relative 1e-9**, joined on the key,
   with the count of exactly-equal values and the largest difference reported.
2. **Everything exact**, floats included.
3. **Floats rounded to N decimals, then everything exact.**
4. **Row counts and keys only.**
5. **Compute rates in exact decimals** (`NUMERIC`), so that both warehouses agree
   exactly.

## Decision

Recommended, for the owner to decide: **option 1**.

Non-float columns are compared as multisets, both ways. A float column is compared pair
by pair on the relation's unique key: equal within a relative difference of 1e-9, or an
absolute difference of 1e-12 where both values are below 1e-3 in magnitude; a null on
one side only is a difference. A double carries about sixteen significant digits, so
1e-9 allows the last seven to differ and nothing a person would read. The comparison
reports how far inside that the real differences are.

Option 2 cannot pass, for the reason in the context. Option 3 fails on values that
straddle a rounding boundary, however close they are. Option 4 would pass a wrong
number. Option 5 may be right, but it changes what the models compute on DuckDB too, and
`sqrt`, `corr` and `stddev` have no exact decimal form; it is a decision for after the
differences have been seen.

## Consequences

- Good: integers, text and dates, which is 93% of the columns, are held exactly.
- Good: the first real measurement of how far two engines differ on these numbers.
- Bad / accepted cost: ADR 0046's guarantee, that a build reproduces itself to the last
  digit, holds on DuckDB only. Whether BigQuery reproduces itself is measured (spec
  0130, R5.5) and not required.
- Bad / accepted cost: a category decided by a float comparison within 1e-9 of a tie
  could go the other way on BigQuery. It would show as a difference in a text column
  (`our_result`), which is held exactly, and be explained there.
- Follow-ups: with the measured differences in hand, decide whether the tolerance is
  the lasting rule or the rates move to exact decimals.
