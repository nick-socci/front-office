# Front Office — Sub-project 2: intermediate layer and marts

Approved 2026-09-26. Kept as written except for the progress table below and notes marked
**Resolved**, which record what the data said once a milestone actually ran. The original
plan's wording is left alone even where reality corrected it — the corrections are the
interesting part.

## Progress

| # | Milestone | State | PR |
|---|---|---|---|
| 7 | Matchup periods, slot eligibility, lineup shape | Merged 2026-09-26 | [#7](https://github.com/nick-socci/front-office/pull/7) |
| 8 | Platform-neutral intermediate layer | In progress | — |
| 9 | `fct_matchup_category_scores`: the reconciliation | Not started | — |
| 10 | Player value and transaction impact | Not started | — |
| 11 | `fct_lineup_decisions`: points left on the bench | Not started | — |
| 12 | Documentation, lint and the record | Not started | — |

Step 0 (finish the 2026 MLB backfill after 2026-09-27, settle-window refresh around
2026-10-05, NAS backup) is **outstanding** and must run before milestone 9.

## Context

Sub-project 1 is complete and merged (PRs 1–6, `main` green): ingestion → raw JSON →
`raw.api_responses` → 12 dbt staging models → CI. The definition-of-done query works.
That layer answers *what happened*; it cannot yet answer *how well the team was managed*,
which is the reason the project exists.

This phase builds the two layers above staging: a **platform-neutral intermediate layer**
(the seam that lets a Yahoo or Sleeper league slot in without rewriting marts) and the
**marts** the roadmap promises. Scope is marts only — the BigQuery migration, Dagster,
Cloud Run and the Streamlit dashboard stay in sub-project 3, so this phase stays local on
DuckDB and iterates fast.

### The finding that shapes the design

A probe run during planning recomputed a full matchup from the ground up — started roster
entries for scoring periods 69–75, resolved to MLBAM ids, joined to real MLB game logs —
and compared it to ESPN's own `cumulativeScore.scoreByStat`:

| | AB | H | HR | R | RBI | SB | IP (outs) | ER | K | W | SV |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Recomputed | 214 | 62 | 7 | 32 | 37 | 2 | 136 | 28 | 46 | 2 | 5 |
| ESPN | 214 | 62 | 7 | 32 | 37 | 2 | 136 | 28 | 46 | 2 | 5 |

Every count category matches exactly, and the rates fall out of the components
(ERA 5.55882 = 28×27/136, WHIP 1.45588 = 66/(136/3), K/9 = 46×27/136). **The mart layer can
therefore be proven correct against the platform's own numbers rather than merely tested for
plausibility.** That reconciliation is the flagship test of this phase and the strongest
single claim the project can make.

### Three things staging is missing, found while probing

1. **Matchup period → scoring period.** Not staged anywhere. It is available:
   `schedule[*].home.pointsByScoringPeriod` keys give the days in each matchup
   (period 10 = days 69–75; `matchupPeriodLength: 1`, `periodTypeId: 2`, 24 periods).
2. **`eligibleSlots`.** Present in every roster entry payload (e.g. `[3,7,19,11,12,16,17]`)
   and never staged. Without it, "who could have started instead" is guesswork.
3. **`rosterSettings.lineupSlotCounts`** — the lineup shape (1 C, 1 each infield, 3 OF,
   1 UTIL, 4 SP, 2 RP, 3 P, 5 BE, 4 IL). Needed for the same reason.

Also noted: `stg_espn__matchups` has 143 rows where the payload has 145 entries. Confirm
the two dropped rows are byes/null-team sides before building on the model.

> **Resolved in milestone 7.** They are playoff byes: the `away` side is an empty object
> and the home team advances without playing. The filter is now documented in the model.
>
> Milestone 7 also killed an assumption this plan made implicitly: matchup periods are
> **not** a uniform length. Period 1 covers 12 scoring periods, period 15 covers 14 (the
> All-Star break folded in), the rest cover 7. Nothing downstream may assume a week.
> `stg_espn__lineup_slot_limits` additionally turned up a lineup slot 18 that ESPN
> enumerates, espn-api does not name, and no league here uses.

## Working style (unchanged, carried from sub-project 1)

Explain the new dbt concept **before** writing code. Tests first. Small readable commits.
One PR per milestone, and **stop at the PR for review** — do not start the next milestone
until the previous PR is merged. Explain unfamiliar command output rather than silently
fixing it. Python needs no hand-holding.

## Naming

Marts use `fct_` / `dim_` rather than the `mart_` prefix the README roadmap currently
advertises; it is the convention real dbt projects use and reads better to an AE reviewer.
The README roadmap wording gets updated in the last milestone.

## Step 0 — finish the 2026 backfill (no PR; run before milestone 9)

The fantasy season ended at scoring period 180 = **2026-09-20**, so the marts are unaffected
by what follows and milestones 7–8 can start immediately. But MLB's regular season runs
through 2026-09-27 and 28 games are still unplayed (2,402 of 2,430 Final).

- After 2026-09-27: re-run `backfill mlb --season 2026` (snapshot mode makes it a no-op for
  everything already landed) and `load`.
- Around 2026-10-05: re-run once more so the 7-day settle window closes on the last games.
- Re-run the NAS backup (`rsync -a` + `sha256sum` manifest, verify count and size).

## Milestone 7 — the three missing staging models

**New dbt concept:** none — this is deliberately a small, familiar milestone that closes the
gaps above before anything is built on them.

**Files:** `dbt/models/staging/espn/stg_espn__matchup_periods.sql` ·
`stg_espn__roster_entry_slots.sql` · `stg_espn__lineup_slot_limits.sql` ·
`_espn__models.yml` · `dbt/tests/…` · fixture regeneration in `scripts/make_fixtures.py`

- `stg_espn__matchup_periods`: one row per (matchup_period, scoring_period), unnested from
  `pointsByScoringPeriod` keys. Reuse `fo_espn_latest('matchups')`.
- `stg_espn__roster_entry_slots`: one row per (scoring_period, team, player, eligible_slot),
  joined to the `espn_lineup_slots` seed. Follow the `header`-CTE-before-`unnest` pattern
  from `stg_espn__roster_entries` — the payload is 2.3 MB per period and projecting it away
  first is what keeps this from exhausting memory.
- `stg_espn__lineup_slot_limits`: one row per slot with its count, from
  `settings.rosterSettings.lineupSlotCounts`.
- Tests: every scoring period 1–180 belongs to exactly one matchup period; periods within a
  matchup are consecutive; slot ids resolve against the seed; slot limits sum to the roster
  size implied by `stg_espn__teams`.

**Verify:** `dbt build` clean on the full season; `dbt build --target ci` on regenerated
fixtures; CI green on PR 7.

## Milestone 8 — the platform-neutral intermediate layer

**New dbt concepts:** intermediate models and the staging/intermediate/marts split ·
**ephemeral** materialization · **model contracts** (`enforced: true`) as the seam's
guarantee.

**Files:** `dbt/models/intermediate/fantasy/int_fantasy__{teams,categories,matchup_periods,roster_days}.sql` ·
`dbt/models/intermediate/mlb/int_mlb__player_game_days.sql` ·
`dbt/models/intermediate/int_fantasy__started_player_days.sql` ·
`dbt/models/intermediate/_intermediate__models.yml`

- Every `int_fantasy__*` model carries `platform` ('espn'), `league_id`, `season` and uses
  neutral names (`roster_slot`, `is_starting_slot`) rather than ESPN's. Nothing above this
  layer references an ESPN model. This is the Yahoo/Sleeper seam actually being built rather
  than asserted.
- **Contracts** go on the four `int_fantasy__*` interface models: a second platform must
  produce these exact columns and types, and dbt enforces it at build time.
- `int_mlb__player_game_days`: batting and pitching unioned to one row per
  (mlbam_player_id, official_date), **summing doubleheaders**. A player with two games on a
  date contributed both to his fantasy team that day — the probe confirmed ESPN counts them
  the same way.
- `int_fantasy__started_player_days`: the attribution grain. Started entries only
  (`is_starting_slot`, excluding BE and IL) × that day's MLB production, resolved by MLBAM id
  with the unambiguous-name fallback already in `docs/examples/roster_day_query.sql`.
- Tests: no roster-day is attributed twice; started-day count reconciles to
  `stg_espn__roster_entries` (38,665 started of 55,653); a started player with no MLB game
  that day yields a row with zeroes, not a missing row.

**Verify:** `dbt build` clean; the ephemeral models compile into their parents (inspect
`target/compiled`); a contract violation is demonstrated deliberately once, so the failure
mode is understood; CI green on PR 8.

## Milestone 9 — `fct_matchup_category_scores`: the reconciliation

**New dbt concepts:** **incremental** materialization · rules-driven (not hardcoded) SQL ·
float-tolerance singular tests.

**Files:** `dbt/models/marts/fct_matchup_category_scores.sql` ·
`dbt/models/marts/fct_matchup_results.sql` · `dbt/models/marts/_marts__models.yml` ·
`dbt/tests/fct_matchup_scores_match_espn.sql` ·
`dbt/tests/fct_matchup_winners_match_espn.sql`

- Recompute all 24 stats × 143 matchups × 2 sides from components, aggregating
  `int_fantasy__started_player_days` over each matchup's scoring periods. The category list
  and the lower-is-better flag come from `stg_espn__scoring_categories` — nothing about
  "17 categories" is hardcoded, which is what makes this work for a different league.
- Rates are computed from components at the matchup grain, never averaged from per-game
  rates: AVG = H/AB, ERA = ER×27/outs, WHIP = (H+BB)/(outs/3), K/9 = K×27/outs.
- `fct_matchup_results`: category wins/losses/ties per side, applying `is_reverse`, and the
  derived winner.
- **The flagship tests**: every count category equals ESPN's `score` exactly; every rate is
  within 1e-6; the derived winner equals ESPN's `winner` for all 143 matchups. Any failure
  here is a real modelling bug, not a tolerance problem.
- Incremental on `matchup_period` with a lookback, documented as future-facing: during 2027
  only open periods need rebuilding.

**Verify:** all three reconciliation tests pass on the full season; deliberately break one
component mapping and confirm the test catches it; CI green on PR 9.

## Milestone 10 — player value and transaction impact

**New dbt concepts:** window functions over the roster timeline · `dbt_utils.date_spine` ·
`dim_` vs `fct_` model roles.

**Files:** `dbt/models/marts/dim_players.sql` · `fct_player_season_value.sql` ·
`fct_transaction_impact.sql` · tests

- `dim_players`: one row per player — ESPN id, MLBAM id, name, position, pro team, with the
  crosswalk resolution method recorded (id match vs name fallback) so downstream consumers
  can see how each row was resolved.
- `fct_player_season_value`: per (player, fantasy team) — days started, per-category
  contribution while started, rate categories from components, and a value-over-replacement
  figure. **Replacement level is defined explicitly and documented in the model header**
  (the median production of a rostered-but-benched player at the same primary slot); it is a
  judgement call, so it gets stated rather than buried.
- `fct_transaction_impact`: for each add, that player's production for the team over the rest
  of the season; for each drop, what the dropped player did afterwards. Uses the 737 staged
  transactions and a date spine bounded by the next transaction on the same player.
- Tests: summed per-category contributions across all players on a team equal that team's
  season totals from milestone 9 — the same reconciliation discipline applied one level down.

**Verify:** spot-check two known transactions against the ESPN activity log; CI green on PR 10.

## Milestone 11 — `fct_lineup_decisions`: points left on the bench

**New dbt concept:** a **dbt Python model** (supported by `dbt-duckdb`), used because the
problem genuinely requires it.

**Files:** `dbt/models/marts/int_optimal_lineups.py` · `fct_lineup_decisions.sql` ·
`ingestion/tests/test_optimal_lineup.py` · tests

- Filling a lineup optimally is an assignment problem: 16 starting slots, ~21 rostered
  players, `eligibleSlots` per player per day, `lineupSlotCounts` as capacities. Greedy SQL
  gets it wrong — it double-assigns a player who is eligible at two slots. `scipy.optimize.
  linear_sum_assignment` solves it exactly. The model header states this, and states the
  BigQuery implication: Python models there need Dataproc, so this one mart will either move
  to SQL or stay DuckDB-only, decided in sub-project 3.
- Scoring a player-day for the assignment needs a scalar. Use the sum of per-category
  z-scores across the league's own scored categories, with `is_reverse` inverted, computed
  within that day's started-player population. Documented as a choice, with its weakness
  stated (it treats all 17 categories as equally valuable, which a real H2H manager does not).
- `fct_lineup_decisions`: per team-day and per matchup — actual category totals, optimal
  category totals, the gap, and the single largest missed start.
- Tests: the optimal lineup never exceeds a slot's capacity, never starts an ineligible
  player, never starts the same player twice, and is never worse than the actual lineup.
  Unit-test the solver in pytest against small hand-built cases.

**Verify:** inspect the worst-gap team-day by hand against the ESPN box score; confirm the
solver is exercised in CI on fixtures; CI green on PR 11.

## Milestone 12 — documentation, lint and the record

**New dbt concepts:** `dbt docs generate` and the lineage graph · **exposures** ·
source freshness definitions.

**Files:** `.github/workflows/docs.yml` · `dbt/models/marts/_exposures.yml` ·
`.sqlfluff` · `.github/workflows/ci.yml` · `README.md` · `docs/README.md`

- Publish `dbt docs generate` output to GitHub Pages — the DAG from raw JSON to marts is the
  single most legible artifact this project produces for a reviewer.
- **sqlfluff** with the DuckDB dialect in CI (the spec listed it as roadmap, not scope; this
  is where it lands). Expect a one-off reformatting commit across existing models.
- **Exposures** declaring the future Streamlit dashboard and the example queries, so
  `dbt build --select +exposure:…` works before the dashboard exists.
- **Source freshness** thresholds defined on the raw sources and documented as dormant until
  the 2027 daily schedule exists.
- README: mart table, the reconciliation result stated plainly with its numbers, updated
  roadmap (`fct_`/`dim_` names), refreshed test counts. `docs/README.md` marks sub-project 2
  complete and the progress table above is filled in.

> **Resolved.** This doc was committed at the start of milestone 8 rather than here. It had
> been living in a scratch directory outside the repo — not in git, not backed up, and
> overwritten by each new planning session.

**Verify:** the docs site loads and the DAG renders; `sqlfluff lint` clean; a fresh clone
plus fresh backfill builds every model, test and Python model; CI green on PR 12.

## End-to-end verification

1. `rm -rf data/warehouse.duckdb && front-office backfill mlb --season 2026 && front-office
   backfill espn --season 2026 && front-office backfill idmap && front-office load`
2. `cd dbt && dbt deps && dbt build` — staging, intermediate, marts, the Python model, and
   every test pass on the full season.
3. The three reconciliation tests pass: category scores, rates within 1e-6, and all 143
   matchup winners.
4. `uv run pytest`, `ruff check`, `mypy --strict`, `sqlfluff lint` all clean; CI green on `main`.

## Risks

- **The reconciliation may not hold everywhere.** One matchup reconciled exactly; 143 have not
  been checked. Doubleheaders, in-season position changes, IL activations mid-day and games
  suspended across dates are the likely edge cases. This is the desired outcome of milestone
  9 either way — a failing test that exposes a real rule is worth more than a passing one that
  hides it. Budget rework in milestone 9 specifically.
- **`eligibleSlots` is a daily snapshot**, so eligibility legitimately changes across the
  season. Milestone 11 must use each day's own eligibility, not a season-wide set.
- **The Python model splits the adapter story.** Accepted deliberately and documented, with
  the decision deferred to the BigQuery sub-project rather than pre-empted here.
- **Replacement level and the z-score scalar are judgement calls.** Both are stated in model
  headers rather than presented as objective; a reviewer disagreeing with the definition is
  fine, a reviewer unable to find the definition is not.
- **sqlfluff will churn every existing model.** Keep the reformatting in its own commit so the
  substantive diff in PR 12 stays readable.
