# Front Office — Sub-project 2: intermediate layer and marts

Approved 2026-09-26. Kept as written except for notes marked **Resolved**, which record
what the data said once a milestone actually ran. The original plan's wording is left
alone even where reality corrected it — the corrections are the interesting part.

## Progress

Tracked in the [Sub-project 2 milestone](https://github.com/nick-socci/front-office/milestone/1),
not here. This document is the design and the record of what it got wrong; a status
column in it would be a second place to keep the same facts current, and the second
place is always the stale one.

## Review amendments — 2026-09-27

The [code review](../reviews/2026-09-27-code-review.md) is the record of open defects,
coverage gaps and recommended remediation. These amendments supersede conflicting
execution guidance below while preserving the original plan as history.

- Milestone 8 implementation is merged in PR #14 (`8484d06`). Its interface models are
  tables to enforce constraints, the crosswalk is ephemeral, and MLB day aggregation
  uses a full outer join. Local fixture validation passed with one ID-map warning;
  full-season reconciliation remains unproven.
- Step 0's October 5 run needs `backfill mlb --season 2026 --refresh` under the current
  implementation. An ordinary rerun skips already-landed games older than seven days.
  Snapshot mode also refetches recent games, so it is not a no-op for every landed game.
- **Resequencing decision, 2026-09-27:** before accepting milestone 9, audit historical
  capture finality/completeness, repair the reconciliation test and add intermediate
  expected-output tests. General lifecycle fixes may follow under the conditions in the
  [reviewer follow-up](../reviews/2026-09-27-reviewer-follow-up.md); identity fixes must
  precede any second league/season load.
- **Design decision taken 2026-09-27:** milestone 9 production marts use the intermediate interfaces, including
  `int_fantasy__categories.is_lower_better`; source-specific reconciliation can use ESPN
  staging. Begin with full rebuilds unless incremental correctness is demonstrated.
- Milestone 11's “never worse” assertion applies only to the defined scalar objective,
  not every category or actual matchup outcome. Label the output hindsight opportunity.
- End-to-end validation should create a separate warehouse from preserved landed data.
  Deleting the existing warehouse and requiring a live historical refetch is unnecessary
  and contradicts the raw-data recovery design.

## Input completeness per player-day — design, 2026-09-28 ([#25](https://github.com/nick-socci/front-office/issues/25))

**The problem.** `int_fantasy__started_player_days` left-joins MLB production, so a
started player with no stats that day becomes a row of zeroes with `played = false`.
That is right when he didn't play. It is wrong, and indistinguishable, when his game's
boxscore never landed or his ESPN id didn't resolve to an MLBAM id. A missing input
would score as a real zero.

**The status.** Each started player-day gets `input_status`, decided in this order:

| `input_status` | Rule | 2026 |
|---|---|---|
| `unresolved_player` | `mlbam_player_id` is null | 0 |
| `played` | he appears in `int_mlb__player_game_days` on that date | 21,120 |
| `missing_boxscore` | the date has at least one played game whose boxscore is not loaded | 0 |
| `verified_off` | otherwise: every played game that date is loaded (or there were none) | 17,545 |

`verified_off` covers both a team off day and a player his manager didn't use. Both
are real zeroes for fantasy scoring, so the design does not separate them. 641 of the
17,545 fall on dates with no MLB games at all, such as the All-Star break.

**Why the rule needs no player-to-team mapping.** If every played game on a date is
loaded, then a resolved player who appears in none of them did not play. There is no
game he could be missing from. His team only matters on a date with a missing
boxscore, and there the rule is conservative: every non-appearing player that day is
flagged. That over-flags, which is the safe direction. The audit gates missing
boxscores to zero before data is trusted, so in practice the flag should never fire.

**Rejected: ESPN's `proTeamId`,** which #25 originally proposed. A roster snapshot
fetched after the season reports each player's *current* team for every historical
period: no player has more than one `proTeamId` across 2026's 180 snapshots, despite
trades during the season. On days players actually played, the mapped team matched
their real MLB team only 95.8% of the time (24,095 of 25,163), and the misses are
traded players' pre-trade days. If per-player precision is ever needed, the source is
MLB's transactions endpoint, not ESPN. Nothing needs it now.

**What "played game" means.** The not-played set moves to a seed, `mlb_game_states`
(`detailed_state`, `is_played`). `stg_mlb__games` gets `is_played` from it. A test fails
the build on any `detailed_state` the seed doesn't list, so a new MLB state (a forfeit,
say) forces a decision rather than defaulting either way. It matches ingestion's
`NOT_PLAYED` set (#36): 2026 has Final, Completed Early, Postponed and Cancelled.

**Models.**
- `int_mlb__game_dates`: one row per `official_date` with `played_games`,
  `loaded_games` (played games that have batting logs; every played game has batters
  on both sides) and `is_complete`. A table, because it is small and joined per
  roster day.
- `int_fantasy__started_player_days`: adds `input_status` and keeps `played`, with a
  test that `played = (input_status = 'played')`.
- Marts (milestone 9) report non-verified player-days per matchup side next to the
  scores. They never fold them into zeroes. This is the #10 gate "missing or
  unresolved inputs reported separately from verified zeros".

**Data tests.**
- `accepted_values` on `input_status`.
- A singular test that no batting or pitching log belongs to a game with
  `is_played = false`. The audit catches the same thing on landed files (#36); this
  catches it in the warehouse.
- A warn-level test that `missing_boxscore` and `unresolved_player` counts are zero.
  It is a warning, not an error, because the CI fixtures load 2 of 24 scheduled games
  on purpose, so every fixture date is incomplete. The status logic itself is proven
  by the unit tests below, not by fixture counts.

**Unit tests** (small synthetic dbt unit tests, not bigger fixtures):
- `int_mlb__player_game_days`:
  - a doubleheader is summed into one player-day;
  - batting and pitching on one day are one row with both sides populated.
- `int_fantasy__started_player_days`, one test per status:
  - played;
  - `verified_off` on a complete date;
  - `verified_off` on a date with no games;
  - `missing_boxscore` on an incomplete date;
  - `unresolved_player`, which takes precedence over `missing_boxscore`.
- Component coverage: every column the 17 scored categories read passes through
  unchanged. That includes the ratio categories' numerators and denominators: H/AB
  (AVG); ER and outs (ERA); hits allowed, walks and outs (WHIP); K and outs (K/9); saves
  plus holds (SVHD).

**Resolved, 2026-09-30 (implementation).** Built as designed. The 2026 warehouse
reproduces the table above exactly: 21,120 `played`, 17,545 `verified_off` (641 on
no-game dates), and all 184 game dates complete. One unit test was added beyond the
list: `int_mlb__game_dates` itself (a cancelled game without a boxscore leaves its date
complete, and a played game without one does not), since the status tests stub that
model and would not otherwise exercise it. Three deliberate breaks each failed a unit
test: checking `missing_boxscore` before `unresolved_player`, feeding pitcher walks from
batter walks, and counting a cancelled game as one to load.

**Resolved, 2026-09-30 (PR #43 review).** The table's order was wrong. Checking `played`
before `missing_boxscore` labels half a doubleheader as `played`: a player in game 1
with game 2's boxscore missing has partial totals that look complete. Now an incomplete
date makes every resolved player `missing_boxscore`, and the order is
`unresolved_player`, `missing_boxscore`, `played`, `verified_off`. The `played` boolean
keeps its meaning (he appears in what is loaded), so the consistency test
`played = (input_status = 'played')` applies only to the two verified statuses. The
same review found that `stg_mlb__games` demoted only `Postponed` in its same-fetch
tie-break while ingestion demotes all of `NOT_PLAYED`. A cancelled entry and its played
makeup could tie, and DuckDB then picks by input order. The tie-break now reads the
seed's `is_played`. 2026 counts are unchanged by both fixes. **Before daily runs in 2027:** the seed lists only end-of-game states. An
in-season schedule carries `Scheduled`, `In Progress` and so on, and those stop the
build until the seed classifies them. That is intended, but whether a date with an
unfinished game counts as incomplete needs deciding with the ingestion-hardening
milestone.

**Out of scope, noted.** Resumed games are attributed to their `official_date`. 2026
has one, 824912 (official date 2026-06-16). Whether ESPN credits the resume date is a
milestone 9 reconciliation question ("slot attribution checked for ... suspended
games"), not an input-status one.

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

> **Resolved, 2026-10-01: ESPN credits stats by slot role.** The review asked which
> production the platform counts for each role, since started player-days carried a
> player's whole day. A full-season probe answered it. Summing every started player's
> batting and pitching leaves 0–18 of 286 matchup sides off ESPN per stat. Crediting
> batting only from hitter slots and pitching only from P/SP/RP brings K, outs, GS, BB,
> SO, R, HR, SB, W, L and SV to exact on every side. What remains is 14 sides, nearly
> all ±1 H/ER: official scoring changes that ESPN never applied, plus 3 sides still to
> explain. `slot_role` is now a column of the `espn_lineup_slots` seed, and
> `int_fantasy__started_player_days` carries credited production only. A player's full
> day stays in `int_mlb__player_game_days`. Those residuals get an explicit register in
> the reconciliation, and are never absorbed by a tolerance.

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
