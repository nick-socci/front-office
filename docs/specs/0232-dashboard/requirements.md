# The dashboard over the marts, on `mothership` — requirements

Issue: #232 · Tier: L · Status: draft

## Problem

The nine marts are built and checked every day on BigQuery (ADR 0123), and nothing reads them: the
only consumers are the example queries in `docs/examples/` (ADR 0045). The daily run starts on
2027-03-01 (ADR 0134), and in season the owner wants to see standings, matchups, player value,
lineup decisions and transactions without writing SQL. The owner chose on 2026-11-21 that the
dashboard comes before the forward-looking marts (roadmap item 2) and runs on `mothership` (ADR
0126) beside the daily run. Two things it needs are in no mart: team names (C3) and standings
(C4). The 2026 season is complete and fixed (C8), so it is a stable base to build on now.

## Goals

- The owner opens the dashboard and sees the current season's standings, matchups, player value,
  lineup decisions and transactions, and any earlier season's, by real team name.
- Every number on a page is a mart column, so dbt's tests hold every number the owner reads.
- Page views cost $0, and the dashboard holds no credential.
- Each page says how old its data is, so a failed run (spec 0219) never passes for current data.
- It deploys and rolls back with the daily run's image, by the runbook.

## No-gos

Explicitly out of scope. Work that drifts here is escalated, not done.

- Projections and waiver targets: pages over roadmap item 2's marts, when they exist.
- Any page that works out a number itself (an aggregate, a rate, a rank): such a number becomes a
  mart first (R4, ADR 0147).
- A public address, a login system, or hosting anywhere but `mothership`. No one else uses it.
- Writing to the warehouse from the dashboard, or editing anything from a page.
- A new Google identity or key for the dashboard (ADR 0144 makes one unnecessary).
- Recomputing ESPN's playoff seeding or its tiebreakers (ADR 0148).
- Player-by-day trend marts: the "trends" here are by season, which the marts already hold.
- Screenshots or numbers from the real league anywhere in the repository (rule 2, `fo_anonymize`).

## Rabbit holes

- Querying BigQuery from the page for freshness → the extract carries its own build time and the
  marts' last-modified times (R2.4); a page reads only the file.
- A DuckDB file replaced while the app has it open → the extract publishes by one rename (R2.3),
  and the app opens a fresh read-only connection per query, so a reader sees the old file or the
  new one, never half of one (ADR 0014's pattern).
- Mapping every BigQuery type to DuckDB → only the types the marts use are mapped (C9). Any other
  type stops the extract, naming the column (R2.5).
- Charts as a design project → Streamlit's built-in tables and charts only; no custom components,
  no theme work.
- Streamlit's own server settings (CORS, XSRF, telemetry) → set once in a committed
  `.streamlit/config.toml`. The listener is loopback-only (R5.2), so they are defence in depth, not
  the control.
- A standings rule for every scoring type → the computed record is defined for
  `H2H_MOST_CATEGORIES`, the only type with matchups in the data (C5). Other types carry ESPN's
  record and null computed columns (ADR 0148).

## Requirements

### R1. Marts for what the pages show

Team names and standings become marts, tested like the rest.

- R1.1 THE SYSTEM SHALL build `dim_fantasy_teams`, one row per (platform, league_id, season,
  fantasy_team_id), with `team_name` and `team_abbrev` from `int_fantasy__teams`. CI builds them
  anonymised, as every model is (`fo_anonymize`).
- R1.2 THE SYSTEM SHALL build `fct_team_standings`, one row per (platform, league_id, season,
  fantasy_team_id), with `scoring_type`, the finished regular-season matchups counted
  (`matchups`), the computed `wins`, `losses` and `ties` over them from `fct_matchup_results`
  (`playoff_tier = 'NONE'`), the computed `category_wins`, `category_losses` and `category_ties`
  over the same matchups, `is_regular_season_complete`, and ESPN's `reported_wins`,
  `reported_losses`, `reported_ties` and `reported_playoff_seed`.
- R1.3 WHILE a league-season's `scoring_type` is not `H2H_MOST_CATEGORIES`, THE SYSTEM SHALL leave
  the computed record columns null and still carry ESPN's.
- R1.4 THE SYSTEM SHALL hold, as a dbt test, that each team's computed record minus ESPN's equals,
  in wins, losses and ties, the sum of what the team's listed regular-season matchups in
  `rec_espn__winner_differences` change (our result against ESPN's). It is an error for a
  league-season whose regular season is complete, and a warning for one in progress, where a
  capture taken between rollovers can lag.
- R1.5 THE SYSTEM SHALL count a regular-season matchup only when it is finished. That means its
  matchup period is before ESPN's current matchup period (`status.currentMatchupPeriod`, amended
  2026-11-23, ADR 0149), and it has no undecided category. So a matchup in progress is in no
  one's record until ESPN has moved past its period.
  `is_regular_season_complete` is true when every regular-season matchup is finished.

### R2. An extract of the marts, made by the daily run

- R2.1 WHEN `daily` builds the marts, THE SYSTEM SHALL copy every mart that the
  `front_office_dashboard` exposure names (read from `dbt/models/marts/_exposures.yml`, which is in
  the image) into one DuckDB file, the extract, through a new asset `marts_extract`, one CLI
  command (`front-office extract-marts`, ADR 0127).
- R2.2 WHILE the warehouse is BigQuery, THE SYSTEM SHALL read each mart with `tabledata.list`,
  which bills nothing (C10), as the run's own identity. WHILE it is DuckDB, it SHALL copy from the
  DuckDB warehouse file. Neither path runs a query that BigQuery bills.
- R2.3 THE SYSTEM SHALL write the extract beside its destination and publish it by one rename, so
  a reader sees the previous extract or the new one, never a partial file.
- R2.4 THE SYSTEM SHALL record in the extract, in a table `extract_info`, when it was made, the
  commit that made it (`FO_GIT_COMMIT`, set in the image from its build argument; on the laptop,
  `git rev-parse HEAD`; `unknown` if neither is there, which never fails the extract), and each
  mart's row count and last-modified time in the warehouse.
- R2.5 IF a mart has a column type the extract does not map, or a mart the exposure names is
  missing, THEN THE SYSTEM SHALL fail `marts_extract` with the table and column named, and leave
  the previous extract in place.
- R2.6 IF a mart fails to build or an error-severity test fails in the run, THEN THE SYSTEM SHALL
  not run `marts_extract`, and the previous extract stays. The extract is all of one build or
  none of it.
- R2.7 THE SYSTEM SHALL make the extract by hand with the same command, from the laptop (DuckDB)
  or in the code server's container (BigQuery), so it can be made out of season.

### R3. The pages

- R3.1 THE SYSTEM SHALL serve these pages, each with a league-season picker that defaults to the
  latest season in the extract:
  - **Standings**: `fct_team_standings` with team names, and each team's computed record beside
    ESPN's. A season whose regular season is complete is in ESPN's seed order. A season in progress
    is ordered by computed wins (most first), then losses (fewest first), labelled "by record so
    far", with ESPN's seed shown as reported (ADR 0148).
  - **Matchups**: for a matchup period, each matchup's result (`fct_matchup_results`) and its
    category scores per side (`fct_matchup_category_scores`).
  - **Players**: the season's players by `total_value` (`fct_player_season_value`), filterable by
    fantasy team and replacement group, with a player's category values
    (`fct_player_category_value`) and the player's value in each season they were rostered.
  - **Lineups**: a team's lineup decisions by day (`fct_lineup_decisions`) and its category results,
    actual against optimal, per matchup (`fct_lineup_decision_categories`).
  - **Transactions**: the season's adds and drops with what each player did afterwards
    (`fct_transaction_impact`).
- R3.2 THE SYSTEM SHALL show each mart column under its dbt column name, or under a label taken
  from that column's description, never under a name that means something else.
- R3.3 THE SYSTEM SHALL show innings from `outs_recorded` as whole innings and thirds ("6.1" read as
  6⅓, rule 4), formatted for display only, and never feed the formatted value to arithmetic.
- R3.4 WHEN a row has `has_unverified_inputs` or `is_unvalued` true, THE SYSTEM SHALL mark that row
  on the page.

### R4. Pages compute nothing

- R4.1 THE SYSTEM SHALL keep every page query in a `.sql` file under the dashboard's `queries/`
  directory, reading only `marts.*` relations in the extract.
- R4.2 THE SYSTEM SHALL hold, as a gate, that no page query aggregates (`group by`, an aggregate
  function, a window) or computes a column from arithmetic on two or more columns. A query filters,
  sorts, joins on keys and selects columns; formatting is done in Python, for display only.
- R4.3 THE SYSTEM SHALL hold, as a gate, that the relations the page queries read are exactly the
  `front_office_dashboard` exposure's `depends_on`, so the exposure says what the dashboard reads
  (ADR 0045's follow-up).

### R5. On `mothership`, reachable only as the owner chose

- R5.1 THE SYSTEM SHALL run the dashboard as a fourth Quadlet unit, `front-office-dashboard`, from
  the daily run's image, under the `front-office` user, with its own memory limit set from a
  measured peak. The image holds `dashboard/` (today `.containerignore` leaves it out), and a smoke
  check in the image build imports the app.
- R5.2 THE SYSTEM SHALL mount nothing into the dashboard's container but the extract's directory,
  read-only. It gets no credential, no landing zone and no Dagster instance, and listens only on the
  host's loopback (ADR 0146).
- R5.3 THE SYSTEM SHALL be reached by the way ADR 0146 chooses, and by no other.
- R5.4 WHEN the code server is restarted for a deploy, THE SYSTEM SHALL keep serving the last
  extract. WHEN the dashboard's unit is restarted, no run is touched.
- R5.5 THE SYSTEM SHALL be described in the runbook: deploy, roll back, see that it is up, reach it,
  make an extract by hand.

### R6. Freshness on every page

- R6.1 THE SYSTEM SHALL show on every page when the extract was made and the newest mart's
  last-modified time, from `extract_info`.
- R6.2 WHILE the extract is older than 36 hours in season (March to October, ADR 0134), THE SYSTEM
  SHALL show a warning on every page that the data may be stale and the daily run should be
  checked, in the words the runbook uses for a stale feed.
- R6.3 IF there is no extract, THEN THE SYSTEM SHALL show one page that says so and how to make one
  (R2.7), and nothing else.

### R7. Tested in CI

- R7.1 THE SYSTEM SHALL run every page query against the CI fixtures' warehouse (`dbt/ci.duckdb`,
  anonymised) in the gates, after the dbt build, and fail on an error or on a query that returns no
  rows where the fixtures hold some.
- R7.2 THE SYSTEM SHALL render every page headless (Streamlit's `AppTest`) over an extract made
  from the CI warehouse, and fail on an exception or a missing freshness line.
- R7.3 THE SYSTEM SHALL test the extract's type mapping, its rename-publish, its `extract_info` and
  each of R2.5's refusals with no BigQuery (a fake reader), and its DuckDB path against the CI
  warehouse.

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| `dim_fantasy_teams` rows, real season | 96: 12 teams × 8 seasons with teams (2018, 2019, 2021 to 2026) (C4) | `select count(*) from marts.dim_fantasy_teams` on BigQuery and DuckDB |
| `fct_team_standings` regular season complete, real season | `is_regular_season_complete` true for all 96 rows; `matchups` per team = the season's regular-season periods: 21, or 23 in 2024 and 22 in 2025 (C19) | `select season, min(matchups), max(matchups), bool_and(is_regular_season_complete) … group by 1` |
| `fct_team_standings` computed record = ESPN's, real season | 90 of 96 teams equal; the 6 that differ are 2019 teams 8 and 9, 2022 teams 7 and 8, 2025 teams 4 and 7, each explained by one of three listed matchups (2019 #74, 2022 #123, 2025 #77) (C6) | the R1.4 test passes; `select … where wins <> reported_wins or losses <> reported_losses or ties <> reported_ties` |
| 2026 standings | seeds 1 to 3 are 15-3-3, 15-4-2, 15-5-1; every 2026 team's computed record = ESPN's (C6) | the Standings page over the real extract, recorded on #232 |
| Extract = the warehouse | for each mart the exposure names, the extract and the laptop's DuckDB marts are equal (`except all` both ways: 0 rows), floats included (ADR 0116) | `scripts/compare_warehouses.py`-style check, recorded on #232 |
| Extract bytes billed | 0 bytes billed by `marts_extract` | the run's BigQuery job list for the run's window: no query job from `marts_extract` (C10) |
| Extract size and time | about 20 MB of marts in BigQuery (C1); the file and its time recorded | `ls -l`; the asset's duration in the run |
| Dashboard memory | peak PSS under its `--memory=` limit over a session that opens every page for every season; host total under 11.9 GB with a `daily` running (C7) | the 0218 `measure.sh` method, recorded on #232 |
| Reachability | the page answers only by the way ADR 0146 chooses: from the laptop through it, and not on the host's public or tailnet address | `curl` from the laptop by each path, recorded on #232 |
| Monthly cost | $0: no new GCP SKU, no new Oracle resource | the project's billing report for the first month with daily runs (with #218's R7.3) |
