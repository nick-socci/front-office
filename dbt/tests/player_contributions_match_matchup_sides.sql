-- R5.1: for every matchup side and every credited component, the started player-days that
-- fall in that matchup must sum to the side's row in int_fantasy__matchup_side_totals.
-- Exact, no tolerance. Returns each (side, component) that differs, with both values.
--
-- Reconciled per side, never per team or per season: errors in two matchups would cancel
-- in a season total. A side is (league, season, matchup_period, fantasy team); matchup_id
-- is carried from the totals for reading the result. Days outside a matchup (the team has no
-- side in that date's period: a bye) join no side and are covered by
-- player_value_days_match_started_days, not here.
--
-- A FULL OUTER JOIN, so a side present on one end only is a failure, with one exception
-- that is the point: a side that started nobody has no player rows at all, and compares as
-- 0 = 0 rather than being skipped. Started days with no side to land on (side_total null)
-- fail. Components are unpivoted by looping over the fo_*_columns macros, as
-- int_fantasy__matchup_stat_values does, so every credited component is checked.
--
-- Catches double counting (a date in two periods), a missed day, a wrong join grain, and a
-- component dropped from one end's column list.

{%- set stat_columns = fo_batting_columns() + fo_pitching_columns() %}

with player_components as (

    {%- for column in stat_columns %}
    select
        days.platform,
        days.league_id,
        days.season,
        periods.matchup_period,
        days.fantasy_team_id,
        '{{ column }}' as component,
        cast(sum(days.{{ column }}) as double) as player_total
    from {{ ref('int_fantasy__started_player_days') }} as days
    inner join {{ ref('int_fantasy__matchup_periods') }} as periods
        on periods.platform = days.platform
        and periods.league_id = days.league_id
        and periods.season = days.season
        and periods.scoring_date = days.scoring_date
    inner join {{ ref('int_fantasy__matchup_sides') }} as sides
        on sides.platform = periods.platform
        and sides.league_id = periods.league_id
        and sides.season = periods.season
        and sides.matchup_period = periods.matchup_period
        and sides.fantasy_team_id = days.fantasy_team_id
    group by days.platform, days.league_id, days.season, periods.matchup_period, days.fantasy_team_id
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

side_components as (

    {%- for column in stat_columns %}
    select
        platform,
        league_id,
        season,
        matchup_period,
        fantasy_team_id,
        matchup_id,
        '{{ column }}' as component,
        cast({{ column }} as double) as side_total
    from {{ ref('int_fantasy__matchup_side_totals') }}
    {{ 'union all' if not loop.last }}
    {%- endfor %}

)

select
    coalesce(sides.league_id, players.league_id) as league_id,
    coalesce(sides.season, players.season) as season,
    coalesce(sides.matchup_period, players.matchup_period) as matchup_period,
    sides.matchup_id,
    coalesce(sides.fantasy_team_id, players.fantasy_team_id) as fantasy_team_id,
    coalesce(sides.component, players.component) as component,
    players.player_total,
    sides.side_total
from player_components as players
full outer join side_components as sides
    on sides.platform = players.platform
    and sides.league_id = players.league_id
    and sides.season = players.season
    and sides.matchup_period = players.matchup_period
    and sides.fantasy_team_id = players.fantasy_team_id
    and sides.component = players.component
where sides.side_total is null
    or coalesce(players.player_total, 0) <> sides.side_total
