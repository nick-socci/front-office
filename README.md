# Front Office

[![CI](https://github.com/nick-socci/front-office/actions/workflows/ci.yml/badge.svg)](https://github.com/nick-socci/front-office/actions/workflows/ci.yml)

A code-first analytics engineering project: real MLB and ESPN fantasy data, ingested as
raw JSON, transformed with dbt, stored in DuckDB (BigQuery planned), and tested in CI.

It exists because I play in a 17-category head-to-head fantasy baseball league and
wanted to answer questions the ESPN app will not: who was actually on a roster on a
given day, what those players did in real games, and where the value is.

## What it does today

```
MLB Stats API  ─┐
ESPN Fantasy   ─┼─►  raw JSON on disk  ─►  raw.api_responses  ─►  dbt staging models
SFBB id map    ─┘    (landing zone)        (one row per         (one row per game,
                                            API response)        player, roster day...)
```

**Ingestion (Python)** fetches and saves; it never interprets. Each response is written
unchanged, with a metadata sidecar recording the request, then loaded into a single
append-only table. A parsing mistake costs a rebuild, not a re-download of the season.

The intermediate layer now builds platform-facing interfaces, roster days, MLB player
days (including doubleheader aggregation), and started-player attribution. Marts and
full-season matchup reconciliation are still pending.

**Transformation (dbt)** does everything that requires knowing what the data means:
flattening JSON, deduplicating at the entity grain, and converting to honest units.

| Layer | Models |
|---|---|
| MLB | `stg_mlb__games`, `stg_mlb__batting_game_logs`, `stg_mlb__pitching_game_logs` |
| ESPN | `stg_espn__league_settings`, `stg_espn__scoring_categories`, `stg_espn__scoring_periods`, `stg_espn__teams`, `stg_espn__roster_entries`, `stg_espn__matchups`, `stg_espn__matchup_category_results`, `stg_espn__transactions` |
| Crosswalk | `stg_idmap__players` (ESPN ↔ MLBAM player ids) |

The recorded 2026 snapshot (2026-09-26): 2,430 scheduled games, 51,129 batting lines,
20,542 pitching lines, 55,653 roster-days across 180 scoring periods, 737 transactions.
Only 2,402 games were Final; the remaining backfill and correction refresh are
[outstanding](docs/README.md#outstanding).

## Try it

```bash
uv sync
uv run front-office backfill mlb --season 2026     # schedule + ~2,400 boxscores
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

## Decisions worth explaining

**Raw JSON first, parse in dbt.** The alternative — parsing in Python and storing tidy
tables — means every parsing fix requires re-fetching. Keeping raw responses made every
later milestone re-runnable offline, which mattered: ESPN rolls leagues over in the
offseason, so the 2026 data could not be re-fetched later.

**Snapshot vs immutable, per endpoint.** A boxscore is not final when the game ends;
official scorers revise hits and errors for days, so boxscores stay refetchable for a
7-day settle window. An ESPN roster is settled once its scoring period is over, judged
against the league's own status rather than the period number.

**Components, never rates.** AVG, ERA and WHIP are ratios; averaging per-game ratios
gives the wrong answer. Staging stores at-bats and hits, earned runs and outs. Innings
are stored as `outs_recorded`, because "6.1 innings" means 6⅓ and treating it as a
decimal silently corrupts every rate built on it.

**Other people's data stays out.** League members never agreed to appear in a public
repo, so staging never selects member names or account GUIDs, `var('anonymize')` aliases
team names in CI, and committed fixtures are rebuilt from an allowlist of fields rather
than scrubbed. Thirty tests enforce it.

**Player ids, not names.** ESPN strips accents where MLB does not, and three names in
2026 belong to two different major leaguers each (including two Max Muncys). The SFBB
crosswalk resolves 99.4% of started roster entries; an unambiguous-name fallback covers
the rest.

## How this was built

Written with Claude Code, deliberately and openly. What that meant in practice:

- **Design first.** A [spec](docs/design/01-ingestion-and-staging.md)
  was written and reviewed before any code, then twice critiqued adversarially; both
  critiques changed the design (entity-grain dedupe, the settle window, allowlist
  fixtures).
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

Local validation on 2026-09-27: 100 pytest tests passed; dbt executed 159 nodes
(158 passed, one player-ID coverage warning). CI runs these checks on main pushes and
pull requests.

**Known gaps.** A [code review](docs/reviews/2026-09-27-code-review.md) on 2026-09-27
found defects that these passing checks do not cover: the skip logic does not yet
guarantee a final capture, raw keys do not yet separate leagues and seasons, and one
reconciliation test cannot fail on the fixtures. The fixes are sequenced there.

## Roadmap

1. **Marts** — player value, weekly matchup projections, waiver-wire recommendations,
   built on the merged intermediate layer; full-season reconciliation comes first.
2. **BigQuery migration** — adapter-specific JSON and SQL need a representative
   migration spike; portability is not yet verified.
3. **Orchestration** — Dagster asset definitions locally, Cloud Scheduler + Cloud Run in
   production.
4. **Dashboard** — Streamlit: standings, projections, waiver targets, player trends.
5. **2027 season** — the daily schedule starts running for real, which is when source
   freshness tests and the settle window stop being theoretical.

Not planned: a multi-user portal. It would mean holding other people's ESPN session
cookies, which is a security problem I have no interest in owning. The intermediate
interfaces carry league and season identity and read scoring rules as data, but raw
loading does not yet (see known gaps), and no second platform has tested the interface.

The design docs behind each of these, written before the work and annotated afterwards
where reality disagreed, are in [`docs/`](docs/).
