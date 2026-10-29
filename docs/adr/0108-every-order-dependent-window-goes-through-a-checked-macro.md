# 0108. Every order-dependent window goes through a checked macro, held by a text rule

- Status: accepted
- Date: 2026-10-28
- Spec: [0141-total-tie-breaks](../specs/0141-total-tie-breaks/design.md) · Issue: #141

## Context

ADR 0107 puts the tie check inside `fo_keep_first` and `fo_row_number`. It holds only where
those macros are used. Today the project ranks in 23 places: eight callers of
`fo_latest_by_entity`, one raw `qualify` in `fo_espn_latest_paths`, twelve hand-written
`row_number()`s in seven models, and two `lag`s (spec 0141, C1). Issue #141 names the
keep-one-row steps. Some hand-written rankings are not keep-one-row, but go wrong on a tie
in the same way:

- the replacement pools keep the first `team_count` rows;
- `earlier_pitching_days` numbers every row.

Two rankings cannot go wrong on a tie: the median positions in
`int_fantasy__reported_matchup_margins` read only the values at the middle places, and
tied rows hold equal values there.

The project already holds two SQL rules with a text test in pytest: JSON access (#79), and
ordered float aggregates with their `order-exempt:` comment (ADR 0046).

## Decision drivers

- Nothing order-dependent is written outside the check without someone saying why.
- One mechanism for keeping, cutting and numbering.
- Fails in seconds, with a file and line, the way the other SQL rules do.

## Considered options

1. **Every order-dependent window**: `row_number`, `lag`, `lead`, `first_value`,
   `last_value`, `nth_value` and `ntile`, outside the two macros' bodies. Each must go
   through a macro or carry a `tie-exempt:` comment with a reason. Held by a text test.
2. **Keep-one-row steps only** (the issue's title): `qualify row_number() … = 1` and its
   `where rank = 1` forms. The cut-at-*n* pools, the numbering and `lag` stay as they are.
3. **No rule**: convert today's call sites and rely on review.

## Decision

Chosen by the owner on 2026-10-28, as recommended: **option 1**.

A tie in a cut at `team_count`, or in a numbering, changes the result just as a tie at
place 1 does, so option 2 leaves the same bug open in three places. Option 3 holds only
until the next model is written. `rank`, `dense_rank`, `percent_rank` and `cume_dist` are
not in the list: they give tied rows equal values, so they cannot pick between them.
Aggregates are left to ADR 0046.

The test reads SQL as `test_dbt_ordered_aggregate_rule.py` does, with the same limits:
comments and strings blanked, the marker alone exempting nothing, and Jinja not rendered.

## Consequences

- Good: rule 5 becomes "go through the macro", and a gate holds it.
- Good: an exemption is in the file, beside the call, with its reason.
- Bad / accepted cost: `lag` over a window that `fo_row_number` checks still needs an
  exemption that says so. The text test cannot see that two windows are the same.
- Bad / accepted cost: a text rule can be dodged by a macro that builds the call from
  pieces. That is accepted, as for the two existing rules.
- Follow-ups: none.
