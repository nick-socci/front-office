# 0048. An example is held on the fixtures to a stated number of rows, and to stated counts of rows with a value

- Status: proposed
- Date: 2026-10-10
- Spec: [0117-examples-return-stated-rows](../specs/0117-examples-return-stated-rows/design.md) · Issue: #117
- Amends: [0045](0045-an-example-query-is-an-exposure-and-the-dashboard-reads-every-mart.md)

## Context

ADR 0045 made each example query an exposure and had the gates run it on the fixture
warehouse. It accepted one cost: "on the fixtures an example is only proved to run, not
to return rows". PR #116's review found what that costs: `roster_day_query.sql` returns
no rows in CI, so its selection is untested (#117).

Measured on the fixtures, 2026-10-10, with the roster example asked for team 11 on
2026-04-29 (spec 0117, *What was measured*): it returns 18 rows, 2 with a batting line
and 1 with a pitching line. With the team filter removed it returns 216 rows; with the
date filter removed, 54. With batting joined to the wrong day it still returns 18, and
the batting lines fall to 1. With the league filter removed nothing changes: the fixture
holds one league. Of the 36 team-days in the fixtures, 35 return 18 rows.

## Decision drivers

- The check should fail for the breaks that were measured, not only for the one in the
  issue's title.
- What is stored should be small and mean something to a reviewer.
- The fixtures are rebuilt often; the check should not make a rebuild expensive.

## Considered options

1. **Stated counts**: for each example, the rows it returns on the fixtures, and
   optionally how many of them have a value in a named column. The gate fails on any
   difference, and on an example with nothing stated.
2. **At least one row** from every example.
3. **A stored copy of each example's output**, compared row for row.

## Decision

Chosen: **option 1** (owner, 2026-10-10, PR #124).

The numbers live in `docs/examples/expected_on_fixtures.yml`, beside the examples. A
stated number of rows is never zero. The roster example states its rows and the rows
with a value in `at_bats` and in `innings_pitched`; the three mart examples state rows.

Option 2 catches an example that returns nothing and none of the measured breaks, which
return too many rows or the right number of wrong ones. Option 3 catches most, and is
rewritten at every fixture rebuild into a diff nobody can review.

## Consequences

- Good: a filter that stops filtering, a join that multiplies rows, and stats read from
  the wrong day each fail the gates.
- Good: an example cannot be added without saying what it returns.
- Bad / accepted cost: the numbers describe the fixtures. A fixture rebuild that changes
  what an example returns turns the gates red until the number is updated by hand.
- Bad / accepted cost: the league filter of the roster example is not held, because the
  fixture warehouse holds one league.
- Bad / accepted cost: counts do not tell one valid team from another by design. Under
  the parameters chosen they often do (team 3 returns 1 and 0 against 2 and 1), which is
  a property of the fixtures and not a guarantee.
- Bad / accepted cost: a count of rows with a value holds that a stat line is present,
  not the numbers in it. Stated column totals would; the owner left them out, since the
  values are tested where they are produced (spec 0117, *Settled by the owner*).
- Follow-ups: running the examples on the two-league fixture would hold the league
  filter; no issue is opened for it (owner, 2026-10-10).
