# 0005. A drop's impact is the rest of the season

- Status: proposed
- Date: 2026-10-03
- Spec: [0011-player-value](../specs/0011-player-value/design.md) · Issue: #11

## Context

`fct_transaction_impact` reports "what the dropped player did afterwards". The original
plan bounded that by the next transaction on the same player.

## Decision drivers

- The question a manager asks of a drop is "what did I give up?".
- Windows should be comparable in meaning across drops.
- No arbitrary constants.

## Considered options

1. **Rest of season, all MLB production**, whoever rostered him afterwards.
2. **Until the next add by anyone** — production while a free agent only.
3. **A fixed window** — the next 30 days.

## Decision

Chosen: **rest of season**. The window runs from the day after the drop to the last
scoring date, and sums his MLB production on the side his group is credited for. The
fact also records `next_added_at` and `next_added_by_team_id`, so option 2's question
can still be answered from the same row.

Option 2 makes a drop look harmless precisely when it was worst: the player someone else
picks up the next morning has a one-day window. Option 3's 30 is arbitrary.

## Consequences

- Good: "what I gave up" is measured in full.
- Bad / accepted cost: windows differ in length — an April drop has five months to look
  bad, a September drop two weeks. `played_days` sits beside the value so the two can be
  told apart.
- Bad / accepted cost: it is MLB production, not fantasy production: nobody may have
  started him. That asymmetry with adds (credited production while started) is deliberate
  and stated in the model header.
- Follow-ups: none.
