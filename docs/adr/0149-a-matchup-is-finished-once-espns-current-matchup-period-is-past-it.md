# 0149. A matchup is finished once ESPN's current matchup period is past it

- Status: accepted
- Date: 2026-11-23
- Spec: [0232-dashboard](../specs/0232-dashboard/design.md) · Issue: #232
- Amends: [0148](0148-standings-are-the-computed-record-reconciled-with-espns.md)

## Context

ADR 0148 counts a regular-season matchup in the standings once "the last scoring period of its
matchup period is before ESPN's status counter (`latest_scoring_period`)". The last scoring period
came from `int_fantasy__matchup_periods`. In a running season, though, that bridge grows a day at
a time: it reads each side's `pointsByScoringPeriod` (ADR 0055). So on the second day of a
seven-day matchup the period's last mapped day is its first, the counter is past it, and the
matchup counts with five days still to play (PR #236 review, round 1, F1). The real 2026 numbers
were right only because every period was complete when it was captured.

ESPN publishes no up-front list of a period's days: `scheduleSettings.matchupPeriods` maps each
matchup period to itself (`{"1": [1], …}`, as `stg_espn__matchup_periods` notes). It does
publish `status.currentMatchupPeriod`, staged as `current_matchup_period`. After the 2026 season it
reads 24, past all 21 regular-season periods (spec C19). What it reads mid-season has never been
seen: every 2026 capture was taken after the season ended.

## Decision drivers

- A matchup still being played is in no one's record (R1.5).
- One ESPN field, read for what it says, rather than a mapping that is complete only after the
  fact.
- Checkable in the 2027 rehearsal, like the seed.

## Considered options

1. **Finished when `matchup_period < current_matchup_period`**, and no category is undecided.
2. **Both counters**: option 1 *and* the period's last mapped day before `latest_scoring_period`.
3. **Keep ADR 0148's rule**, and accept a record that counts a matchup early until its period ends.

## Decision

Chosen by the owner on 2026-11-23, on PR #236's review: **option 1**, as recommended. It reads
the period ESPN says is being played, and needs nothing that only fills in later. Option 2's
second condition could only hold back a matchup that option 1 already holds back. Option 3 is
the defect the review found.

`int_fantasy__league_seasons` carries `current_matchup_period` in place of
`latest_scoring_period`, which only the standings read. ADR 0148's other choices stand: the
computed record beside ESPN's, the reconciliation test, seed order once the regular season is
complete, and H2H_MOST_CATEGORIES only.

## Consequences

- Good: in season, the record counts exactly the matchups whose period ESPN has moved past.
- Good: the standings no longer read `int_fantasy__matchup_periods` at all.
- Bad / accepted cost: the rule rests on what `currentMatchupPeriod` holds mid-season, which is
  unseen. If ESPN moved it before the period's last day was settled, a matchup would count a day
  early.
- Follow-ups: in #220's rehearsal or the first week of 2027, check that `currentMatchupPeriod`
  moves when a matchup period ends, beside the seed check ADR 0148 asks for.
