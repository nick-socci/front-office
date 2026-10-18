# 0077. A player-day difference is accounted for when ESPN's matchup lines carry it

- Status: accepted
- Date: 2026-10-16
- Spec: [0147-espn-matchup-lines](../specs/0147-espn-matchup-lines/design.md) · Issue: #147
- Amends: [0064](0064-a-count-traced-to-espns-own-game-lines-is-explained.md)

## Context

`rec_espn__player_day_differences_are_registered` fails on a key (side and stat with
player-day differences against ESPN's daily game lines) that has no register row and
whose side and stat are not `explained_by_game_lines`. 18 keys fail on past seasons:

- 9 are on components 2018's totals do not report.
- 4 are on stats the league does not score.
- 2 cancel on a matching side, and one walk sits on a side whose total matches.
- 2 are on a side whose total is inconsistent, and 1 is #152's start.

One of the 18 cannot be registered at all, since the side shows no difference to match
it. ESPN's matchup lines are a second record of what ESPN credited each player. For all 446
keys accounted today and 17 of the 18, ours less the key's difference equals them. The
18th is #152's: ESPN's daily line has the start, and its matchup lines leave it out
(spec 0147, C16, C17).

## Decision drivers

- The test exists to find player-days ESPN credited differently from us.
- A key that cannot be registered must not be the only way to pass.

## Considered options

1. **Carried by the lines**: a key is accounted for by a register row of its size, or
   when our side value less its difference sum equals ESPN's matchup lines.
2. **Scored stats only**: judge only stats a scored stat is built from, and register the
   rest by hand.

## Decision

Chosen by the owner on 2026-10-16: **option 1**, replacing ADR 0064's "its side and stat are
`explained_by_game_lines`" in this rule. `wrong_size` is unchanged.

## Consequences

- Good: 17 of 18 accounted; #152's start still fails until #152 lands, as a crediting
  difference should.
- Good: cancelling differences are accounted when ESPN agrees with itself about them,
  without a hand row each.
- Bad / accepted cost: a key is no longer tied to the side total. That link is the
  matchup reconciliation's job, which judges every side and stat itself.
