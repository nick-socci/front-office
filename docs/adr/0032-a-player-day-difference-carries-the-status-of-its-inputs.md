# 0032. A player-day difference carries the status of its inputs

- Status: proposed
- Date: 2026-10-09
- Spec: [0081-player-day-reconciliation-input-status](../specs/0081-player-day-reconciliation-input-status/design.md) · Issue: #81

## Context

`rec_espn__player_day_differences` reports every started player-day and stat where our
number and ESPN's line differ. A player-day with no loaded boxscore is ours as zero, so
it differs from any line ESPN has. On the real 2026 season there are none: 22 rows, all
on verified inputs. On the CI fixtures after #93 there are 467 rows and all of them are
this case; in season, each day's late boxscores would be.

The matchup-level table already separates a side it could not check (`unverified`) from
one it checked. The player-day table is different in kind: it holds only differences,
not every comparison.

## Decision drivers

- A row should not claim a difference its inputs cannot support.
- Where nothing could be compared, the table should show that, not look clean.
- The 22 real rows are unchanged.
- The grain and the meaning of a row are the owner's to set.

## Considered options

1. **Keep the rows and label them**: two columns, `input_status` and `status`
   (`difference` or `unverified`).
2. **Leave unverified player-days out.**
3. **A census**: one row per started player-day and stat, with `match`, `difference` or
   `unverified`.
4. **Leave it**, and read the table only on the real season.

## Decision

Chosen by the owner on 2026-10-09, going through the spec's decisions: **option 1**,
with both columns, `input_status` passed through and `status` derived from it, and a
`verified_off` day for which ESPN has a line counted as a difference.

A row's `status` is `difference` when its player-day is `played` or `verified_off`, and
`unverified` when it is `missing_boxscore` or `unresolved_player`. A `verified_off` day
for which ESPN has a non-zero line is a `difference`: every game that date is loaded and
he is in none, and ESPN says he played. It did not happen in 2026 (0 of 17,545), and if
it does it is exactly what the table is for: a wrong player match, or a game filed under
another date. Rows are still kept only where the numbers differ.

Option 2 is the smallest change and keeps the table purely "differences", but in CI the
table would be empty while nothing in it had been compared, and in season it would hide which lines are
waiting on a boxscore. Option 3 changes the grain and grows the table from 22 rows to
every started player-day times its stats, to record agreement nobody reads. Option 4 is
the issue.

## Consequences

- Good: a difference can be told from an unchecked comparison in the row itself, and a
  test can judge only the first.
- Good: no existing column, row or consumer changes on the real season.
- Bad / accepted cost: the table no longer holds only differences; a reader must filter
  on `status`. Its name is kept.
- Bad / accepted cost: `status` is derivable from `input_status`. Both are carried so
  the rule lives in the model, not in each reader.
- Bad / accepted cost: in CI the table still has 467 rows, now labelled, and its test
  judges none of them.
- Bad / accepted cost: a label needs a row. An unverified player-day whose numbers
  happen to agree has none, so an empty table still does not prove agreement; the
  completeness tests do that.
- Follow-ups: the register of known differences has no league or season in its key; the
  owner decided on 2026-10-09 that the spec's test fails closed on that and that keying
  the register is its own work (#99).
