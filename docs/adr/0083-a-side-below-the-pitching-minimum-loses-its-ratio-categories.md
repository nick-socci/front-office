# 0083. A side below the pitching minimum loses its ratio categories

- Status: accepted
- Date: 2026-10-18
- Spec: [0160-pitching-minimum](../specs/0160-pitching-minimum/design.md) · Issue: #160

## Context

From 2021 on, the league's settings require 30 outs a matchup
(`statQualificationMinimum`, stat 34; spec 0160, C1). ESPN's help pages do not say what a
side that falls short loses (C11). In eight seasons one side did: 2021, matchup 113, team
5, with 24 outs (C2). ESPN turned three of its results into losses: WHIP and K/9, rates it
won by value, and L, a lower-is-better count it won by value. It left CG, 0–0, a tie, and
judged IP, ERA, K, W and SV by value (C3). Both sides falling short has never happened.

## Decision drivers

- Fit ESPN's one observed case exactly.
- A rule stated from the categories' components, not from stat ids, so it holds for any
  league's category set.
- Results stay complementary: a WIN for one side is a LOSS for the other.

## Considered options

1. **Pitching rates and lower-is-better pitching categories are lost**; both below is a tie
   in those categories.
2. **Pitching rates only.** Contradicts the case: L would stay a WIN.
3. **Every pitching category.** Contradicts the case: CG would become a LOSS.

For both sides below: a **tie**; **by value**; or **fail the build**.

## Decision

Chosen by the owner on 2026-10-18: **option 1**, and a **tie** when both sides are below.
A category is bound when every one of its components is a pitching component, and it is a
rate (it has a denominator) or lower-is-better. A side below the minimum loses every bound
category, whatever the values, and a 0-out side loses even though its rate is undefined.
When both sides are below, each bound category is a tie. Every other category is judged by
value, as before.

## Consequences

- Good: the 6 unexplained category results of 2021 m113 match ESPN, and the rule reads
  the same in any league's category set.
- Bad / accepted cost: the reading rests on one case. Both sides falling short is decided
  by choice, not by evidence; the reconciliation will show a difference if ESPN ever
  disagrees.
- Follow-ups: where the rule is applied is ADR 0084; the minimum's scale and unread
  settings are ADR 0085.
