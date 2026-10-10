# 0038. Lineup eligibility is ESPN's as fetched

- Status: accepted
- Date: 2026-10-09
- Spec: [0012-lineup-decisions](../specs/0012-lineup-decisions/design.md) · Issue: #12

## Context

A "could have started" analysis needs to know which slots a player was eligible for on
the day. ESPN returns a player's eligibility as of the fetch, whatever period is
requested (#52): all 180 periods of 2026 were fetched on 2026-09-26 and no player's
eligible slots change across them. Eligibility only grows in a season, so the slot a
player was started in is always inside it (0 exceptions in 38,665 started rows), but a
move that was not legal in April can look legal. The owner flagged this on #12 and left
what to do about it undecided.

Measured with the prototype: the season gap is 1,468 margins with eligibility as
fetched, and 1,358 if a player may only take slots he had already occupied by that
date (plus `UTIL` and `P`). In season, a settled roster capture is taken up to a week
after its period (ADR 0018).

## Decision drivers

- No invented rule standing in for ESPN's.
- The reader must be able to tell how far the eligibility is from the day.
- The same models must be right for a season captured daily.

## Considered options

1. **ESPN's eligibility as fetched**, with the fetch time on every row.
2. **Only slots already occupied** by that date, plus the generic slots.
3. **Rebuild eligibility** from games played by position and ESPN's thresholds.
4. **Do not build the marts for a backfilled season.**

## Decision

Recommended, for the owner to decide: **option 1**.

`int_fantasy__lineup_options` reads `stg_espn__roster_entry_slots` as it is and carries
its `fetched_at` as `eligibility_fetched_at`; `fct_lineup_decisions` carries it per
team-day. The models' headers and descriptions say that for 2026 it is the eligibility
of 2026-09-26.

Option 2 understates by a rule nobody plays by: a player who gains a position counts
there only after his manager first uses it. Option 3 is ESPN's rulebook to keep per
season, for a bound measured at about 8%. Option 4 gives up 2026, the only season
there is.

## Consequences

- Good: no rule to maintain; a daily-captured season needs no change.
- Bad / accepted cost: 2026's gap overstates what was legal on the day, by at most
  about 8% on the measured bound.
- Bad / accepted cost: even in season, eligibility is as of the settled capture, up to
  a week after the day.
- Follow-ups: if a same-day roster capture is ever kept beside the settled one, the
  options model should read it; that is a capture-policy question (ADR 0016, ADR 0018).
