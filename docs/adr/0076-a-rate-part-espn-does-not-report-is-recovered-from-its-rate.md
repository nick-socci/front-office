# 0076. A rate part ESPN's totals do not report is recovered from ESPN's rate

- Status: accepted
- Date: 2026-10-16
- Spec: [0147-espn-matchup-lines](../specs/0147-espn-matchup-lines/design.md) · Issue: #147
- Amends: [0063](0063-a-rate-espn-gives-no-components-for-is-compared-directly.md)

## Context

2018's `scoreByStat` omits at-bats, hits and walks allowed, and earned runs. ADR 0063
compares those rates directly, and accepted that a differing one "can only be
`unexplained`": 35 AVG, WHIP and ERA values are. ESPN reports rates to eight decimals.
From the reported part and the rate, the missing part can be recovered: AB = H / AVG,
P_H + P_BB = WHIP × outs / 3, ER = ERA × outs / 27. All 858 of 2018's are within 1.25e-5
of a whole number. On the 823 that match, the recovered total equals ours. Of the 35, 21
differ from ours by the game lines, and 14 differ from ESPN's lines while ours equals them
(spec 0147, C11).

## Decision drivers

- Use ESPN's own numbers, not stand-ins for them.
- A recovery that is not clearly ESPN's must not be used.
- What was not checked stays visible (ADR 0063).

## Considered options

1. **Recover the missing part** when exactly one part is missing and the result is whole
   within 1e-4. Then explain it like a reported component (game lines, then matchup
   lines).
2. **Let ESPN's matchup lines stand in** for the missing part.
3. **Leave ADR 0063 as it is.**

## Decision

Chosen by the owner on 2026-10-16: **option 1**. A recovered part is ESPN's component total for the implied
value, and its shift is its game-line difference, or our part less ESPN's where ours
equals ESPN's lines (ADR 0074). `formula_checked` stays false, because a recovered part
reproduces ESPN's rate by construction. ADR 0063 holds where nothing can be recovered:
both parts missing, a zero rate or reported part, or a recovery that is not whole.

## Consequences

- Good: all 35 of 2018's rates are explained, by ESPN's own rate (C11).
- Good: option 2 would leave 14 unexplained. It treats ESPN's lines as its total, which
  is exactly what fails on those sides.
- Bad / accepted cost: WHIP's two hidden components are recovered only as their sum.
- Bad / accepted cost: a rate a hair from a whole number by chance (about 2 in 10,000)
  would be recovered. It explains nothing unless it also equals ours less the game lines,
  or ESPN's lines.
