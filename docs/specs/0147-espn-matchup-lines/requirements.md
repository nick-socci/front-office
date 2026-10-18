# ESPN's own matchup lines settle the past seasons' differences — requirements

Issue: #147 · Tier: M · Status: draft

## Problem

On the eight-season warehouse the real `dbt build` fails three reconciliation tests on
past seasons (#147): `fct_matchup_scores_match_espn` (133 rows),
`fct_matchup_results_match_espn` (79) and `rec_espn__player_day_differences_are_registered`
(18). #83 explained most past-season differences from ESPN's own game lines (ADR 0064),
and #152 takes one start out. What is left is mostly differences that ESPN's daily game
lines cannot see: ESPN's side total disagrees with ESPN's own lines, and our value agrees
with the lines (design.md, C3 to C6). 2026's register records eight such values by hand as
`espn_total_inconsistent`, from a spike capture of `rosterForMatchupPeriod`. That view is
already landed for every past season, inside every matchup-days capture (C1, C2). It is
not read. The rest are small gaps in the rules: a count of two components (C9), 2018's
rates whose components ESPN's totals leave out (C10, C11), byes (C14), winners (C15) and
the player-day rule (C16, C17).

The owner decided on 2026-10-16 that this spec covers the reconciliation only. Two league
rules found here change `fct_matchup_results` itself and have their own issues: the
playoff tiebreak (#159) and the minimum innings (#160). The 2023 slope question is #161.

## Goals

- Every count or rate that differs from ESPN's total is explained by evidence the build
  checks, wherever ESPN's own lines carry that evidence, with no row kept by hand.
- A difference ESPN's own lines do *not* carry still fails, by name. #152's start limit is
  the proof: the new rules leave it failing (C17).
- Nothing that matches ESPN today changes status.
- After this spec and #152, `fct_matchup_scores_match_espn` and
  `rec_espn__player_day_differences_are_registered` pass on all eight seasons, and
  `fct_matchup_results_match_espn` fails only on the rows of #159 and #160.

## No-gos

Explicitly out of scope. Work that drifts here is escalated, not done.

- No league rule is modelled here: not the playoff tiebreak (#159), the minimum innings
  (#160) or the games-started limit (#152). Their rows keep failing until those land.
- The 2023 slope question (#161) and the warning `stg_idmap__covers_started_players` are
  not touched.
- No new landing and no new ESPN request. The lines are read from the matchup-days
  captures already landed.
- Suspended games are not re-credited. Seven past-season sides differ because ESPN's
  total of the time handled a suspended game differently from its present lines (C7).
  This spec explains them by the lines and does not model that crediting.
- No register row is added, and 2026's 31 rows stay as they are (ADR 0074).
- No production mart changes. Only the staging layer and the reconciliation do.

## Rabbit holes

Places this could sink time, and the decision already taken to avoid them.

- Naming the cause of each inconsistent ESPN total → not done. The rule needs the
  inconsistency, not its cause, as ADR 0064 did for game lines. What the data suggests
  (suspended games; totals frozen when the season ended) goes in the design as a finding.
- Splitting a suspended game's stats by the day each part was played → needs play-by-play
  and is a crediting rule, not a reconciliation one. Out of scope (no-go 4).
- Separating WHIP's two hidden components (hits and walks allowed) in 2018 → not needed.
  Their sum is what ESPN's rate fixes, and what the rule compares (ADR 0076).
- A season in progress, whose matchup lines are period-to-date → the lines are read from
  the capture of the period's last scoring period. A matchup still in progress is not
  explained by lines read before it ended (R1.3, Risks).

## Requirements

### R1. ESPN's matchup lines are staged

ESPN's own record of what each player was credited with in a matchup is read from the
captures already landed.

- R1.1 THE SYSTEM SHALL hold one row per league-season, matchup, side, ESPN player and
  stat of ESPN's `rosterForMatchupPeriod` lines, from the matchup-days captures: the
  matchup's `id`, the side's `teamId`, the entry's `playerId`, and each key and value of
  the line with `statSourceId` 0 and `statSplitTypeId` 5.
- R1.2 THE SYSTEM SHALL read each matchup's lines from the newest capture of the last
  scoring period of its matchup period that has a capture, chosen on the manifest's
  narrow columns and kept by a semi-join on `file_path` (AGENTS.md, capture views).
- R1.3 THE SYSTEM SHALL record the scoring period and `fetched_at` of the capture each
  row is read from.
- R1.4 THE SYSTEM SHALL read no player name and no key of member data from these
  captures. The capture view declares only the fields R1.1 names, and the BigQuery
  projection of ADR 0061 gains only those.
- R1.5 IF a stat value of a line is not a number THEN THE SYSTEM SHALL leave that stat
  out of the row set, and keep the line's other stats.

### R2. A count ESPN's own lines account for is explained

- R2.1 WHEN a count has no register row, is not `explained_by_game_lines`, and our value
  less its game-line difference (0 when it has none) equals, within 1e-9, the sum of
  ESPN's matchup lines for that side and stat, while that sum differs from ESPN's side
  total by more than 1e-9, THE SYSTEM SHALL give it the status
  `explained_by_matchup_lines` (ADR 0074).
- R2.2 THE SYSTEM SHALL take a stat absent from every line of a side that has lines as 0
  for that side, and SHALL apply R2.1 to no side that has no lines.
- R2.3 THE SYSTEM SHALL carry the side's matchup-line sum as a column,
  `matchup_line_value`, on every count row of `rec_espn__matchup_stat_differences`, and
  null on a rate row: a sum of players' rates is not a side's rate.
- R2.4 WHEN a count is built from more than one component (SVHD is saves plus holds) THE
  SYSTEM SHALL take its game-line difference as the sum of its components' game-line
  differences (ADR 0075).

### R3. A rate follows its explained components

- R3.1 THE SYSTEM SHALL shift each ESPN component of a rate, for its implied value, by
  its registered difference if it has one; otherwise by our value less ESPN's if that
  component is `explained_by_matchup_lines`; otherwise by its game-line difference; and
  otherwise by 0.
- R3.2 WHEN one part of a rate (its numerator or its denominator) has no component in
  ESPN's side totals and the other part has all of its own THE SYSTEM SHALL recover
  ESPN's total of the missing part from ESPN's rate and the reported part (ADR 0076).
- R3.3 IF a recovered total is not within 1e-4 of a whole number, or cannot be recovered
  (a zero rate, or a zero reported part), THEN THE SYSTEM SHALL not recover it, and the
  rate is judged as ADR 0063 has it.
- R3.4 WHEN a part is recovered THE SYSTEM SHALL use it as ESPN's component total for the
  implied value. Its shift is the game-line difference of its components if our part
  less that difference equals ESPN's recovered total; otherwise our part less ESPN's, if
  our part less the game-line difference equals the matchup lines' part and the lines'
  part differs from the recovered total; otherwise 0.
- R3.5 THE SYSTEM SHALL keep `formula_checked` false for a rate whose part was recovered.
  A recovered part reproduces ESPN's rate by construction, so the formula was not checked.

### R4. Byes and winners

- R4.1 THE SYSTEM SHALL give every category result of a side whose matchup ESPN does not
  play (a bye) the status `bye`, and `fct_matchup_results_match_espn` SHALL not return it.
- R4.2 WHEN our winner differs from ESPN's and every category result of that matchup
  whose result differs is `explained` THE SYSTEM SHALL treat the winner as explained and
  not return it (ADR 0078).
- R4.3 IF a winner differs and any category result of that matchup that differs is not
  `explained`, or no category result differs, THEN THE SYSTEM SHALL return it as today.

### R5. A player-day difference is accounted for by ESPN's matchup lines

- R5.1 THE SYSTEM SHALL count a key (league-season, matchup, side, stat) with player-day
  differences as accounted for when it has a register row of its size, or, when it has
  no register row, when our side value of that stat's component less the key's
  difference sum equals, within 1e-9, ESPN's matchup-line sum for that side and stat
  (ADR 0077). A key with a register row is judged by that row alone (amended
  2026-10-18, design.md *Amendments*).
- R5.2 IF a key has neither THEN THE SYSTEM SHALL report it as `unregistered` (no
  register row, not carried by the lines) or `wrong_size` (a register row of another
  size, whatever the lines say), as today.
- R5.3 THE SYSTEM SHALL judge a key on a stat that no scored stat of its league-season
  is built from by the same rule as any other.

### R6. Nothing else moves

- R6.1 THE SYSTEM SHALL give every row whose status today is `match`, `registered`,
  `explained_by_game_lines`, `explained_by_component`, `bye` or `formula_mismatch` the
  same status and the same `our_value`, `espn_value` and `difference`.
- R6.2 THE SYSTEM SHALL leave every model outside `staging/espn`, the matchup-days capture
  view and `reconciliation/espn` with the same rows.

## Expected values

Counted on `data/warehouse_150.duckdb` (#150's eight-season build, `main` at `d927c00`)
on 2026-10-16 by simulating the rules (design.md, *Claims ledger*), and recounted at
build time. "With #152" assumes #152's own expected values (its spec, *Expected values*).

| Check | Expected | How to verify |
|---|---|---|
| Sides with lines (R1) | every side of every played matchup of every covered league-season | played sides with no line: 0 (C2) |
| Line sums against ours (R1, R2.4, C5) | on all 43,906 count rows that are not byes, the lines' sum equals our value less its game-line difference (R2.4's for SVHD), except the 6 counts of 2023, matchup 110, team 7 (#152's start) | query of C5 |
| Statuses, before #152 | unexplained 133 → 9; `explained_by_matchup_lines` 0 → 66; `explained_by_game_lines` 424 → 426; `explained_by_component` 269 → 325; match 52,345, registered 31, bye 366, formula_mismatch 0: unchanged | count by status |
| The 9 left | 2023, matchup 110, team 7: GS, OUTS, P_H, P_BB, ER, K, WHIP, ERA, K/9 | the rows |
| Statuses, with #152 | unexplained 0 | count by status |
| Every other row (R6.1) | same status and values as the saved table | `except all` both ways on the saved pre-change table |
| 2018 recovered parts (R3.2) | 858 rates (AVG, WHIP, ERA) recovered, none further than 1.3e-5 from a whole number; on the 823 that match, the recovered total equals ours | the recovery query of C11 |
| Category results | unexplained 28 → 6 (2021, matchup 113: WHIP, K/9, L on both sides, #160); missing_ours 36 → 0 (2018 byes now `bye`) | count by status |
| Winners | 15 differ → 10 returned (the tied playoff matchups of #159); 5 explained: 2019 m74, 2022 m123, 2023 m138, 2025 m77, 2025 m142 | the test's winner rows |
| `fct_matchup_scores_match_espn` | 133 → 9; 0 with #152 | the test |
| `fct_matchup_results_match_espn` | 79 → 16 (6 of #160, 10 of #159) | the test |
| `rec_espn__player_day_differences_are_registered` | 18 → 1 (2023, m110, t7, ER: #152's start); 0 with #152 | the test |
| Accounted keys today (R5.1) | all 446 stay accounted (464 keys in all) | the key query of C16 |
| Build cost | full eight-season build no more than 10% above #150's 179 s and 9.2 GB peak (C21), run the same way | `/usr/bin/time -v` on the build |
