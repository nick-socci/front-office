-- Sub-project 1's definition of done:
--   "Who was on team X's roster on date D, and what did each of them do in MLB that day?"
--
-- Answering this needs every piece of the pipeline at once: ESPN rosters keyed by
-- scoring period, the period -> date bridge, and MLB game logs keyed by date.
--
-- Run with:
--   duckdb data/warehouse.duckdb < docs/examples/roster_day_query.sql
--
-- As it is, it asks about one team on one day (see `params` below). To ask about another,
-- set a DuckDB variable first; the file does not need editing (DuckDB 1.1 or later):
--   duckdb data/warehouse.duckdb -cmd "set variable team_id = 3" \
--     < docs/examples/roster_day_query.sql
-- The variables are league_id, team_id and on_date.
--
-- Players are resolved in two steps, in this order:
--
--   1. the ESPN <-> MLBAM crosswalk (stg_idmap__players), which resolves 99.41% of
--      started entries and correctly separates the two different major leaguers named
--      Max Muncy;
--   2. failing that, an accent-normalised name match -- but ONLY for names belonging to
--      exactly one MLB player. ESPN strips accents ("Teoscar Hernandez") while MLB does
--      not ("Hernández"), and the crosswalk lags for players called up late, so the
--      fallback earns its place; restricting it to unambiguous names keeps it from
--      silently merging two people.

.mode box

with params as (
    -- A team is chosen by its id, so that this file names no team. The output still
    -- shows team_name: the real one on your own warehouse, an alias in CI.
    -- A team_id is unique only within a league, so the league is named too; the date
    -- already fixes the season.
    -- Each value is read from a DuckDB variable of the same name and falls back to the
    -- one written here, so the file runs as it is and can be asked about another team.
    -- The gates ask it about a team and a day the fixtures hold (ADR 0049).
    select
        coalesce(getvariable('league_id'), '73677') as league_id,
        coalesce(getvariable('team_id'), 6) as team_id,
        coalesce(getvariable('on_date'), date '2026-07-02') as on_date
),

unambiguous_names as (
    -- Names that belong to exactly one MLB player, so a name match cannot merge two.
    select match_name
    from (
        select strip_accents(player_name) as match_name, mlbam_player_id
        from staging.stg_mlb__batting_game_logs
        union
        select strip_accents(player_name), mlbam_player_id
        from staging.stg_mlb__pitching_game_logs
    )
    group by match_name
    having count(distinct mlbam_player_id) = 1
),

roster as (
    select
        teams.team_name,
        periods.scoring_date,
        entries.player_name,
        entries.lineup_slot,
        entries.default_position,
        coalesce(
            crosswalk.mlbam_player_id,
            case
                when unambiguous_names.match_name is not null
                    then name_fallback.mlbam_player_id
            end
        ) as mlbam_player_id
    from staging.stg_espn__roster_entries as entries
    inner join staging.stg_espn__scoring_periods as periods
        on periods.league_id = entries.league_id
        and periods.season = entries.season
        and periods.scoring_period = entries.scoring_period
    inner join staging.stg_espn__teams as teams
        on teams.league_id = entries.league_id
        and teams.season = entries.season
        and teams.team_id = entries.team_id
    left join staging.stg_idmap__players as crosswalk
        on crosswalk.espn_player_id = entries.espn_player_id
    left join unambiguous_names
        on unambiguous_names.match_name = strip_accents(entries.player_name)
    left join (
        select distinct strip_accents(player_name) as match_name, mlbam_player_id
        from staging.stg_mlb__batting_game_logs
        union
        select distinct strip_accents(player_name), mlbam_player_id
        from staging.stg_mlb__pitching_game_logs
    ) as name_fallback
        on name_fallback.match_name = strip_accents(entries.player_name)
    inner join params
        on params.league_id = teams.league_id
        and params.team_id = teams.team_id
        and params.on_date = periods.scoring_date
    -- BE is the bench and IL is the injured list: neither scores that day.
    where entries.lineup_slot not in ('BE', 'IL')
),

batting as (
    select
        logs.mlbam_player_id,
        sum(logs.at_bats) as at_bats,
        sum(logs.hits) as hits,
        sum(logs.home_runs) as home_runs,
        sum(logs.runs_batted_in) as runs_batted_in,
        sum(logs.stolen_bases) as stolen_bases
    from staging.stg_mlb__batting_game_logs as logs
    inner join staging.stg_mlb__games as games on games.game_pk = logs.game_pk
    inner join params on params.on_date = games.official_date
    group by logs.mlbam_player_id
),

pitching as (
    select
        logs.mlbam_player_id,
        sum(logs.outs_recorded) as outs_recorded,
        sum(logs.strikeouts) as strikeouts,
        sum(logs.earned_runs) as earned_runs,
        sum(logs.wins) as wins,
        sum(logs.saves) as saves
    from staging.stg_mlb__pitching_game_logs as logs
    inner join staging.stg_mlb__games as games on games.game_pk = logs.game_pk
    inner join params on params.on_date = games.official_date
    group by logs.mlbam_player_id
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
        when roster.mlbam_player_id is null then 'unresolved player'
        when batting.mlbam_player_id is null and pitching.mlbam_player_id is null
            then 'did not play'
    end as note
from roster
left join batting on batting.mlbam_player_id = roster.mlbam_player_id
left join pitching on pitching.mlbam_player_id = roster.mlbam_player_id
order by roster.lineup_slot, roster.player_name;
