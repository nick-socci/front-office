# 0056. A covered league-season says whether it has a transaction log

- Status: accepted
- Date: 2026-10-11
- Spec: [0083-past-season-rosters](../specs/0083-past-season-rosters/design.md) · Issue: #83
- Amends: [0026](0026-a-league-season-is-covered-when-it-has-rosters.md)

## Context

ADR 0026 made coverage one boolean, `has_rosters`, and accepted that as a cost. #83
lands rosters for seven past seasons. ESPN serves the transaction log of the current
season only: the same request returns 404 for 2023 and 2025 and 200 for 2026 (spec
0083, C12). A covered past season therefore has rosters, values and lineup decisions,
and no row in `fct_transaction_impact`, which today holds 737 rows, all 2026 (C19).

## Decision drivers

- An empty result must not read as "nobody made a move".
- Coverage follows from what is loaded, not from a list (ADR 0026).
- The seasons should be covered for everything that does not need the log.
- No invented transactions.

## Considered options

1. **A second boolean, `has_transaction_log`, on `int_fantasy__league_seasons`**, read
   from the loaded log responses, and a test holding the transaction mart to it.
2. **Change nothing**; say it in the mart's description.
3. **Rebuild moves from day-to-day roster differences.**
4. **Do not cover a league-season without a log.**

## Decision

Chosen by the owner on 2026-10-11, going through the spec's decisions: **option 1**.

`has_transaction_log` is true when a transaction-log response is loaded for the
league-season, whether or not it holds a transaction.
`fct_transaction_impact` may hold rows only for such league-seasons, and its description
says that a league-season without the flag has no log landed.

Option 2 leaves the difference in prose. Option 3 has to decide what a move was, who
made it and when, from two rosters a day apart (ADR 0004 needed the message type for
that). Option 4 gives up seven seasons of values for a fact they do not use.

## Consequences

- Good: a query over several seasons can leave out the ones with no log, by a join.
- Good: a landed log with no transaction in it is told apart from no log.
- Bad / accepted cost: one more staging model, of one row per league-season.
- Bad / accepted cost: the audit still reports the missing log for a past season.
- Follow-ups: none; revisit if ESPN's log is found behind another endpoint.
