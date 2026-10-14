# 0064. A count whose difference is traced to ESPN's own game lines is explained without a register row

- Status: proposed
- Date: 2026-10-13
- Spec: [0083-past-season-rosters](../specs/0083-past-season-rosters/design.md) · Issue: #83

## Context

A count that differs from ESPN's side total is `registered` only if
`espn_reconciliation_residuals`, a register kept by hand, holds a row for that league,
season, matchup, side and stat, with its cause and evidence. Every player-day key with a
difference against ESPN's own game lines must have such a row
(`rec_espn__player_day_differences_are_registered`). For 2026 that is 31 rows, 23 of them
`official_scoring_change`.

With seven past seasons built (2026-10-13), 498 count values are `unexplained`. Of them,
424 differ from ESPN's total by exactly the sum of that side's player-day differences
against ESPN's own lines, and those differences are 442 keys with no register row. 376
of the 457 player-day differences are off by exactly one, in total bases, hits, hits
allowed and earned runs: the shape of an official scoring change. Our boxscores of those
seasons were fetched years later and carry MLB's final ruling; ESPN's lines carry the
ruling at the time.

## Decision drivers

- The evidence for each such difference already exists in ESPN's own lines, and the
  model can check it on every build.
- A register kept by hand has to stay small enough to be kept by hand.
- Anything not traced must still fail.

## Considered options

1. **A status traced automatically**: a count off by exactly the sum of its player-day
   differences against ESPN's own lines is explained, with no register row.
2. **Generate register rows** by script, with evidence built from the data.
3. **Register by hand**, as 2026 was.

## Decision

Chosen by the owner on 2026-10-13: **option 1**, applied wherever the register has no
row for the key.

- A count with no register row whose difference equals, within 1e-9, the sum of the
  side's player-day differences for that stat (rows with status `difference` in
  `rec_espn__player_day_differences`) is `explained_by_game_lines`. It is decided after
  `registered`, so a register row always wins.
- A rate's implied value shifts each ESPN component by its registered difference, or,
  with none, by its game-line sum; a rate that equals it is `explained_by_component` as
  before.
- `rec_espn__player_day_residuals` no longer calls a key `unregistered` when its side and
  stat are `explained_by_game_lines`. A key whose sum is wrong for its register row is
  still `wrong_size`.
- A category result that flips because of such a value is `explained`, as for the other
  explained statuses.

## Consequences

- Good: 424 of the 498 unexplained counts, and the rates that follow from them, are
  explained by evidence the build checks, with no hand-kept row.
- Good: what stays `unexplained` is what ESPN's own lines do not account for, which is
  where a defect or an unmodelled rule would show (the games-started limit was found
  there).
- Bad / accepted cost: the cause of such a difference is not named. It is very likely an
  official scoring change; it is not proved play by play.
- Bad / accepted cost: from 2027 a scoring change in season is explained this way too,
  and needs no register row; the register is left for what the lines do not explain.
  2026's existing rows stay and still match.
- Bad / accepted cost: player-day differences that cancel on a side (one hit more for one
  player, one fewer for another) leave the side matching and are no longer each a register
  row.
