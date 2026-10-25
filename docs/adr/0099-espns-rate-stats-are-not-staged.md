# 0099. ESPN's rate stats are not staged

- Status: accepted
- Date: 2026-10-24
- Spec: [0194-espn-rates-not-staged](../specs/0194-espn-rates-not-staged/design.md) · Issue: #194

## Context

ESPN's stat lines carry rates beside counts: 15 of the 84 stat ids in its game lines
(spec 0194, C7). A rate whose denominator is zero has no value. ESPN writes one anyway,
encoded by season and by endpoint (C3 to C6):

- 2018 game lines: the largest double, 1.7976931348623157e308 (1,781 values);
- 2019 to 2026 game lines: `0.0` (about 2,000 a season);
- 2021 game lines: NaN, for runs created (4,076);
- matchup lines: the string `"Infinity"`, which spec 0147 R1.5 already drops.

Two of the 2018 values in one sum overflow it: DuckDB gives infinity, and BigQuery stops
(#194, found by #135). Rule 4 keeps the project's own numbers off rates, and no reader of
the two line models takes a rate (C8). The `0.0` encoding cannot be told from a real zero
by its value.

## Decision drivers

- No undefined rate may be read as a number, in any encoding ESPN uses.
- No guessing at ESPN's formulas: 11 of the 15 rates are not in the components seed (C7).
- Every count and every reconciliation stays as it is.
- One meaning of "ESPN's lines" across the two models that stage them.

## Considered options

1. **Rates are not staged.** A generated seed column names the 15 rates, and both line
   models drop them.
2. **Sentinels become null.** The largest double, NaN and infinity are nulled by value,
   and every stat is kept.
3. **Each rate nulled at a zero denominator.** Rates are kept, and each one whose
   denominator is zero is nulled.

## Decision

Chosen by the owner on 2026-10-24: **option 1, rates are not staged**, in both line
models. The rates are named, not the counts. The owner's reading of the data is that
every ESPN rate at a zero denominator is undefined, whatever value ESPN wrote. Option 1 is
the only option that removes every encoding of that, including the `0.0` that option 2
leaves as a number. It needs no formula, which option 3 does. On a prototype built on the
real season, only the two line models change, by removed rows, and every reconciliation
model downstream is identical (C9).

Naming the rates keeps the 7 stat ids that espn-api does not name (22, 30, 61, 64, 78,
79, 80), as both models keep them today. Their values cannot tell a rate from a count:
WPCT and SV% are also 0 or 1 per game.

## Consequences

- Good: no model can sum a sentinel or read ESPN's `0.0` as a perfect rate. Staging is
  smaller by 1,343,928 game-line rows and 334,395 matchup-line rows (17.9% of each).
- Good: two tests hold the rule, with plants: no rate staged, and no value that is
  non-finite or at least 1e300. The second also catches a new encoding of "undefined" in
  a count, or in a rate the list misses.
- Bad / accepted cost: staging no longer carries everything ESPN sends, which departs
  from the usual practice. A model that needs an ESPN rate as ESPN shows it must take it
  out of the list deliberately, and amend this record.
- Bad / accepted cost: a rate ESPN adds later passes as a count until it is named.
- Follow-ups: none. Revisit if a model needs one of ESPN's rates, or if espn-api names
  one of the 7 unknown ids as a rate.
