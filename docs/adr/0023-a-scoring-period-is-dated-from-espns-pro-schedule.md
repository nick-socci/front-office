# 0023. A scoring period is dated from ESPN's pro schedule

- Status: accepted
- Date: 2026-10-07
- Spec: [0073-espn-pro-schedule](../specs/0073-espn-pro-schedule/design.md) · Issue: #73
- Supersedes: [0021](0021-a-scoring-period-is-dated-from-mlbs-schedule.md)

## Context

ADR 0021 dates a scoring period from MLB's schedule: period 1 is MLB's first
regular-season official date. It was chosen on 2026-10-07 to lift the hold of #70 without
new ingestion, with ESPN's own schedule named as the follow-up.

What changed: that schedule is now specified for landing. ESPN's game-level season
resource lists every pro game with its start time and scoring period. Checked for 2026,
2025, 2024 and 2018: every game of a season implies the same date for period 1 (its
Eastern date minus its period, plus one), including the Tokyo and Seoul openers. Against
the 2026 warehouse, all 2,339 distinct (period, game) pairs in ESPN's roster stat lines
are in the schedule with the same period, and period 1 is 2026-03-25, MLB's opening day.

Under ADR 0021 `stg_espn__scoring_periods` reads `stg_mlb__games`, the one cross-source
`ref` in staging, and an ESPN league-season cannot be dated without MLB's schedule for
its season.

## Decision drivers

- Prefer the source's own statement to an inference about it.
- Keep an independent check on whatever the rule is.
- A league-season should be datable from ESPN data alone (#57).
- A missing input must fail the build, not change the rule quietly.

## Considered options

1. **ESPN's schedule is the rule; MLB's opening day is the check.**
2. **MLB stays the rule (ADR 0021); ESPN's schedule is a check.**
3. **Each period takes the date of its own games**, gaps filled from neighbours.
4. **ESPN's schedule, falling back to MLB's when it is missing.**

## Decision

Chosen: **option 1**, by the owner on 2026-10-07.

Period 1 of a season is the earliest date its scheduled games imply, and a test fails
the build unless every game implies that same date. Period *p* is *p* − 1 days later.
`stg_espn__scoring_periods` reads `stg_espn__pro_games` and `stg_espn__league_settings`
only. MLB's opening day and MLB's games per date remain as tests.

Option 2 keeps an inference where the answer is published, and keeps the staging
exception. Option 3 needs a rule for the periods with no game, which is the same
assumption with more code. Option 4 hides a missing schedule behind dates that look
right, and spends the independent check as the fallback.

## Consequences

- Good: staging reads one source per model again.
- Good: the opening-day test is evidence from two sources again, as it was before #70.
- Good: a past season is dated from one public ESPN request.
- Good: the 180 dates of 2026 do not move.
- Bad / accepted cost: dates now rest on an undocumented ESPN view. If it changes, the
  build fails on null dates until the model is pointed back at ADR 0021's rule.
- Bad / accepted cost: one period per Eastern day is still an assumption for the periods
  with no game. It is tested on every game of every season loaded.
- Bad / accepted cost: ADR 0021 stood for one day.
- Follow-ups: #75 can read the last period with a game from the new model.
