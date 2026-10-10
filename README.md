# Front Office

[![CI](https://github.com/nick-socci/front-office/actions/workflows/ci.yml/badge.svg)](https://github.com/nick-socci/front-office/actions/workflows/ci.yml)

**[Browse the models and their lineage](https://nick-socci.github.io/front-office/)** — the
dbt docs site, rebuilt from fixtures on every change to `main`.

A code-first analytics engineering project: real MLB and ESPN fantasy data, ingested as
raw JSON, transformed with dbt, stored in DuckDB (BigQuery planned), and tested in CI.

It exists because I play in a 17-category head-to-head fantasy baseball league and
wanted to answer questions the ESPN app will not: who was actually on a roster on a
given day, what those players did in real games, and where the value is.

## What it does today

```
MLB Stats API  ─┐
ESPN Fantasy   ─┼─►  raw JSON on disk  ─►  raw.api_responses  ─►  staging  ─►  intermediate  ─►  marts
SFBB id map    ─┘    (landing zone)        (one row per          (shaped       (the project's     (shaped like
                                            API response)         like the      own terms, no      a question)
                                                                  API)          platform's)
                                                                                      └─►  reconciliation
                                                                                           (ours against ESPN's)
```

**Ingestion (Python)** fetches and saves; it never interprets. Each response is written
unchanged, with a metadata sidecar recording the request, then loaded into a single
append-only table. A parsing mistake costs a rebuild, not a re-download of the season.

A response and its sidecar are one *capture*: a directory, `…/fetched_at=<stamp>/`,
holding `payload.json` and `meta.json`, written under a temporary name and published by
a single rename. So a capture is on disk complete or not at all, and one that already
exists is never replaced: a second write to the same place stops the run. One function
decides what counts as a capture, and the fetch logic, the loader and the audit all ask
it. Only one command may write at a time, enforced by a lock the operating system
releases if the process dies. A roster capture's sidecar also records the league's
scoring-period status from its own response, which is what shows a period closed
(ADR 0016).

ESPN's pro schedule is landed as a season-level capture: it has no league and needs no
credentials (ADR 0024). It is what dates scoring periods (ADR 0023): every scheduled game
implies a date for period 1, and the build fails unless they all agree.

**Transformation (dbt)** does everything that requires knowing what the data means:
flattening JSON, deduplicating at the entity grain, and converting to honest units.

| Layer | Models | What it is for |
|---|---|---|
| Staging (`stg_`) | 18: 4 MLB, 13 ESPN, 1 id crosswalk | One model per thing an API returns: a game, a batting line, a roster entry. Flattens the JSON, keeps one row per entity, converts to honest units. No business rules. |
| Intermediate (`int_`) | 23: 2 MLB, 21 fantasy | The same facts in the project's own terms and no platform's: a roster day, a player's day in MLB, a matchup side. ESPN's vocabulary stops here. |
| Marts (`fct_`, `dim_`) | 9 | Shaped like a question. [Listed below](#the-marts). |
| Reconciliation (`rec_`) | 7 | Our numbers beside ESPN's own, and every difference between them. Nothing reads from here; it exists to be checked. |

Every model's description, columns, SQL and tests are on the
[docs site](https://nick-socci.github.io/front-office/), with the graph of what feeds what.

The 2026 season as built on 2026-10-10: 2,430 scheduled games, of which 2,429 were
played; 51,708 batting lines and 20,800 pitching lines; 55,653 roster-days across 180
scoring periods; 737 transactions; 143 head-to-head matchups in 17 scoring categories.

## The marts

| Mart | The question it answers | One row per | Rows, 2026 |
|---|---|---|---|
| `fct_matchup_category_scores` | Who won each category of each matchup? | matchup, team and scored category | 4,862 |
| `fct_matchup_results` | Who won each matchup? | matchup | 143 |
| `fct_player_season_value` | What was a player worth to the team that started him? | player and fantasy team | 580 |
| `fct_player_category_value` | In which categories did that value come? | player, fantasy team and scored category | 9,860 |
| `fct_transaction_impact` | What did an add or a drop turn out to be worth? | transaction | 737 |
| `fct_lineup_decisions` | What did a team leave on its bench that day? | team and day | 2,160 |
| `fct_lineup_decision_categories` | Would the best lineups have changed a category's result? | matchup, team and scored category | 4,862 |
| `dim_players` | Who is this player? | MLB player | 1,515 |
| `dim_player_league_seasons` | Which MLB player is a platform's player, in this league and season? | player, league and season | 498 |

Value is measured against a replacement-level free agent and expressed in matchup
margins, so it adds up: the 580 player-seasons sum to 2,245.53, and so do the 2,160
team-days. `docs/examples/` holds a short query over each of the three questions, and
the one that was sub-project 1's definition of done.

## Does it agree with ESPN?

ESPN publishes each matchup's totals and who won each category. The reconciliation
layer recomputes both from MLB boxscores and the rosters, and puts the two side by side
for the whole season. Every difference has to be accounted for, or the build fails.

| Compared | Rows | Agree | The rest |
|---|---|---|---|
| Category results (win, loss, tie) | 4,862 | 4,856 | 6 `explained`: the category's values differ only by differences already accounted for below |
| Matchup stat values | 6,912 | 6,816 | 31 `registered`, 17 `explained_by_component`, 48 `bye` |

- **`registered` (31)** is a count that differs from ESPN's by exactly an amount recorded
  in a hand-kept register (`dbt/seeds/espn_reconciliation_residuals.csv`), each row with
  its cause and its evidence: 23 are `official_scoring_change` and 8 are
  `espn_total_inconsistent`.
- **`explained_by_component` (17)** is a rate (an average, an ERA) that differs from
  ESPN's but equals what our formula gives on ESPN's own components once the registered
  differences are applied. Rates are never registered themselves.
- **`bye` (48)** is a team with no opponent that week; ESPN reports its stats and there
  is no result to compare.

No value is `unexplained`, and all 143 matchup winners match. A registered difference
that stops occurring fails the build too, so the register cannot go stale.

## Try it

```bash
uv sync
uv run front-office backfill mlb --season 2026     # schedule + player list + ~2,400 boxscores
uv run front-office backfill espn --season 2026    # needs ESPN cookies, see below
uv run front-office backfill idmap
uv run front-office load
uv run front-office audit --season 2026            # complete, loaded and final?

cd dbt && DBT_PROFILES_DIR=. uv run dbt deps && uv run dbt build
duckdb ../data/warehouse.duckdb < ../docs/examples/roster_day_query.sql
```

The audit checks the files rather than the models: that every played game and scoring
period was captured, loaded, and captured late enough to be final. It exits non-zero on
anything that makes the data unreliable, and is rerun after every backfill.

That last query is the project's definition of done: *who was on team X's roster on date
D, and what did each of them do in MLB that day?*

ESPN league data requires `ESPN_S2`, `SWID` and `LEAGUE_ID` in a gitignored `.env`
(copy the cookies from a logged-in browser session). MLB's API needs no credentials.

### More than one league or season

Every capture is filed by the request it answers (its URL path, which is where ESPN puts
the league and season) and every league-scoped model carries `league_id` and `season`,
so several leagues and seasons can share one warehouse. Two things enforce it:

- `front-office load` refuses two captures with the same identity, naming both files and
  loading nothing, instead of quietly keeping one.
- `scripts/check_tenant_isolation.py`, part of the gates, builds a fixture of several
  league-seasons together, then each one with only its own league's earlier seasons, and
  fails if any model gives a league-season different rows. A league-season may read its
  league's earlier seasons (a category's scale blends them in); it may not read another
  league, or a later season.

### What a killed run leaves behind

At most a temporary directory. The next `backfill` moves anything under the landing zone
that is not a capture into a quarantine beside it (`data/raw_quarantine/`) before it
fetches, and then fetches whatever is missing. Nothing is ever deleted, and the audit
warns while the quarantine is not empty. A sweep that would move more than a handful of
things refuses, since that means a bug and not a crash.

```bash
uv run front-office repair --dry-run     # what would move, without moving it
uv run front-office repair               # the same sweep, without fetching
uv run front-office repair --deep        # also move captures whose payload fails its checksum
```

`load` and `audit` never wait for a running backfill; they say so if one is in progress.

### Rebuilding the warehouse after the raw table changes shape

The raw table is derived from the landing zone, so a change to its shape is a rebuild,
not a migration. `front-office load` refuses a warehouse with the old shape and changes
nothing. Build a new file beside the old one, compare, and only then swap them yourself:

```bash
uv run front-office load --db data/warehouse_r2.duckdb
cd dbt && FO_DUCKDB_PATH=../data/warehouse_r2.duckdb DBT_PROFILES_DIR=. uv run dbt build
cd .. && uv run python scripts/compare_warehouses.py data/warehouse.duckdb data/warehouse_r2.duckdb
```

The comparison lists any model present in only one file and any difference in the columns
they share, and exits non-zero if there is one. Builds are reproducible to the last digit
since #28, so the exact comparison is the right one from now on. For the first rebuild,
from a warehouse built before #28, add `--round-doubles 9`: that warehouse's decimal
values were not reproducible in their last digit, and without the option four models
are reported as differing.

## Decisions worth explaining

**Raw JSON first, parse in dbt.** The alternative — parsing in Python and storing tidy
tables — means every parsing fix requires re-fetching. Keeping raw responses made every
later milestone re-runnable offline, which mattered: ESPN rolls leagues over in the
offseason, so the 2026 data could not be re-fetched later.

**Snapshot vs immutable, per endpoint.** A boxscore is not final when the game ends;
official scorers revise hits and errors for days, so a boxscore is refetched until a
capture is at least 7 days newer than the game's first capture taken after its last
scheduled start. That is judged from capture timestamps alone, not the game's date, so a
missed week of runs repairs itself. An ESPN roster is settled once its scoring period is over, judged
against the league's own status rather than the period number.

**Components, never rates.** AVG, ERA and WHIP are ratios; averaging per-game ratios
gives the wrong answer. Staging stores at-bats and hits, earned runs and outs. Innings
are stored as `outs_recorded`, because "6.1 innings" means 6⅓ and treating it as a
decimal silently corrupts every rate built on it.

**Source freshness is defined, and dormant.** Source freshness is dbt's check of how
old a source's newest row is. `raw.api_responses` warns when its newest capture is more
than 36 hours old and errors at 7 days (`dbt source freshness`; on the season as it
stands it reads the newest capture's age to the second). Nothing runs it yet: there is
no schedule to be late, and the CI fixtures are months old by design, so it would fail
there every time. It wakes with the 2027 daily schedule. Its known limit is that it
gives one age for a table holding three sources, so a stalled feed can hide behind a
live one ([#114](https://github.com/nick-socci/front-office/issues/114)).

**Other people's data stays out.** League members never agreed to appear in a public
repo, so staging never selects member names or account GUIDs, `var('anonymize')` aliases
team names in CI, and committed fixtures are rebuilt from an allowlist of fields rather
than scrubbed. The fixture privacy tests and a pre-commit hook enforce it, and the docs
site is assembled from three named files that are checked before upload.

**Player ids, not names.** ESPN strips accents where MLB does not, and three names in
2026 belong to two different major leaguers each (including two Max Muncys). The SFBB
crosswalk resolves 99.4% of started roster entries; an unambiguous-name fallback covers
the rest.

## How this was built

Written with Claude Code, deliberately and openly. What that meant in practice:

- **Design first.** A [spec](docs/design/01-ingestion-and-staging.md)
  was written and reviewed before any code, then twice critiqued adversarially; both
  critiques changed the design (entity-grain dedupe, the settle window, allowlist
  fixtures). Since October every unit of work has a spec in
  [`docs/specs/`](docs/specs/) that I approve before anything is built, and each
  decision a reasonable engineer could have made differently has a record in
  [`docs/adr/`](docs/adr/README.md).
- **I verified against reality, not against the model's claims.** Every milestone was
  checked against the real season: summed player stats reconciled to the payload's own
  team totals for all 4,806 team-sides, pitcher runs allowed reconciled to opponent runs
  scored for 4,804 games, and random games checked against a *different* MLB endpoint.
- **The data corrected the code repeatedly.** A postponed game and its makeup share one
  `game_pk`, so deduplicating by recency silently kept 29 games that were never played.
  `doubleHeader` is `"N"`/`"Y"`/`"S"`, not a boolean. 309 appearances have zero plate
  appearances and still steal bases. None of that was predictable from documentation.
- **I corrected the model too.** Stat 34 was labelled OUTS from the upstream library; in
  my league ESPN displays it as IP. The seed now carries both.

Local validation on 2026-10-10: 884 pytest tests passed. On the real 2026 season dbt
found 57 models, 437 data tests, 155 unit tests and 7 seeds, and of the 655 it ran, 654
passed and one warned (the id crosswalk's coverage check, 9 rows). SQL is linted with
sqlfluff: 118 files, no violation and no exemption comment. CI runs all of it on the
fixtures, on pushes to `main` and on pull requests, and then publishes the docs site
from `main`.

**Known gaps.** A [code review](docs/reviews/2026-09-27-code-review.md) on 2026-09-27
found defects that the checks passing at the time did not cover. Each became an issue,
and all six are closed
([milestone](https://github.com/nick-socci/front-office/milestone/2?closed=1)). What is
open now: a roster period at the
very end of MLB's season cannot settle, because ESPN's counter stops
([#75](https://github.com/nick-socci/front-office/issues/75)); two things can only be
checked while a season is being played
([#66](https://github.com/nick-socci/front-office/issues/66),
[#69](https://github.com/nick-socci/front-office/issues/69)); and whether player value
predicts winning has not been tested on past seasons
([#83](https://github.com/nick-socci/front-office/issues/83)).

## Roadmap

Built: ingestion, staging, the intermediate layer, the nine marts
([above](#the-marts): `fct_matchup_category_scores`, `fct_matchup_results`,
`fct_player_season_value`, `fct_player_category_value`, `fct_transaction_impact`,
`fct_lineup_decisions`, `fct_lineup_decision_categories`, `dim_players`,
`dim_player_league_seasons`), the reconciliation against ESPN, and the
[docs site](https://nick-socci.github.io/front-office/). Not built, in order:

1. **BigQuery migration** — adapter-specific JSON and SQL need a representative
   migration spike; portability is not yet verified. The lineup solver is a dbt Python
   model and needs its own answer there (ADR 0039).
2. **Orchestration** — Dagster asset definitions locally, Cloud Scheduler + Cloud Run in
   production.
3. **Dashboard** — Streamlit: standings, projections, waiver targets, player trends.
   dbt already knows it is coming: it is declared as an exposure over the nine marts, so
   `dbt build --select +exposure:front_office_dashboard` builds everything it will need.
4. **Projections and waiver-wire recommendations** — marts that look forward. Everything
   built so far measures what happened.
5. **2027 season** — the daily schedule starts running for real, which is when source
   freshness and the settle window stop being theoretical.

Not planned: a multi-user portal. It would mean holding other people's ESPN session
cookies, which is a security problem I have no interest in owning. Raw storage and every
league-scoped model carry league and season identity and read scoring rules as data, and
a gate proves that two leagues by two seasons build the same together as alone. But only
one real league-season has been loaded, and no second platform has tested the interface.

The design docs, specs and decision records behind each of these, written before the
work and amended in the open where reality disagreed, are in [`docs/`](docs/).
