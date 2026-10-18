# 0084. Every category result is decided by one macro that applies the minimum

- Status: proposed
- Date: 2026-10-18
- Spec: [0160-pitching-minimum](../specs/0160-pitching-minimum/design.md) · Issue: #160

## Context

Category results are decided in three places (spec 0160, C9):
- `fct_matchup_category_scores`, which `fct_matchup_results`, the ESPN reconciliation and
  the actual side of the lineup mart read;
- the optimal result of `fct_lineup_decision_categories`, an inline copy of the rule with a
  comment that says "if that rule changes, change it in both";
- the actual and the rescored results of `rec_fantasy__category_wins_added`.

ADR 0083 changes the rule, and each place has different outs to judge it on: actual, the
optimal lineup's, or the swapped side's.

## Decision drivers

- Every place that scores a category scores it as the league does.
- One copy of the rule, so the copies cannot drift.

## Considered options

1. **All three places, through one macro** that takes the values and each side's
   below-the-minimum flag.
2. **The fact and the optimal lineup only.** The rescoring check stays by value.
3. **The fact only.** The lineup mart's optimal result and the rescoring check stay by
   value.

## Decision

Chosen by the owner on 2026-10-18: **option 1**. The macro, `fo_category_result`, is the
rule. The fact passes actual outs, the lineup mart the optimal lineup's own outs, and the
rescoring check the swapped side's outs.

## Consequences

- Good: one rule, and the lineup mart's warning comment goes away. The optimal lineup and
  the rescoring are judged as the league judges.
- Bad / accepted cost: `category_wins_added` can move on at most 49 pairs (C8), and with it
  the 2023 slope that #161 is about, by what those pairs carry.
- Follow-ups: a future scoring rule goes into the macro, once.
