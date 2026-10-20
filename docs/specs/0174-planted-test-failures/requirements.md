# A data test the CI fixtures cannot exercise is shown to fail on a planted row — requirements

Issue: #174 · Tier: M · Status: draft

## Problem

No row of the CI fixture warehouse is verified (design.md, C1). A fixture date counts as
complete only when every game played on it has a boxscore, and the fixtures hold 3 of the
38 games of their three dates (C2). So every data test restricted to verified rows passes
on zero rows in CI: the `not_null` tests on `fct_matchup_category_scores.result` and on
`fct_matchup_results.winner`, `fct_matchup_category_scores_values_have_a_side`, and
`int_fantasy__started_player_days_played_matches_input_status` (C3). The fixtures hold no
playoff matchup either. So `fct_matchup_results_home_is_the_better_seed` (#159) checks
nothing in CI, and neither do the two ESPN reconciliation tests, whose every CI row is
`unverified` (C4).

Reviews of #172 and #173 flagged this twice in a row. Each time the test was shown to
fail by hand, on a copy of the CI warehouse with a row planted, and the plants were
recorded on the issue (C5). Nothing repeats those checks, so a later change could leave
such a test unable to fail with every gate still green.

The gap is wider than the issue names. 35 of 412 generic tests read zero CI rows (C3):
- 4 because their `where` admits no CI row;
- 31 because their whole relation is empty in CI.

The owner chose (2026-10-20) a planting harness over a larger fixture (ADR 0087), and a
rule that finds such tests by itself (ADR 0088).

## Goals

- Every data test that can't fail in CI today, and that this project's logic rests on,
  is shown to fail on every CI run: on a copy of the CI warehouse with a planted row.
  Where a plant marks the edge of a rule, it is also shown to pass.
- A new generic test whose `where` admits no CI row fails the gates until it has a plant.
  A relation that becomes empty in CI fails them until someone records why.
- A plant that stops planting anything, or a register entry whose test or relation is
  gone, fails the gates. The register cannot rot quietly.

## No-gos

Work that drifts into any of these is escalated, not done.

- No fixture data changes. No new boxscore, roster, matchup or endpoint is added to
  `fixtures/landing` or `fixtures/landing_multi`. A real matchup period in the fixtures
  was the alternative not chosen (ADR 0087). The missing `matchup_days` endpoint is #178.
- No model and no existing test changes. The harness only reads what the tests already
  are.
- No plant for a test whose relation is empty in CI: that relation gets an exemption with
  its reason instead (ADR 0088).
- No detection for singular tests. Their input can't be measured from the manifest. They
  get plants by the convention in R5.
- DuckDB only. The plants are DuckDB SQL against the CI warehouse; BigQuery is not
  touched.
- The user-level build skill is not edited. The convention is written into `AGENTS.md`.

## Rabbit holes

- **Planting into a view.** A view can't take an INSERT or UPDATE, and many staging and
  reconciliation relations are views. → The plant first replaces the view, in the copy
  only, with a table of the same name and rows (`materialize:`). Prototyped on
  `stg_espn__teams` (C7).
- **A view stores the catalog it was built in** (`compare_warehouses.py`, header). A copy
  under another name would break every view. → Each copy is a file named `ci.duckdb` in
  its own temporary directory, so the catalog is still `ci`.
- **Running the test faithfully.** Re-implementing dbt's `where`, severity and failure
  count would drift from dbt. → The harness runs the real `dbt test --select <test>`
  in-process (`dbtRunner`): 1.3 s a plant once warm (C6).
- **A plant written against fixture rows that later change.** → Every statement of a plant
  must change at least one row, or the plant fails by name (R2.3). C6's first attempt
  changed 0 rows, because every fixture side is below the 30-out minimum.

## Requirements

### R1. The register

- R1.1 THE SYSTEM SHALL keep the plants in `dbt/plants/`, one YAML file per test, named
  `<test name>.yml`. Each file holds a list of plants, and each plant has:
  - a `name`;
  - a `why`: the failure the plant stands for;
  - an optional `materialize`: views to turn into tables first;
  - `sql`: one or more entries, each exactly one INSERT, UPDATE or DELETE statement;
  - `expect`: `pass`, or a status (`fail` or `warn`) with the exact number of failures.
- R1.2 THE SYSTEM SHALL keep the relations that are empty in CI in
  `dbt/plants/_empty_in_ci.yml`. Each entry names a relation (`schema.name`), the reason
  it is empty in CI, and an issue or ADR link that the reason rests on.
- R1.3 IF a plant file names no test in the manifest, or an exemption names a relation
  that is not empty in CI, THEN THE SYSTEM SHALL fail, naming the file or the relation.
- R1.4 IF a plant file or entry is missing a required key, has an unknown key, or an
  `sql` entry that is not exactly one INSERT, UPDATE or DELETE statement as DuckDB parses
  it, THEN THE SYSTEM SHALL fail before running anything, naming the file and the plant.

### R2. A plant is run

- R2.1 WHEN a plant runs THE SYSTEM SHALL copy the built CI warehouse to a new temporary
  directory, as `ci.duckdb`, and never open `dbt/ci.duckdb` for writing.
- R2.2 THE SYSTEM SHALL turn each `materialize` view into a table of the same schema, name
  and rows, then run the plant's statements in order.
- R2.3 IF a plant statement changes no row THEN THE SYSTEM SHALL fail that plant, naming
  the statement, and not run its test. An UPDATE changes a row only when some row of its
  table differs afterwards, not merely when the UPDATE matched one.
- R2.4 THE SYSTEM SHALL run the plant's test with dbt (`dbt test --select <test>
  --target ci --vars '{anonymize: true}'`) against the copy, and compare dbt's status and
  failure count with `expect`.
- R2.5 IF a plant's result differs from its `expect` THEN THE SYSTEM SHALL fail, printing
  the test, the plant, what was expected and what dbt gave.
- R2.6 THE SYSTEM SHALL run every plant, print each result, and exit 1 if any failed.

### R3. Tests that read zero CI rows are found

- R3.1 WHEN it runs THE SYSTEM SHALL count, for every generic test in the manifest that is
  attached to a model or seed, the rows of that relation in the CI warehouse, and the rows
  its `where` admits.
- R3.2 IF a generic test's relation has rows but its `where` admits none, AND the test has
  no plant file, THEN THE SYSTEM SHALL fail, naming the test.
- R3.3 IF a generic test's relation has no rows AND the relation has no exemption, THEN
  THE SYSTEM SHALL fail, naming the relation and its tests.
- R3.4 THE SYSTEM SHALL print how many generic tests it counted, how many read zero rows,
  and for how many of those a plant or an exemption accounts.

### R4. The first register

- R4.1 THE SYSTEM SHALL have plants for the 4 generic tests whose `where` admits no CI row
  (C3): each fails on a planted verified row that breaks it.
- R4.2 THE SYSTEM SHALL have plants for the singular tests the issue and the last two
  builds proved by hand (C5):
  - `fct_matchup_results_home_is_the_better_seed`;
  - `fct_matchup_scores_match_espn`;
  - `fct_matchup_results_match_espn`;
  - `stg_espn__league_settings_tie_rules_are_understood`;
  - `stg_espn__league_settings_qualification_is_understood`.
- R4.3 THE SYSTEM SHALL plant each branch of a singular test that unions several checks
  (both ESPN reconciliation tests have two).
- R4.4 THE SYSTEM SHALL carry, for `fct_matchup_category_scores_values_have_a_side`, the
  five cases recorded on #173 (three fail, two pass). Each guard also gets a case it must
  let through:
  - for `fct_matchup_results_home_is_the_better_seed`, a playoff matchup whose home side
    is the better seed;
  - for `stg_espn__league_settings_tie_rules_are_understood`, an unknown rule in a
    league-season without rosters.
- R4.5 THE SYSTEM SHALL exempt the 7 relations empty in CI (C8), each with its reason and
  link.

### R5. The harness is part of the gates and of how work is done

- R5.1 THE SYSTEM SHALL run the harness (`scripts/check_plants.py --db dbt/ci.duckdb`) in
  `.agentic/gates` and in `.github/workflows/ci.yml`, after the dbt build and the example
  check, in the same order in both.
- R5.2 THE SYSTEM SHALL state in `AGENTS.md` that a data test whose failing case the CI
  fixtures can't hold gets a plant in `dbt/plants/`. The plants that prove a new test can
  fail are committed there, not run by hand.
- R5.3 THE SYSTEM SHALL keep the harness's own logic under pytest: the register's
  validation, the classification of R3, and the comparison of R2.4. These run on small
  synthetic manifests and warehouses, not on the fixture build.

## Expected values

Counted on a fresh CI build of `main` at ac0e2ac on 2026-10-20; recounted at build time.
The harness runs on the CI warehouse only: it has no real-season run.

| Check | Expected | How to verify |
|---|---|---|
| Generic tests counted (R3.4) | 412 | the harness's summary |
| Generic tests over zero CI rows | 35: 4 by their `where`, 31 on empty relations | the summary |
| Accounted for | 35 of 35: 4 by plant files, 31 by the 7 exemptions | the summary |
| Plant files (R4.1–R4.4) | 9: the 4 generic and the 5 singular tests | `ls dbt/plants` |
| Plants | 24, each `expect` met: 20 `fail` plants give exactly their stated failure count, and 4 `pass` plants pass (2 of `values_have_a_side`, 1 of the seed test, 1 of the tie rules) | the harness's output |
| Exemptions (R4.5) | 7: `stg_espn__matchup_days` and `stg_espn__matchup_player_lines` (#178); `rec_espn__register_rows` (by design: the register names real leagues only); `rec_espn__player_day_residuals`, `rec_espn__winner_differences`, `rec_fantasy__category_wins_added` and `rec_fantasy__category_wins_by_group` (no verified side in CI, ADR 0087) | `_empty_in_ci.yml` |
| Run time of the harness step | under 90 s on the owner's machine | timed in the gates |
| Each check shown to fail | the detector's two failures, each register validation, a statement that changes nothing, and a plant whose `expect` is wrong | the build's *Tests shown to fail* table |
| `dbt/ci.duckdb` | byte-identical before and after the harness | `sha256sum` before and after |
