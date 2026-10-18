# 0063. A rate ESPN gives no components for is compared with ESPN's rate directly

- Status: accepted, amended by [0076](0076-a-rate-part-espn-does-not-report-is-recovered-from-its-rate.md)
- Date: 2026-10-13
- Spec: [0083-past-season-rosters](../specs/0083-past-season-rosters/design.md) · Issue: #83

## Context

`rec_espn__matchup_stat_differences` checks a rate in two steps. First the formula: our
rule applied to ESPN's own component scores must give ESPN's rate, or the status is
`formula_mismatch`, "the formula is wrong, whatever our inputs say". Then the value:
ours against ESPN's.

For 2018 ESPN's `scoreByStat` carries 18 stats where later seasons carry 22 to 24.
At-bats, hits allowed, walks allowed and earned runs are absent (stat ids 0, 37, 39, 45),
so AVG, WHIP and ERA have no components to apply the formula to. The formula value is
null and every 2018 rate is `formula_mismatch`: 858 rows, of which 823 agree with ESPN's
rate within the tolerance of 1e-6. Measured on the eight-season warehouse, 2026-10-13.

## Decision drivers

- A status must say what was found. "The formula is wrong" was not found; it could not
  be looked for.
- A value that can be compared should be.
- What was not checked must stay visible.

## Considered options

1. **Compare the rate directly when ESPN gives no components**, and record that the
   formula was not checked.
2. **A status of its own** (`formula_unchecked`) for every such rate, whatever its value.
3. **Leave it** as `formula_mismatch` until ESPN's components for such a season are found
   elsewhere.

## Decision

Chosen by the owner on 2026-10-13: **option 1**.

When the formula value is null because a component is missing from ESPN's side, the
formula check is skipped and the rate goes on to the value statuses (`match`,
`explained_by_component`, `unexplained`) like any other. A column, `formula_checked`,
says whether the check ran. `formula_mismatch` keeps its meaning: the check ran and
failed.

## Consequences

- Good: 823 of 2018's 858 rates become `match`; the other 35 are judged on their values,
  which follow count differences on the same sides.
- Good: a season that one day has components is checked as before.
- Bad / accepted cost: for such a season an error in our rate formula that happened to
  agree with ESPN's values could not be seen. The formula is checked on every other
  season.
- Bad / accepted cost: `explained_by_component` needs ESPN's components too, so a rate of
  such a season that differs can only be `unexplained`.
