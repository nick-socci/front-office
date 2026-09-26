# Handover — Fantasy Baseball Analytics

**Status (updated 2026-09-26):** Sub-project 1 is complete — ingestion, DuckDB warehouse,
dbt staging layer and CI are built and running on the full 2026 season. Sub-project 2
(intermediate layer and marts) is underway; milestone 7 is merged. The project is named
**Front Office** and lives at https://github.com/nick-socci/front-office.

| Sub-project | Spec | State |
|---|---|---|
| 1 — ingestion, staging, CI | [`2026-09-20-ingestion-and-staging-design.md`](docs/superpowers/specs/2026-09-20-ingestion-and-staging-design.md) | Complete (PRs 1–6) |
| 2 — intermediate layer and marts | [`2026-09-26-intermediate-and-marts-design.md`](docs/superpowers/specs/2026-09-26-intermediate-and-marts-design.md) | In progress (PR 7 merged) |
| 3 — BigQuery, orchestration, dashboard | not yet written | Not started |

Each spec carries its own milestone-by-milestone progress table. The README has the
public-facing view of what exists today and the roadmap.

**Outstanding, not yet done:** the 2026 MLB backfill stopped at 2,402 of 2,430 games,
because the regular season ran to 2026-09-27. Re-run the backfill after that date and
again around 2026-10-05 so the 7-day settle window closes, then refresh the NAS backup.
The fantasy season ended at scoring period 180 (2026-09-20), so no fantasy analysis
depends on those last 28 games.

The open decisions below are resolved: DuckDB now with BigQuery to follow, marts
confirmed against a 17-category league, the AI-assisted write-up lives in the README,
and the project has a name.

Everything below is the original planning record from 2026-09-16/17, kept as written.

## Why this project exists

Part of a deliberate job-search pivot (tracked in `~/projects/job-search/career-ops`) from low-code BI work (Alteryx) toward code-first Analytics Engineering roles. An evaluation of an Anthropic Data Engineer posting (career-ops `reports/001-anthropic-2026-09-16.md`) surfaced a real gap: no dbt, Airflow/orchestration, GitHub/CI, or modern-dashboard experience shows up in `cv.md`. This project is designed to close exactly those gaps with something you'll actually finish, because it's about a subject you're already invested in (your own ESPN fantasy league) rather than synthetic demo data.

Once built, this becomes a real, source-grounded proof point — run it through career-ops' `/career-ops project` mode for an evaluation against your archetypes, then `/career-ops add` to bring it into `cv.md`/`article-digest.md`. Nothing gets claimed there until it's real and working.

This also supports the two "adjacent, keep open" archetypes added to `career-ops/modes/_profile.md` on 2026-09-17: Software/ML Engineering (entry point) and AI-assisted/Agentic Engineering — the latter because the plan is to openly document AI-assisted development in the README rather than hide it.

## The rejected alternative

First plan was a synthetic sales/commission pipeline (mirrors the day job's domain directly). Rejected in favor of fantasy baseball for one dominant reason: genuine personal interest means it actually gets finished, and it naturally produces a better story — real live data, a real reason to need a daily schedule, and a dashboard you'd actually use yourself instead of abandoning after the demo.

## Architecture

```
data_generator/     -> not literal "generator" here; ingestion scripts pulling real data
dbt/                -> staging -> intermediate -> marts
orchestration/       -> Dagster asset/schedule definitions (see "Orchestration" below for the local-vs-prod split)
dashboard/           -> Streamlit app
.github/workflows/   -> CI (dbt tests + lint on push)
```

### Data sources

- **MLB Stats API** — free, public, no key required. Schedules, boxscores, player game logs, standings.
  - Live in-game data via the "GUMBO" feed: `https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live` — pull-based, updates roughly every ~12 seconds during a live game. This is the practical free option.
  - A true push feed (ActiveMQ, 1-2 second latency) exists but is MLB's internal infrastructure for official broadcast/media partners — not self-serve. Don't chase this.
- **ESPN Fantasy API** — unofficial/undocumented, but well-supported via the community `espn-api` Python package. Confirmed: this is a **private ESPN league**, so it needs auth.
  - Auth: grab the `espn_s2` and `SWID` cookies from a logged-in browser session. Store in a local `.env` file (already gitignored below) — **never commit these**, they're tied to your personal ESPN login.
  - Keep polling reasonable (every 1-2 minutes, not sub-minute) — it's an undocumented API and aggressive polling risks a rate-limit/block.

### Transform layer (dbt)

- Staging: `stg_games`, `stg_player_game_logs`, `stg_rosters`, `stg_league_matchups`
- Intermediate: rolling player performance windows (7/14/30-day), matchup projections
- Marts: `mart_player_value`, `mart_weekly_matchup_projection`, `mart_waiver_wire_recommendations`
- Tests: standard schema tests (not_null/unique/relationships) on all keys, reasonable-range tests on stats (e.g. batting average between 0 and 1), and **dbt source freshness tests** — these are a strong fit here since the data genuinely should update daily during season.

### Warehouse: DuckDB vs BigQuery (open decision)

- **DuckDB**: file-based, zero infra, dbt-native. Simple to start with; store the file in Cloud Storage (5GB free) if it needs to live in the cloud.
- **BigQuery**: 10GB storage + 1TB queries/month free, plus **2 TiB/month free Storage Write API ingestion** (confirmed current as of this conversation — see Sources below) — comfortably covers this project's volume even at high polling frequency. Stronger resume signal since real analytics-engineering jobs run on BigQuery/Snowflake/Redshift, not DuckDB. `dbt-bigquery` is a very common real-world pairing.
- **Recommendation if undecided when picking this back up:** start on DuckDB for local dev speed, migrate to BigQuery before calling it "done" — the migration itself is a nice, honestly-earned resume bullet ("designed for portability, migrated to BigQuery for production").

### Orchestration (Dagster) — the one deployment wrinkle

Dagster's normal deployment is a persistent webserver + daemon, which doesn't fit cleanly into "pay only when invoked" free tiers.

**Recommended pattern:** keep Dagster as the local dev/design layer — asset and schedule definitions live in the repo and demonstrate the orchestration thinking — but let the actual production trigger be lightweight: Cloud Scheduler -> Cloud Run/Cloud Function running the ingest+dbt steps directly. This is a normal real-world pattern, not a compromise, and it's genuinely free (see cost section below).

Alternative if you want Dagster actually hosted: the single free e2-micro Compute Engine instance (only in `us-west1`/`us-central1`/`us-east1`, 30GB disk, 1GB egress) can technically run it, but that VM is small (shared vCPU, ~1GB RAM) and will be tight running webserver + daemon + dbt together.

### Dashboard

**Streamlit**, hosted on **Streamlit Community Cloud** (free, deploys straight from a public GitHub repo). Confirmed limits: 1GB RAM, sleeps after 12 idle hours (fine — just a ~30s cold start), needs the repo to be public. If you'd rather host on GCP specifically, Cloud Run works too (within the 2M free requests/month).

Planned views: live standings, this week's projected points, ranked waiver-wire pickups, player trend charts.

### CI

GitHub Actions: run `dbt build`/`dbt test` + a Python linter on every push. Unrelated to GCP, free/unlimited on a public repo. A green CI badge on a personal project is the single strongest "good software practices" signal in the whole build — worth prioritizing early, not leaving until the end.

## Cost analysis (GCP free tier)

**Bottom line: the whole stack runs at $0/month if you build it right.**

- Daily ingestion -> Cloud Run/Functions: 2M invocations/month free, trivial usage here.
- Daily trigger -> Cloud Scheduler: 3 free jobs/month per billing account, one daily cron costs nothing.
- Storage -> Cloud Storage (5GB free) for DuckDB, or BigQuery (10GB storage + 1TB queries + 2TiB streaming ingestion, all free).
- Dashboard -> Streamlit Community Cloud, free, not GCP.
- CI -> GitHub Actions, free on a public repo.

**On "live" stats specifically:** 1-minute refresh cadence (Cloud Scheduler's finest native granularity anyway) is indistinguishable from "live" for fantasy purposes and stays completely free — ~9,000 invocations/month at 5 live hours/day, a rounding error against the 2M free tier. **True sub-minute continuous polling** requires a different pattern (a long-running Cloud Run job/loop instead of discrete scheduled calls), which shifts billing from "free invocations" to "billed compute time." Rough estimate if you went that route: **~$10-30/month** depending on how many simultaneous games you track through a season — bounded and hobby-affordable, but real money instead of free. **Recommendation: build v1 on 1-minute cadence.** Treat true sub-minute streaming as a documented phase-2 stretch goal, not a v1 requirement.

## Timeline (~20-30 hours at 5-8 hrs/week, roughly 3-4 weeks)

- **Week 1:** ingestion scripts (MLB Stats API + ESPN league pull) -> DuckDB -> dbt staging models -> repo scaffold -> first GitHub Actions CI run.
- **Week 2:** intermediate/mart models + full dbt test suite -> CI runs full `dbt build`.
- **Week 3:** Dagster asset/schedule definitions (local) + the real Cloud Scheduler/Cloud Run production trigger + Streamlit dashboard v1.
- **Week 4:** README polish (architecture diagram, "How this was built" section documenting AI-assisted development honestly — what was reviewed/tested yourself, not just accepted — and a Roadmap/Phase 2 section), final CI cleanup.

## Open decisions for next session

1. DuckDB-only, or migrate to BigQuery before calling v1 done?
2. Confirm exact mart list once the ESPN league's actual scoring rules are pulled in (standard categories vs. points league changes what "value" and "projection" mean).
3. Decide whether the AI-assisted-build writeup goes in the main README or a separate `BUILD_LOG.md`.
4. Pick a real project name (currently just the directory name).

## Sources referenced during planning

- [Free Trial and Free Tier Services and Products | Google Cloud](https://cloud.google.com/free)
- [Cloud Scheduler pricing | Google Cloud](https://cloud.google.com/scheduler/pricing)
- [Status and limitations of Community Cloud — Streamlit Docs](https://docs.streamlit.io/deploy/streamlit-community-cloud/status)
- [MLB Delivers Real-Time Data to Fans | Google Cloud Blog](https://cloud.google.com/blog/products/databases/mlb-delivers-real-time-data-to-fans)
- [GUMBO Documentation (PDF)](https://bdata-research-blog-prod.s3.amazonaws.com/uploads/2019/03/GUMBOPDF3-29.pdf)
- [BigQuery streaming data documentation | Google Cloud](https://docs.cloud.google.com/bigquery/docs/streaming-data-into-bigquery)
