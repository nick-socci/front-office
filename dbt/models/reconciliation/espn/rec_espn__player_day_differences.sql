-- One row per (started player-day, stat) where our credited number and ESPN's own
-- per-game lines disagree: the evidence behind every matchup residual.
--
-- Compared stat by stat for the ESPN stats that are exactly one credited component
-- (H is hits, ER is earned_runs; AVG and ERA are not compared here, being built from
-- these). Only the side of the day the slot credits is compared: ESPN's line for a
-- pitcher includes any at-bats, which a pitcher slot never scores.
--
-- ESPN's game lines are summed per day, so a doubleheader is compared whole. A started
-- player with no ESPN line that day is compared against zero.
--
-- Rows are kept only where the two numbers differ, and each says what its inputs were.
-- input_status is the started player-day's (#25), and status follows from it:
--   difference  played or verified_off: every game that date is loaded, so the gap is
--               real. That includes a verified_off day for which ESPN has a line: we say
--               he did not play and ESPN says he did, and that is what this table is for.
--   unverified  missing_boxscore or unresolved_player: our number may be zero only because
--               the boxscore is not loaded. The row is kept so the comparison is visible,
--               and it is evidence of nothing; readers filter on status = 'difference'.
-- A row needs a gap to exist, so an unverified day whose numbers happen to agree has none:
-- completeness is reported by int_fantasy__started_player_days_inputs_all_verified and
-- rec_espn__every_side_is_verified, not by the absence of rows here (ADR 0032).
--
-- On the 2026 data every row here is a difference, an official scoring change ESPN never
-- applied (MLB's boxscore, fetched later, has the corrected call).

{{ config(materialized='table') }}

with single_component_stats as (

    -- ESPN stats that are one credited component, unscaled: the bridge from a component
    -- column to ESPN's stat id.
    select
        stat_key as stat_id,
        max(component) as component
    from {{ ref('int_fantasy__stat_components') }}
    where platform = 'espn'
    group by stat_key
    having count(*) = 1
       and max(part) = 'numerator'
       and max(weight) = 1

),

credited as (

    -- Each slot role's side of the day, one row per component.
    {%- set credited_columns = [] %}
    {%- for column in fo_batting_columns() %}{% do credited_columns.append(('hitter', column)) %}{% endfor %}
    {%- for column in fo_pitching_columns() %}{% do credited_columns.append(('pitcher', column)) %}{% endfor %}
    {%- for role, column in credited_columns %}
    select
        league_id,
        season,
        scoring_date,
        scoring_period,
        fantasy_team_id,
        platform_player_id,
        player_name,
        roster_slot,
        input_status,
        '{{ column }}' as component,
        cast({{ column }} as double) as our_value
    from {{ ref('int_fantasy__started_player_days') }}
    where platform = 'espn'
      and slot_role = '{{ role }}'
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

espn_days as (

    select
        league_id,
        season,
        scoring_period,
        espn_player_id,
        stat_id,
        sum(stat_value) as espn_value,
        count(distinct espn_game_id) as espn_games
    from {{ ref('stg_espn__player_game_stats') }}
    group by league_id, season, scoring_period, espn_player_id, stat_id

),

compared as (

    select
        credited.*,
        stats.stat_id,
        coalesce(espn_days.espn_value, 0) as espn_value,
        espn_days.espn_games
    from credited
    inner join single_component_stats as stats
        on stats.component = credited.component
    left join espn_days
        on espn_days.league_id = credited.league_id
        and espn_days.season = credited.season
        and espn_days.scoring_period = credited.scoring_period
        and espn_days.espn_player_id = credited.platform_player_id
        and espn_days.stat_id = stats.stat_id

)

select
    sides.matchup_id,
    compared.league_id,
    compared.season,
    compared.fantasy_team_id,
    compared.scoring_date,
    compared.scoring_period,
    compared.platform_player_id,
    compared.player_name,
    compared.roster_slot,
    compared.stat_id,
    compared.component,
    compared.our_value,
    compared.espn_value,
    compared.our_value - compared.espn_value as difference,
    compared.espn_games,
    compared.input_status,
    case
        when compared.input_status in ('played', 'verified_off') then 'difference'
        else 'unverified'
    end as status
from compared
inner join {{ ref('int_fantasy__matchup_periods') }} as periods
    on periods.platform = 'espn'
    and periods.league_id = compared.league_id
    and periods.season = compared.season
    and periods.scoring_date = compared.scoring_date
inner join {{ ref('int_fantasy__matchup_sides') }} as sides
    on sides.platform = 'espn'
    and sides.league_id = compared.league_id
    and sides.season = compared.season
    and sides.matchup_period = periods.matchup_period
    and sides.fantasy_team_id = compared.fantasy_team_id
where abs(compared.our_value - compared.espn_value) > 1e-9
