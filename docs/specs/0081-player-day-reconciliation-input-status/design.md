# A player-day difference says whether its inputs were verified — design

Issue: #81 · Requirements: [requirements.md](requirements.md) · Tasks: [tasks.md](tasks.md)

## Overview

`rec_espn__player_day_differences` gains two columns, passed through and derived from
the started player-day it compares: `input_status`, and `status`, which is `difference`
when the inputs were verified and `unverified` when they were not. Nothing else about
the table changes: same rows, same grain, same existing columns. A small view then rolls
the `difference` rows up to (matchup, side, stat) and says what is wrong with any key the
register of known residuals does not account for; a singular test fails on those, and
unit tests hold both rules. One model changed, one view and one test file added.

## Alternatives considered

| | A — keep the rows, label them (chosen) | B — leave unverified out | C — census of every comparison | D — leave it |
|---|---|---|---|---|
| A row never claims an unsupported difference | yes | yes | yes | no |
| CI's table shows that nothing was compared | yes: 467 rows, all `unverified` | no: empty | yes | no |
| An empty table proves agreement | no: an unverified day whose numbers agree has no row | no | yes | no |
| Grain unchanged | yes | yes | no | yes |
| Rows, real 2026 | 22 | 22 | every started player-day × its stats | 22 |
| Rows, CI after #93 | 467, labelled | 0 | all 647 player-days × stats | 467 |
| New columns | 2 | 0 | 1 | 0 |

**A.** The comparison still happens; the row says what it is worth.

**B.** One `where` clause. It loses because the CI table would be empty while nothing in
it had been compared, which is the situation this project keeps writing tests against
(`…have_game_lines_to_check`, `rec_espn__every_side_is_verified`).

**C.** What the matchup-level table is. There it costs 6,912 rows; here it would be
38,665 player-days, each times the stats of its slot's role, almost all `match`.

**D.** The issue as filed.

## Decisions

| ADR | Decision | Status |
|---|---|---|
| [0032](../../adr/0032-a-player-day-difference-carries-the-status-of-its-inputs.md) | A player-day difference carries the status of its inputs; a `verified_off` day with an ESPN line is a difference | accepted |

The view and test of R3 are not in the ADR: they are a check on the table, and can be
dropped or changed without touching it.

## Detailed design

### `rec_espn__player_day_differences.sql`

- The `credited` CTE also selects `input_status` from
  `int_fantasy__started_player_days`.
- The final select adds, after `espn_games`:
  - `input_status`;
  - `status`: `'difference'` when `input_status in ('played', 'verified_off')`, else
    `'unverified'`.
- The `where` clause is unchanged, so R1.3 and R2.1 to R2.3 need no other SQL: a
  `verified_off` day is already compared against ESPN's line, and a `played` day with no
  line already against zero.
- Grain and key: one row per (`league_id`, `season`, `scoring_period`,
  `fantasy_team_id`, `platform_player_id`, `stat_id`). A player is in one started slot a
  day, and `credited` yields one row per component, each bridged to one stat.
- The header comment gains the two statuses and says that an `unverified` row is kept so
  the comparison is visible, and is evidence of nothing.

### `rec_espn__player_day_residuals.sql` and its test

A view (a saved query, rebuilt on read; nothing is stored). The rule lives here and not
in the singular test because dbt can unit-test a model and cannot unit-test a singular
test; `rec_fantasy__category_wins_by_group` holds its test's rule the same way (#94).

```
keys:  status = 'difference' rows grouped by
       (league_id, season, matchup_id, fantasy_team_id, stat_id): sum(difference), count
left join espn_reconciliation_residuals on (matchup_id, team_id, stat_id)
problem:
    'ambiguous_register'  more than one (league_id, season) among all keys
    'unregistered'        no register row
    'wrong_size'          abs(sum - expected_difference) > 1e-9
    null                  otherwise
```

`rec_espn__player_day_differences_are_registered.sql` selects the rows whose `problem`
is not null.

`ambiguous_register` is the fail-closed answer to a seed that names a matchup and no
season. Today one league-season has rosters, so one has differences. When a second does
(spec 0085 expects past seasons to gain rosters), a matchup id means two things and the
test stops the build until the register can tell them apart. The owner decided on
2026-10-09: fail closed here, no change to the seed in #81, and key the register by
league and season as its own work (#99).

It runs one way only. A register row with no player-day rows is not returned: 9 of the
31 are such, by nature (see the requirements). The matchup-level test already fails on a
stale register row.

What it adds to `fct_matchup_scores_match_espn`: that test sees a side's total. Two
player-day differences on one side and stat that cancel (one player credited a hit ESPN
does not have, another the reverse) leave the total matching, so there is no register
row and that test passes. Here the key has `difference` rows and no register row, so it
is returned. The rule is on the key, not on the sum alone: a key with any `difference`
row must have a register row, and the row must equal their sum.

### `_rec_espn__models.yml`

- Description brought up to date; `columns:` for `status` (`not_null`,
  `accepted_values: [difference, unverified]`) and `input_status` (`not_null`,
  `accepted_values` as on the source model).
- `dbt_utils.unique_combination_of_columns` on the key above.
- The unit test of R4.1, `player_day_differences_label_their_inputs`. Inputs given:
  `int_fantasy__stat_components` (H = hits, ER = earned_runs),
  `int_fantasy__started_player_days`, `stg_espn__player_game_stats`,
  `int_fantasy__matchup_periods`, `int_fantasy__matchup_sides`. A column a case does not
  give is null, and a null number yields no row, so each case names the component it is
  about.

## Test strategy

| Requirement | Test | Catches |
|---|---|---|
| R1.1, R1.2, R2.1–R2.3 | the unit test, eight cases | a status decided from the wrong column; a `verified_off` line dropped; an unverified row labelled a difference |
| R1.3 | the unit test's two no-row cases | the table becoming a census |
| R1.4 | `except` both ways against the table as it was, on the real season | a changed value, a lost row |
| R3.1–R3.3, R3.5 | the view's unit test, six cases | a key checked for existence but not size; a cancelling pair passing; unverified rows judged; a second season matched to the first's register |
| R3.4 | the singular test, on the real season | a scoring change nobody registered |
| R4.2, R4.3 | generic tests in YAML | a status outside the vocabulary; a fan-out in a join |
| Expected values | the last task | numbers that moved |

CI has no `difference` row, so in CI the singular test judges nothing; its rule is
exercised there by the view's unit test, case by case. The last task also runs the view
on the real season.

## Risks

- The register test fails in season on a legitimate case it did not foresee, such as a
  key whose registered difference mixes a scoring change with an inconsistent ESPN total
  — low; none in 2026 — the register would need a way to say so, and that is a decision
  to raise then, not to pre-empt.
- `ambiguous_register` makes one league-season's rows in the view depend on whether
  another has differences, which is what the tenant-isolation rule (ADR 0013) forbids of
  a model — certain in principle, invisible today — the isolation gate still passes,
  because no fixture league-season has a `difference` row. It is a deliberate alarm on
  a register that cannot tell seasons apart. Accepted by the owner on 2026-10-09 until
  the register is keyed by league and season (#99), which removes it.
- A reader treats the 467 CI rows as differences — low — they are labelled, and the YAML
  description says to filter.
- #93 has not merged when this is built — possible — the CI expected values then do not
  apply; the build stops and says so.

## Open questions

- **Whether `status` should use the matchup table's word for a real difference.** That
  table has `registered` and `unexplained`; this one cannot say which without joining
  the register, which the test does. The owner chose the two columns on 2026-10-09 and
  was not asked about the word separately, so it stands: `difference` is the honest word for
  what the row knows.
- **The pre-#93 CI split by status** was not measured; only its total, 308.

## Review log

| Source | Finding | Resolution |
|---|---|---|
| design-review | F1 (P1): the register test joins by matchup, side and stat with no league or season, so a second season's difference could pass against 2026's register row | Changed: R3.2 `ambiguous_register` fails the build as soon as two league-seasons have differences. Not changed: the seed gets no league or season column here; that is a column-set decision and touches the matchup-level table. The owner agreed on 2026-10-09 and had #99 filed for it |
| design-review | F2 (P2): labelling does not make an empty table mean agreement; an unverified day whose numbers agree has no row | Changed: the alternatives table, the goal and the ADR's driver now claim only that an existing row is labelled |
| design-review | F3 (P2): no repeatable negative case for the register test | Changed: the rule moves into a view, `rec_espn__player_day_residuals`, with a six-case unit test (R3.1, R3.5); the singular test selects its problems. A new model, approved by the owner on 2026-10-09 |

## Amendments
