# The register of known differences names its league and season — design

Issue: #99 · Requirements: [requirements.md](requirements.md) · Tasks: [tasks.md](tasks.md)

## Overview

The register seed gains `league_id` and `season` as its first two columns, holding the
real ESPN league id and 2026 on all 31 rows, and its key becomes the five columns. Every
join to it adds those two columns: the two in `rec_espn__matchup_stat_differences`, and
the one in `rec_espn__player_day_residuals`, whose `ambiguous_register` alarm then has
nothing left to guard and is removed. The two singular tests that judge the register
itself (a singular test is a SQL file under `dbt/tests/` that fails when its query returns
a row) take their rule from a new view, `rec_espn__register_rows`, so that a unit test can
hold it. One seed, two models and two tests changed; one view added; no number on the real
season moves.

## Alternatives considered

### How a row names its league (ADR 0040)

| | A — the real ESPN league id (chosen) | B — an alias and a local mapping | C — a hash of the league id | D — keep the register out of the repo |
|---|---|---|---|---|
| Joins like every other model | yes: `league_id`, `season` | no: through a mapping | no: every join hashes | yes |
| Works for a second league with no new setup | yes | no: a mapping entry per league, on every machine | yes | yes |
| Publishes something new | no: the id is in `ingestion/tests/` and in history | no | no | no |
| Hides the league id | no | yes, in the seed only | no: 5 digits, 100,000 guesses | yes |
| A real build needs something CI does not have | no | yes: the mapping | no | yes: the file |
| The evidence stays public and reviewed | yes | yes | yes | no |

**A.** The seed is keyed the way everything else in the warehouse is, and nothing has to
be configured for a row to apply. Chosen by the owner on 2026-10-09.

**B.** The seed would say `home`, and a gitignored file or a dbt variable would turn that
into an id at build time. It loses because it hides, in one file, an id that five tracked
test files already state, and pays for it with a second thing every real build must have
and CI cannot check.

**C.** Looks private and is not: a five-digit id is recovered by hashing every five-digit
number.

**D.** The register is the project's public account of where it disagrees with ESPN and
why. Moving it to `data/` loses that and leaves CI unable to parse or test the file.

### Where the register's own rule lives (ADR 0041)

| | A — a view the tests select from (chosen) | B — the join written in each test file | C — register-only rows in the matchup table |
|---|---|---|---|
| A wrong join can fail in CI | yes: a unit test | no: CI has no register row that applies | yes |
| A wrong join can fail on the real season | only if it loses a row | only if it loses a row | only if it loses a row |
| New relations | 1 view | 0 | 0 |
| Changes an existing grain or status | no | no | yes |
| The rule is written | once | twice, in two files | once |

**A.** Follows `rec_espn__player_day_residuals` (#81) and
`rec_fantasy__category_wins_by_group` (#94): dbt can unit-test a model and cannot
unit-test a singular test, so the rule goes in a model and the test selects from it.

**B.** The smallest diff: two more join conditions in each file. It loses because nothing
automated could then catch the mistake this issue is about. On the real season one
league-season has rosters, so a join that forgot the season returns the same 31
`registered` rows; in CI the register names a league that is not loaded, so the branch
returns nothing whatever it joins on.

**C.** A full outer join to the register inside `rec_espn__matchup_stat_differences`, with
a status such as `stale_register`. It changes that table's grain and vocabulary, which
#99 does not ask for and the requirements rule out.

## Decisions

| ADR | Decision | Status |
|---|---|---|
| [0040](../../adr/0040-a-register-row-names-its-league-and-season-by-the-real-league-id.md) | A register row names its league and season, the league by its real ESPN id | proposed |
| [0041](../../adr/0041-the-registers-own-checks-live-in-a-view.md) | The register's own checks live in a view, one row per register row | proposed |

## Detailed design

### The seed and its YAML

```
league_id,season,matchup_id,team_id,stat_id,expected_difference,cause,evidence
<real league id>,2026,2,3,1,1,official_scoring_change,"William Contreras 2026-04-01, …"
```

- 31 rows, each gaining the same two leading fields. The league id is the one league in
  the real warehouse (`select distinct league_id from intermediate.int_fantasy__league_seasons`
  returns one row), the same value as `LEAGUE_ID` in `ingestion/tests/test_espn.py`.
- `column_types` gains `league_id: varchar` and `season: bigint`. Every model holds
  `league_id` as text; without the type dbt would infer a number and the join would
  compare text with a number.
- Grain and key: one row per (`league_id`, `season`, `matchup_id`, `team_id`, `stat_id`).
- A seed that gains a column needs `dbt seed --full-refresh` on a warehouse that already
  holds the old table (dbt otherwise keeps the old table's columns and DuckDB rejects the
  insert). CI and the isolation gate build from empty and never meet this.

### `rec_espn__matchup_stat_differences.sql`

Two joins change and nothing else:

- in `espn_formula`, the `left join register` adds
  `register.league_id = espn.league_id and register.season = espn.season`;
- in `annotated`, it adds
  `register.league_id = compared.league_id and register.season = compared.season`.

Both stay left joins on a unique key, so neither can add or lose a row. The header's
`registered` entry says the row is the one for this league-season.

### `rec_espn__player_day_residuals.sql`

- The `league_seasons` CTE and its `cross join` go.
- The `left join register` adds `register.league_id = keys.league_id and
  register.season = keys.season`.
- `problem` is `unregistered`, then `wrong_size`, then null.
- The header loses the `ambiguous_register` entry. The YAML's accepted values become
  `[unregistered, wrong_size]`.

### `rec_espn__register_rows.sql` and the two tests

A view (a saved query, run when read; nothing is stored), so the tests judge the register
against the tables as they are now.

```
register                     espn_reconciliation_residuals, one row each
league_seasons               int_fantasy__league_seasons where platform = 'espn'
espn_matchups                distinct (league_id, season, matchup_id) of
                             stg_espn__matchup_category_results
differences                  rec_espn__matchup_stat_differences

register
  inner join league_seasons on (league_id, season)
  left join espn_matchups on (league_id, season, matchup_id)
  left join differences   on (league_id, season, matchup_id,
                              team_id = fantasy_team_id, stat_id = stat_key)

reconciliation_status = differences.status
problem:
    'matchup_absent'     no espn_matchups row
    'explains_nothing'   reconciliation_status is null,
                         or not in ('registered', 'unverified')
    null                 otherwise
```

This is today's rule with the full key. `matchup_absent` is what
`rec_espn__register_matchups_exist` returns now; `explains_nothing` is the second branch
of `fct_matchup_scores_match_espn`.

The inner join is what keeps the view inside the tenant-isolation rule. The gate
(`scripts/check_tenant_isolation.py`) counts, in each single build, the rows of every
league-scoped relation that belong to another league, and fails on any. A view with a row
per register row would hold the real league's 31 rows in every fixture build. So the view
holds only league-seasons that are loaded, and a register row about one that is not is
reported straight from the seed by the warning test, which the gate does not read
(seeds are in a schema it does not scan).

Three consequences, all intended:

- A row about a past season that has matchups and no rosters is `explains_nothing`: that
  season is not compared (ADR 0026), so no reconciliation row can be `registered`.
- A row whose league-season is loaded and whose matchup ESPN does not have is
  `matchup_absent`, a warning: a mistyped matchup.
- A row whose league-season is not loaded has no view row and is warned on as
  `league_season_not_loaded`. That is every row in CI, and on the real warehouse it is a
  mistyped league or season.

Columns keep the seed's names (`team_id`, `stat_id`). The view is tested unique on the
five-column key, and `problem` for its accepted values (`accepted_values` passes a null).

`fct_matchup_scores_match_espn.sql`: the first branch gains `league_id` and `season` in
its select list and is otherwise as it is. The second becomes

```sql
select 'register row explains nothing' as finding,
       league_id, season, matchup_id, team_id, stat_id,
       coalesce(reconciliation_status, 'no such side or stat') as status
from rec_espn__register_rows
where problem = 'explains_nothing'
```

`rec_espn__register_matchups_exist.sql`, still `severity='warn'`, is a union of two
selects with the same columns (`finding` and the five key columns): the seed's rows with
no `int_fantasy__league_seasons` row of platform `espn` for their league and season, as
`league_season_not_loaded`; and the view's rows where `problem = 'matchup_absent'`, as
`matchup_absent`. The first is an anti-join on two columns of the seed and is the one
piece of the rule outside the view; the probe in the last task exercises it.

### Unit tests

In `_rec_espn__models.yml`. Every register row given carries `league_id` (text, as
`"1"`) and `season`.

- `matchup_stat_differences_assign_every_status` and
  `player_day_residuals_judge_each_key_against_the_register`: their register rows gain
  `league_id: "1", season: 2026`; nothing else changes (R5.4).
- `matchup_stat_differences_keep_each_league_seasons_register_apart` (R5.1). Rules: AB,
  H, AVG = H / AB. Three league-seasons with rosters, each with matchup 7, team 2,
  ESPN's H 10, AB 40, AVG 0.25, and our AB 40.

  | League-season | Our H / AVG | Register row for H | H | AVG |
  |---|---|---|---|---|
  | 1 / 2026 | 11 / 0.275 | +1 | `registered` | `explained_by_component` |
  | 1 / 2027 | 11 / 0.275 | none | `unexplained` | `unexplained` |
  | 2 / 2026 | 12 / 0.3 | +2 | `registered` | `explained_by_component` |

  A join without the season makes 1 / 2027 `registered`. A join without the league gives
  each 2026 side two register rows, so the output has duplicate keys and a wrong status.
  The AVG column catches either mistake in the `espn_formula` join alone.
- `player_day_residuals_keep_each_league_seasons_register_apart` (R5.2), in place of the
  removed test: a difference of 1 on matchup 1, team 1, stat 1 in each of the three;
  register rows of 1 for 1 / 2026 and 2 for 2 / 2026. Expected: null, `unregistered`,
  `wrong_size`.
- `register_rows_are_judged_in_their_own_league_season` (R5.3), seven register rows.
  Loaded: 1 / 2026, 1 / 2027 and 2 / 2026.

  | Register row | ESPN has the matchup there | Status at the full key | `problem` |
  |---|---|---|---|
  | 1 / 2026, matchup 1 | yes | `registered` | null |
  | 1 / 2026, matchup 2 | yes | `unverified` | null |
  | 1 / 2026, matchup 3 | yes | `match` | `explains_nothing` |
  | 1 / 2026, matchup 4, a stat ESPN lacks | yes | none | `explains_nothing` |
  | 1 / 2027, matchup 1 | yes | `match` there; `registered` in 1 / 2026 | `explains_nothing` |
  | 2 / 2026, matchup 5 | no; league 1 / 2026 has a matchup 5 | none | `matchup_absent` |
  | 3 / 2026, matchup 1; league 3 is not loaded | — | — | no row |

### Documents

- The seed's YAML description: the five-column key, one league-season per row, kept by
  hand with evidence on every row.
- `AGENTS.md`, project shape: "`dbt/seeds/` — the lookup seeds are generated by
  `scripts/make_espn_seeds.py` and never hand-edited. `espn_reconciliation_residuals.csv`
  is the exception: a register kept by hand, each row naming its league and season and
  carrying its evidence."
- ADR 0032's follow-up is met; that ADR is not edited. `docs/design/` is not edited.

## Test strategy

| Requirement | Test | Catches |
|---|---|---|
| R1.1–R1.3 | the real build; `git diff --word-diff` of the seed | a row that lost a field or changed a value |
| R1.2 | the real build's 31 `registered` | a league id read as a number, which joins nothing |
| R1.4 | `not_null` on both columns; five-column uniqueness | a row with no league; the same residual entered twice |
| R2.1, R2.2 | R5.1's unit test | a join missing the league or the season, in either place |
| R2.3, R3.1 | R5.2's unit test, and the existing five-case one | the same in the view; a leftover alarm |
| R2.4 | `except` both ways against copies taken before the build, real season | any moved value |
| R3.2, R3.3 | `git grep -c ambiguous_register -- dbt` returns nothing | a leftover branch, value or sentence |
| R4.1, R4.2 | R5.3's unit test; uniqueness and accepted values on the view | a row satisfied by another league-season's residual; a stale row passing |
| R4.1 | the isolation gate | a view row of a league that is not loaded |
| R4.3–R4.5 | the real build (0 rows each); CI (31 warned rows); the probe below | a test that no longer selects what the view marks |
| R6 | review of the diff | — |
| Expected values | the last task | numbers that moved |

Tests come before the code they test: R5.1 and R5.2 are written against the present
models and seen to fail for the stated reason (1 / 2027 `registered`; duplicate keys;
`ambiguous_register`) before a join is touched.

In CI no register row applies to a fixture league, so there every join to the register
returns nothing and the unit tests are the only thing that exercises them. On the real
season the joins are exercised, but only in the direction "nothing was lost".

**The probe.** Neither build has an `explains_nothing` row, and the unit test reaches the
view, not the two test files that read it. So the last task shows once that they are
wired: in a scratch copy of the repo's seed, not committed, it adds a row for the fixture
league (111111, 2026, matchup 1, a team of that matchup, stat 9999, which ESPN does not
have) and one for a league that is not loaded, and builds CI.
`fct_matchup_scores_match_espn` must fail with exactly the first row, and the warning
must grow from 31 to 32. The seed is then restored and `git status` is clean.

**CI `PASS` count.** 641 now. Added: the view (1), its uniqueness and accepted-values
tests (2), two `not_null` tests on the seed (2), two more unit tests (R5.1, R5.3; R5.2
replaces one) (2). Expected 648, `WARN=3`. Recounted in the first task, as in #81.

## Risks

- A real build is run without refreshing the seed — likely once — dbt fails loudly on the
  column mismatch; the tasks and the PR say to run `dbt seed --full-refresh`.
- The register is read as applying to CI — low — in CI all 31 rows warn as
  `league_season_not_loaded` (28 warn today), which is the existing warning with three
  more rows and a reason.
- ESPN gives a league a new id in a later season — not seen: one id across nine seasons,
  2018 to 2026 — a row would then be warned on as not loaded and its residual `unexplained`,
  which fails the build and says where.
- A second league's owner would not want its id in a public file — possible later — the
  decision is recorded in ADR 0040 with that as its condition to revisit.
- The warning in CI now never checks a register row at all (it checked 3 against
  `unverified` sides, which proved nothing) — certain — accepted: the fixtures are not
  the league the register describes.

## Open questions

- **The exact CI `PASS` count** depends on what else merges first; 648 is counted from
  `263923d`.
- **Whether the three CI rows that lose `registered_difference` appear in the isolation
  fixture's four league-seasons too** was not measured. It does not matter to the gate:
  after this change none carries one, in a combined build or a single one.

## Review log

| Source | Finding | Resolution |
|---|---|---|
| design-review | F1 (P0): a view with a row per register row holds the real league's 31 rows in every fixture build, and the isolation gate counts a single build's rows of another league as leaks | Confirmed in `check_tenant_isolation.py` (the `strays` count). Changed: the view holds only register rows of a loaded league-season (R4.1); rows of one that is not loaded are warned on from the seed (R4.4); a seventh unit-test case. Not changed: the gate. The reviewer suggested exempting the view there; a rule that every model must pass is worth more than one view's convenience |
| design-review | F2 (P2): no build has an `explains_nothing` row, so nothing shows that the singular tests still select what the view marks | Changed: a one-off probe in the last task, with its expected result in the expected values |

## Amendments

