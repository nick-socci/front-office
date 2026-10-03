# 0004. A transaction's acting team depends on its message type

- Status: proposed
- Date: 2026-10-03
- Spec: [0011-player-value](../specs/0011-player-value/design.md) · Issue: #11

## Context

`stg_espn__transactions` exposes ESPN's message fields `to` and `from` as `to_team_id`
and `from_team_id`. Checked against the roster timeline for 2026, those names are wrong
for most rows:

| Message type | Rows | Acting team is in | Evidence |
|---|---|---|---|
| 178 FA ADDED, 180 WAIVER ADDED | 374 | `to` | 336 on that team the day after, 0 the day before |
| 179, 181 DROPPED | 252 | `to` | 241 on that team the day before, 0 the day after |
| 239 DROPPED | 111 | `for` (not selected today) | 89 of the 89 rostered the day before were on it; 0 the day after |

For type 239, `from` holds values 0–5 and 13–17 — lineup slot ids (16 is the bench, 17
the injured list), not teams, which run 1–12. `to` is −1.

What an ESPN field means is the person's decision (AGENTS.md).

## Decision drivers

- Staging names must not assert a meaning the data does not have.
- The mapping is a platform rule, and platform rules live in seeds here
  (`int_fantasy__stat_components`).
- An unknown or unhandled type must stop the build, not default.

## Considered options

1. **Honest staging names + a seeded rule + an intermediate interface.** Staging exposes
   `message_to`, `message_from`, `message_for`; `espn_activity_types` gains
   `movement`, `method`, `team_field`; `int_fantasy__transactions` applies it.
2. **Fix it in staging.** A `case` on message type inside `stg_espn__transactions`
   producing `fantasy_team_id`.
3. **Infer the team from the roster timeline.** Ignore the message fields; the acting
   team is whoever rostered the player the day before or after.

## Decision

Chosen: **option 1**. Staging flattens and names; the intermediate layer says what it
means; the rule is a seed row, so a new message type is a data change with a failing
`not_null` test until someone decides it.

Option 2 hides a platform rule in SQL and makes staging interpret. Option 3 cannot place
a same-day add-and-drop or a pre-season move (49 transactions predate the first roster
day), and would make the transaction log depend on the snapshots it is supposed to
explain.

## Consequences

- Good: every transaction has a non-null acting team, tested against the teams
  interface; type 244 (trades, none in 2026) fails loudly instead of being guessed.
- Bad / accepted cost: a breaking rename of two staging columns. Nothing outside staging
  reads them today.
- Follow-ups: trades need their own decision when one occurs. League and season identity
  on transactions is #28.
