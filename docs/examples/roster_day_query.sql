-- Sub-project 1's definition of done:
--   "Who was on team X's roster on date D, and what did each of them do in MLB that day?"
--
-- Answering this needs every piece of the pipeline at once: ESPN rosters keyed by
-- scoring period, the period -> date bridge, and MLB game logs keyed by date.
--
-- Run with:
--   duckdb data/warehouse.duckdb < docs/examples/roster_day_query.sql
--
-- PROVISIONAL JOIN: players are matched on accent-normalised name, because the
-- ESPN <-> MLBAM id crosswalk arrives in milestone 6. On the 2026 season this matches
-- 100% of started entries (38,665) -- but three names are shared by two different MLB
-- players each (Jose Fermin, Max Muncy, Yunior Marte), affecting 150 rostered entries,
-- so a name join can silently merge two people. That is exactly why the crosswalk
-- exists; until it lands, treat those rows with suspicion.

.mode box

with params as (
    select 'Wonder Wharf Wonderdogs' as team_name, date '2026-07-02' as on_date
),

roster as (
    select
        teams.team_name,
        periods.scoring_date,
        entries.player_name,
        entries.lineup_slot,
        entries.default_position,
        strip_accents(entries.player_name) as match_name
    from staging.stg_espn__roster_entries as entries
    inner join staging.stg_espn__scoring_periods as periods
        on periods.league_id = entries.league_id
        and periods.season = entries.season
        and periods.scoring_period = entries.scoring_period
    inner join staging.stg_espn__teams as teams
        on teams.league_id = entries.league_id
        and teams.season = entries.season
        and teams.team_id = entries.team_id
    inner join params
        on params.team_name = teams.team_name
        and params.on_date = periods.scoring_date
    -- BE is the bench and IL is the injured list: neither scores that day.
    where entries.lineup_slot not in ('BE', 'IL')
),

batting as (
    select
        strip_accents(logs.player_name) as match_name,
        sum(logs.at_bats) as at_bats,
        sum(logs.hits) as hits,
        sum(logs.home_runs) as home_runs,
        sum(logs.runs_batted_in) as runs_batted_in,
        sum(logs.stolen_bases) as stolen_bases
    from staging.stg_mlb__batting_game_logs as logs
    inner join staging.stg_mlb__games as games on games.game_pk = logs.game_pk
    inner join params on params.on_date = games.official_date
    group by 1
),

pitching as (
    select
        strip_accents(logs.player_name) as match_name,
        sum(logs.outs_recorded) as outs_recorded,
        sum(logs.strikeouts) as strikeouts,
        sum(logs.earned_runs) as earned_runs,
        sum(logs.wins) as wins,
        sum(logs.saves) as saves
    from staging.stg_mlb__pitching_game_logs as logs
    inner join staging.stg_mlb__games as games on games.game_pk = logs.game_pk
    inner join params on params.on_date = games.official_date
    group by 1
)

select
    roster.scoring_date,
    roster.team_name,
    roster.lineup_slot,
    roster.player_name,
    batting.at_bats,
    batting.hits,
    batting.home_runs,
    batting.runs_batted_in,
    batting.stolen_bases,
    round(pitching.outs_recorded / 3.0, 1) as innings_pitched,
    pitching.strikeouts,
    pitching.earned_runs,
    pitching.wins,
    pitching.saves,
    case
        when batting.match_name is null and pitching.match_name is null then 'did not play'
    end as note
from roster
left join batting on batting.match_name = roster.match_name
left join pitching on pitching.match_name = roster.match_name
order by roster.lineup_slot, roster.player_name;
