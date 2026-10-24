# 0098. The CI fixtures carry matchup-days captures of their own matchups

- Status: accepted
- Date: 2026-10-23
- Spec: [0178-matchup-days-fixture](../specs/0178-matchup-days-fixture/design.md) · Issue: #178

## Context

The CI fixtures hold no `espn/matchup_days` capture. So `stg_espn__matchup_days` and
`stg_espn__matchup_player_lines` are empty in CI, and 17 generic tests, 6 singular tests
and the tenant-isolation gate read nothing on them (spec 0178, C1, C9, C12). ADR 0088
exempted the two relations, linked to #178, and ADR 0087 named the missing endpoint as a
follow-up.

The fixture is two fictions joined together. Its rosters and game lines come from real
scoring periods 31, 36 and 37, renumbered 1, 6 and 7. Its matchups are real matchups 1 and
2 of matchup period 1, whose real days are 1 to 12, trimmed to 1 to 7 (C2). ESPN's real
captures of scoring periods 1, 6 and 7 mark matchup period 1 and carry ESPN's lines for
those two matchups. Those of 31, 36 and 37 mark periods 4 and 5 and carry no lines for
them (C3, C4). Within the fixture's matchups, ESPN's lines sum exactly to ESPN's totals,
on 80 of 80 count rows (C8).

## Decision drivers

- No rewritten ESPN data (ADR 0087's driver). A fixture value is what ESPN sent, cut down
  by an allowlist.
- The fixture's two records of a matchup, its totals and its lines, must describe the
  same matchup.
- The models must run on real input in CI, including the tenant-isolation gate.
- Keep the committed fixtures small.

## Considered options

1. **Real captures of the fixture's matchup days**: real scoring periods 1, 6 and 7, the
   fixture's two matchups, rebuilt from an allowlist of the capture view's fields.
2. **Real captures of the rosters' days, renumbered**: 31, 36 and 37, with
   `matchupPeriodId`, matchup ids and teams rewritten to agree with the matchups fixture.
3. **No fixture**: the two exemptions stay, as a permanent gap.
4. **Plants into the empty relations**, which would supersede ADR 0088's no-plant rule
   for empty relations.

Within option 1, the set of periods: {1, 6, 7}, {7} alone, or {1 … 7}.

## Decision

Chosen by the owner on 2026-10-23, going through the spec's decisions: **option 1, with
scoring periods {1, 6, 7}**. It is the only option that keeps
every ESPN value as sent and also runs the models end to end in CI. Its lines agree with
the fixture's totals (C8). The captures follow the matchups, not the rosters, so their
period numbers need no renumbering. {1, 6, 7} are the fixture's days of data, and three
captures make the lines model choose the last of them. {7} alone would make that choice
trivial, and {1 … 7} adds four days that have no data, for 466 KB.

Option 2 rewrites ESPN's data, and fails `int_fantasy__matchup_period_sources_agree`
unless the rewrite is complete. Option 3 leaves the gap that #174 found. Option 4 shows
that the tests can fail, not that the models work on real captures, and costs about 17
plants.

The marker is kept as an empty object, as the BigQuery upload keeps it (ADR 0061): only
its presence is read. The multi-league fixture's one-period 2027 seasons keep only the
period-1 capture, as they already do for rosters.

## Consequences

- Good: 17 generic tests and 6 singular tests read real rows in CI. Tenant isolation
  covers both models. The plant gate's two #178 exemptions go.
- Good: in CI, `rec_espn__matchup_stat_differences` now has ESPN's lines beside ESPN's
  totals, and the two agree.
- Bad / accepted cost: +349,650 bytes in `fixtures/landing` and about +0.93 MB in
  `fixtures/landing_multi` (C5).
- Bad / accepted cost: the fixture's matchups and their lines are now tied to the same
  real matchups. Generation stops if the landed captures ever disagree on them (spec 0178,
  R1.7).
- Bad / accepted cost: the CI build no longer runs `duckdb__fo_captures`' branch for an
  endpoint with no captures. A pytest on a temporary landing zone still holds it (C15).
- Bad / accepted cost: the new lines describe the matchups' real days (1, 6 and 7), not
  the rosters' (real 31, 36 and 37). So CI cannot check that a side's lines agree with its
  rosters and game lines. And `rec_espn__matchup_stat_differences` stays all `unverified`
  (96 rows), so its verified statuses still have no CI row (ADR 0087).
- Follow-ups: the marker fallback of `int_fantasy__matchup_periods` stays without a CI row,
  because 2026 lists every fixture day itself. Exercising it would take a fixture season
  that has no `pointsByScoringPeriod`.
