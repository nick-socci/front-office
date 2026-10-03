# 0002. Value is measured per played day

- Status: accepted
- Date: 2026-10-03
- Spec: [0011-player-value](../specs/0011-player-value/design.md) · Issue: #11

## Context

A count category (hits, strikeouts, innings) needs a "per what" before a player can be
compared with replacement. Rates (AVG, ERA, WHIP, K/9) cannot be subtracted from each
other meaningfully: a .300 hitter over 4 at-bats is not worth what one over 400 is.

## Decision drivers

- Innings pitched is a scored category, so volume must be able to have value.
- The 2026-09-27 review flagged availability bias: off days must not count against a
  player or for a replacement.
- A player's value should not mostly measure his manager's lineup timing.
- Components, never rates (AGENTS.md rule 4).

## Considered options

1. **Per played day** — a game day against a replacement's game day.
2. **Per opportunity** — per plate appearance for hitters, per out for pitchers.
3. **Per roster slot-day** — every started day, played or not, against the replacement's
   calendar-day rate.

## Decision

Chosen: **per played day** for counts — `N − replacement_per_played_day × played_days` —
and **marginal components** for rates — `N − replacement_rate × D`, using the player's own
denominator. So AVG's value is hits above what a replacement gets in the same at-bats,
and ERA's is earned runs saved over the same outs. Every value is signed so positive is
better.

Per opportunity makes innings worth exactly zero for every pitcher (outs minus one per
out). Per slot-day charges a hitter for his team's off days and rewards a manager who
starts pitchers only on the days they pitch, which is lineup skill (milestone 11), not
player value.

## Consequences

- Good: volume categories carry value; off days are neutral on both sides.
- Bad / accepted cost: a starter's game day is compared with a replacement starter's
  game day, so a player who pitches deeper into games earns innings value, but one who
  simply starts more often does not earn extra per day — his extra days do.
- A played day is counted on the credited side only: a day batted in a hitter slot, a
  day pitched in a pitcher slot. A two-way player who bats but does not pitch while in a
  pitcher slot has no played day there (two such days in 2026).
- Bad / accepted cost: "played" for a pitcher means he appeared; a one-out relief
  appearance is a full played day.
- Follow-ups: none.
