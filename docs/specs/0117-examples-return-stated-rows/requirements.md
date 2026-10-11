# An example returns the rows it should on the fixtures — requirements

Issue: #117 · Tier: M · Status: draft

## Problem

`scripts/check_examples.py` runs every file in `docs/examples/` on the fixture warehouse
and fails on an error (spec 0013, R3.4). A query that returns nothing is not an error, and
`roster_day_query.sql` returns nothing there: it asks for league `73677`, team 6, on
2026-07-02, and the fixtures hold league `111111` on 2026-04-24, 04-29 and 04-30. So the
example the README runs first is proved to parse and nothing more (PR #116 review, round
1, F3; ADR 0045 lists it as an accepted cost).

Measured on the fixture warehouse, 2026-10-10 (design, *What was measured*): with the
team filter removed the example returns 216 rows in place of 18, and with the date filter
removed, 54. Today both would pass.

## Goals

- An example that returns the wrong number of rows on the fixtures fails the gates.
- The roster example returns rows in CI, from a team and a day the fixtures hold.
- The roster example's second half is held as far as a count can hold it: the players
  who played that day get a batting or a pitching line, and the ones who did not get
  none. Whether the numbers in a line are right is not held (see *No-gos*).
- The example files stay what they are for: a file a reader pipes into DuckDB as it is.

## No-gos

- No change to `fixtures/` or to `scripts/make_fixtures.py`. The design needs no new
  fixture day and no second league, so the fixture counts recorded in the README and in
  spec 0013 do not move.
- No change to what any example selects on the real season: `roster_day_query.sql` keeps
  league `73677`, team 6 and 2026-07-02 as what it returns when run as committed.
- No check in CI of what the committed default parameters return. CI holds no real
  league, so nothing there can run league `73677`, team 6 on 2026-07-02 against data (see
  *Rabbit holes*). The one check CI does make on the defaults is R2.1's: a test that reads
  the file's text and holds the three values to the committed ones.
- No comparison of an example's rows with a stored copy of its output.
- No check of the values in a stat line. The gate counts the rows that have a batting
  line and the rows that have a pitching line; a line with wrong numbers in it passes.
  Stated column totals would hold them; the owner left them out on 2026-10-10 (design,
  *Settled by the owner*).
- No parameters for the three mart examples: they select no team and no day.

## Rabbit holes

- **Catching "another valid value".** The issue's consequence reads: changing the
  `team_id`, `league_id` or date to another valid value still passes. Measured: on the
  fixtures 35 of the 36 team-days return 18 rows and one returns 17, so no count tells one
  team from another, and once the gate supplies its own parameters the committed defaults
  are not what CI runs at all. → The gate holds the selection *mechanism* (the filters
  filter, the joins do not multiply rows). The committed defaults are checked on the real
  season when the file changes, as they were in #13: 18 rows, compared row for row.
- **The league filter.** The main fixture holds one league, so removing the join on
  `league_id` changes nothing there (measured: the same 18 rows). → Accepted and written
  down, not solved by adding a league to the main fixture. `fixtures/landing_multi` holds
  two leagues and is built only inside `check_tenant_isolation.py`; running examples on
  it is a separate piece of work.
- **A general parameter language.** → Parameters are DuckDB variables with a default,
  only in the one file that has parameters.

## Requirements

### R1. Every example states what it returns on the fixtures

So that an example returning nothing, or too much, fails the gates.

- R1.1 THE SYSTEM SHALL hold, for each file in `docs/examples/`, the number of rows that
  file returns on the fixture warehouse, in one committed file beside the examples.
- R1.2 WHEN the gates run, THE SYSTEM SHALL execute every example on the fixture
  warehouse and fail if the number of rows returned differs from the number stated,
  printing the file, the number stated and the number returned.
- R1.3 IF an example file has no stated expectation, or an expectation names no example
  file, THEN THE SYSTEM SHALL fail the gates, naming it.
- R1.4 THE SYSTEM SHALL refuse a stated number of rows of zero: an example that is
  expected to return nothing is held to nothing.
- R1.5 THE SYSTEM SHALL keep failing on a query error, as R3.4 of spec 0013 requires.

### R2. The roster example takes its parameters from variables

So that the gate can ask it about a team and a day the fixtures hold, and a reader can
ask about their own.

- R2.1 `roster_day_query.sql` SHALL read `league_id`, `team_id` and `on_date` from DuckDB
  variables of those names, and WHEN a variable is not set THE SYSTEM SHALL use the
  committed value: `'73677'`, `6` and `date '2026-07-02'`.
- R2.2 WHEN the file is run as committed, with no variable set, on the real 2026 season,
  THE SYSTEM SHALL return the same rows as before this change, compared row for row.
- R2.3 WHEN the gates run the roster example, THE SYSTEM SHALL set the variables stated
  for it, and SHALL clear them before the next example runs.
- R2.4 IF an expectation states a variable that its example file does not read, THEN THE
  SYSTEM SHALL fail the gates, naming the variable.
- R2.5 The file's header SHALL say how a reader sets the variables.

### R3. The presence of the roster example's stat lines is held

So that the join from the roster to that day's MLB games is tested, not only "who was on
the roster". Measured: reading batting from the wrong day leaves the row count at 18 and
changes how many rows have a batting line. This holds that a line is present, not what
is in it.

- R3.1 An expectation MAY state, for named output columns, how many returned rows have a
  value in that column; WHEN it does, THE SYSTEM SHALL fail the gates if the count
  differs, printing the column, the number stated and the number found.
- R3.2 IF an expectation names a column the example does not return, THEN THE SYSTEM
  SHALL fail the gates, naming the column.
- R3.3 The roster example's expectation SHALL state the count for `at_bats` and for
  `innings_pitched`, and both SHALL be greater than zero: the team-day chosen has a
  batter and a pitcher who played.

### R4. The record

- R4.1 `AGENTS.md`, *Project shape*, SHALL say that the gate holds each example to a
  stated number of rows, and where the numbers are kept.
- R4.2 The numbers SHALL be changed only with the fixtures or the example they describe:
  the file that holds them SHALL say so, and say how to read the new numbers.

## Expected values

Read-only on 2026-10-10: the fixture warehouse built by `.agentic/gates` at `b4d16fd`,
and `data/warehouse.duckdb`.

| Check | Expected | How to verify |
|---|---|---|
| `lineup_decisions_query.sql`, fixtures | 12 rows | the gate |
| `matchup_results_query.sql`, fixtures | 4 rows | the gate |
| `player_value_query.sql`, fixtures | 15 rows | the gate |
| `roster_day_query.sql`, fixtures, league `111111`, team 11, 2026-04-29 | 18 rows; `at_bats` in 2; `innings_pitched` in 1 | the gate |
| `roster_day_query.sql`, fixtures, no variable set | 0 rows (the committed league is not in the fixtures) | by hand; not a gate |
| `roster_day_query.sql`, real season, no variable set | 18 rows, equal row for row to the file at `b4d16fd`; `at_bats` in 6, `innings_pitched` in 1 | by hand, before against after |
| Team filter removed, fixtures, team 11 on 2026-04-29 | the gate fails: 216 rows | once by hand, on a scratch copy of the file |
| Date filter removed, same | the gate fails: 54 rows | once by hand, same |
| Batting read from five days earlier, same | the gate fails on `at_bats` (1, not 2); rows still 18 | once by hand, same |
| League filter removed, same | the gate passes: 18 rows, 2 and 1. The accepted gap | once by hand, same |
| The three mart examples, real season | 12, 12 and 15 rows, unchanged: their files are not edited | by hand |
| Fixture counts in the README and spec 0013 | unchanged | `git diff --stat` shows nothing under `fixtures/` |
