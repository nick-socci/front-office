# 0148. Standings are the computed record, reconciled with ESPN's

- Status: accepted
- Date: 2026-11-21
- Spec: [0232-dashboard](../specs/0232-dashboard/design.md) · Issue: #232

## Context

No mart holds standings. `int_fantasy__teams` carries ESPN's reported `wins`, `losses`, `ties` and
`playoffSeed`. Counting each team's regular-season matchup results from `fct_matchup_results`
gives ESPN's record for 90 of 96 team-seasons. The 6 that differ are explained, two teams at a time,
by the three regular-season matchups already in `rec_espn__winner_differences` (C6). ESPN's seed
breaks ties by a rule that is not category wins (C7), so the seed cannot be rebuilt from the marts.
Every season with matchups is `H2H_MOST_CATEGORIES`; 2020 was `ROTO` and has none (C5). Whether
`playoffSeed` is the live standing during a season is unknown: every 2026 capture was taken after
it ended (C8). What an ESPN field means, and a mart's column set, are the owner's to decide.

## Decision drivers

- The record shown is one the project can test, and that agrees with ESPN or says why not.
- No reimplementation of ESPN's tiebreakers.
- General across leagues: no rule for a scoring type the data has never shown.

## Considered options

1. **Both**: `fct_team_standings` holds the computed regular-season W-L-T and category W-L-T beside
   ESPN's reported W-L-T and seed. A dbt test holds that they differ by exactly what the listed
   matchups change. The page orders a completed regular season by ESPN's seed, and a season in
   progress by computed wins, then losses, labelled "by record so far".
2. **ESPN's record only**, as reported, in `dim_fantasy_teams`.
3. **The computed record only**, ordered by win percentage, with ties left tied.

## Decision

Chosen by the owner on 2026-11-22, at the spec's walkthrough: **option 1**, as recommended, with the
reading of `latestScoringPeriod` and `playoffSeed` given here. It shows the order ESPN's league uses, and a record the project computes
and reconciles. Its test turns a new, unexplained difference into a failed build, as the
reconciliation does elsewhere. Option 2 shows a number the project cannot check. Option 3 orders
teams differently from the league's own standings whenever two records tie (C7).

The computed columns are defined for `H2H_MOST_CATEGORIES` only. They are null for any other
scoring type, which keeps ESPN's columns. A regular-season matchup counts once it is finished: the
last scoring period of its matchup period is before ESPN's status counter (`latest_scoring_period`,
as ADR 0016 reads it), and no category is undecided. After every real season, the counter is past
the last regular-season day (C19). The seed orders only a completed season, because what it holds
mid-season has never been seen.


## Consequences

- Good: standings agree with ESPN, or the build says which matchup explains the difference.
- Bad / accepted cost: in season the computed record leaves out the matchup in progress, by design.
  The order of a season in progress is not ESPN's when two teams tie on wins and losses.
- Follow-ups: in #220's rehearsal or the first week of 2027, check whether `playoffSeed` is live
  (if so, it could order a season in progress too) and that the counter moves at each rollover. A league of another scoring type needs its own rule,
  written when its data exists.
