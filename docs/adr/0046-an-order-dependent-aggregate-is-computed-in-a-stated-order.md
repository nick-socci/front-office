# 0046. A floating-point aggregate that depends on row order is computed in a stated order

- Status: proposed
- Date: 2026-10-10
- Spec: [0115-reproducible-group-correlation](../specs/0115-reproducible-group-correlation/design.md) · Issue: #115

## Context

The last digit of a floating-point sum depends on the order of its terms, and the
physical order of a table's rows changes from build to build. The project compares
warehouses exactly (`compare_warehouses.py`, the tenant isolation gate) and the README
says builds are reproducible to the last digit.

The same fault has now appeared three times: `stddev_pop` (#55), the `avg` that replaced
it (#58), and `corr` in `rec_fantasy__category_wins_by_group` (#94, found in #115). The
second was fixed by the owner's decision of 2026-10-04, recorded as R4.13 of spec 0028:
sums and averages of non-integer values are computed in a fixed order. That rule lives
in one spec's amendment, names sums and averages only, and did not stop the third.

Measured on the real 2026 season (2026-10-10, DuckDB 1.5.5): the view's 580 pairs in 12
row orders gave 12 different correlations, differing by up to 8e-16; `corr(y, x order by
platform_player_id, fantasy_team_id)` gave one.

## Decision drivers

- Exact comparison stays the verdict, with no relation excused.
- One rule for every aggregate, so the next one is not a new decision.
- No change to what a column means.

## Considered options

1. **State the order inside the aggregate**: `corr(y, x order by <the grain's key>)`,
   as R4.13 already does for sums.
2. **Compute the statistic from ordered sums by its formula.**
3. **Round the column** to a fixed number of decimals.
4. **Excuse the relation**: compare it after rounding, and say so in the README.

## Decision

Recommended: **option 1**, as a general rule. An aggregate over floating-point values
whose result depends on the order of its rows (`sum`, `avg`, `corr`, `stddev`, `var`,
`covar`, `regr_*` and the like) carries an `order by` on columns that are unique within
the group, normally the key of the grain it reads. Exempt: an aggregate that is exact
whatever the order, which is to say `min`, `max`, `count`, `median`, and a `sum` or `avg`
whose inputs are all integer-valued and whose magnitudes sum to less than 2^53 (about
9e15), the range in which a `double` holds every integer. Integer-valued alone is not
enough: `avg` of 1e16, 1 and -1e16 is 0 or 0.33 by row order. An exemption is claimed in
a comment at the aggregate, with the bound.

Option 2 gives a stable value too, but a different one (it disagreed with `corr` in the
16th digit on all three groups), in five sums where one call will do, and by a formula
that loses precision when a group's values are close together. Option 3 does not make
the value reproducible, only makes a difference rare: two results either side of a
rounding boundary still round apart, and it changes a column to hide a property of how
it was computed. Option 4 leaves the exact comparison failing on every rebuild and the
README's claim false.

## Consequences

- Good: the same inputs give the same digits on every build, in every relation.
- Good: the rule covers aggregates R4.13 did not name.
- Bad / accepted cost: an ordered aggregate sorts its input. On 580 rows that is
  nothing; on a large fact it would be weighed then.
- Bad / accepted cost: `order by` inside `sum` or `corr` is DuckDB syntax. BigQuery has
  no equivalent for these aggregates, so the port needs another way to fix the order
  (a pre-sorted array, or exact decimal arithmetic). That was already true of R4.13.
- Bad / accepted cost: nothing in CI enforces the rule. A breach is caught when two real
  builds are compared, as #115 was.
- Follow-ups: none now. The two remaining `avg()` calls (`int_fantasy__category_scales`,
  `int_fantasy__reported_matchup_margins`) are over integer-valued inputs no larger than
  369 on 2026, thousands of rows at most, and exempt; if either input ever takes a
  non-integer value, it gains an order. They carry no comment claiming the exemption
  today, and #115 changes no other model: the comments are left for the owner to ask
  for.
