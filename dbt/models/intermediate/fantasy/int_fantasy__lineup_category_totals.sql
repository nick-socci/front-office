-- Each matchup side's value in each scored category under the lineup it started and under the
-- best lineup it could have fielded (#12, R5): one row per side, category and lineup.
--
-- THE OPTIMAL ROWS ARE HINDSIGHT OPPORTUNITY, NOT A MEASURE OF MANAGER SKILL. They follow the
-- rule that a starter who played is replaced only by another player who played (ADR 0037), so
-- the difference from the actual rows counts choices between players and not days that went
-- badly. The lineups rest on ESPN's eligibility as fetched (ADR 0038): as of the fetch, not of
-- the day, so a move that was not legal on the day can look legal.
--
-- One path for both lineups. Each lineup is a set of (team-day, player, slot role); a player is
-- credited by the role of the slot the lineup puts him in, as int_fantasy__started_player_days
-- does (a hitter slot his batting, a pitcher slot his pitching), his MLB line is joined on
-- the date, the credited components are summed over the dates of the side's matchup period as
-- int_fantasy__matchup_side_totals does, and each category is its numerator over its
-- denominator by int_fantasy__stat_components as int_fantasy__matchup_stat_values does: a count
-- is its numerator, a zero denominator gives a null value. The sums name no lineup. The one
-- statement that does is the null of R5.4, applied after them.
--
-- WHY A MODEL AND NOT CTES OF THE MART. A test reads only what a model selects. The actual
-- rows must equal fct_matchup_category_scores.team_value (the singular test
-- lineup_category_totals_reproduce_the_actual_totals), and that is what proves the path the
-- optimal rows came through. A mart that recomputed the totals in CTEs could not be tested
-- against the fact it must match, and a column copied from the fact would prove nothing.
--
-- The spine is every side of int_fantasy__matchup_side_totals crossed with its league-season's
-- scored categories and the two lineups, so a side whose lineup credits nothing still has its
-- rows (components zero). Those models are what the fact is built from, so the rows are the
-- fact's, and no intermediate model reads a mart.
--
-- UNVALUED (R5.4, R3.5). An optimal row's numerator, denominator and value are null when any
-- team-day of the side's matchup period is unvalued: it has an option whose value is null in
-- int_fantasy__lineup_options, the rule fct_lineup_decisions.is_unvalued uses. The options are
-- read rather than that mart so that an intermediate model does not rest on a mart. Such a
-- team-day has no optimal lineup (the solver leaves it unsolved), so its sum would be a part
-- reported as the whole. A day with no assigned player, or with no options at all, is not
-- unvalued: it adds nothing to the sums and nulls nothing.
--
-- The lineup maximises summed day value over all categories, not any one of them, so an
-- optimal row can be worse than its actual row. Injured-list slots are not candidates, and
-- the league's limit on pitcher starts is not applied (ADR 0037).

{{ config(materialized='table') }}

{%- set stat_columns = fo_batting_columns() + fo_pitching_columns() %}
{%- set side_columns = [
    'platform', 'league_id', 'season', 'matchup_id', 'matchup_period', 'fantasy_team_id',
] %}

with lineup_player_days as (

    select
        'actual' as lineup,
        platform,
        league_id,
        season,
        scoring_date,
        fantasy_team_id,
        mlbam_player_id,
        slot_role
    from {{ ref('int_fantasy__roster_days') }}
    where is_started

    union all

    select
        'optimal' as lineup,
        lineups.platform,
        lineups.league_id,
        lineups.season,
        lineups.scoring_date,
        lineups.fantasy_team_id,
        days.mlbam_player_id,
        slots.slot_role
    from {{ ref('int_fantasy__optimal_lineups') }} as lineups
    inner join {{ ref('int_fantasy__lineup_slots') }} as slots
        on slots.platform = lineups.platform
        and slots.league_id = lineups.league_id
        and slots.season = lineups.season
        and slots.lineup_slot_id = lineups.lineup_slot_id
    inner join {{ ref('int_fantasy__roster_days') }} as days
        on days.platform = lineups.platform
        and days.league_id = lineups.league_id
        and days.season = lineups.season
        and days.scoring_date = lineups.scoring_date
        and days.fantasy_team_id = lineups.fantasy_team_id
        and days.platform_player_id = lineups.platform_player_id

),

credited_days as (

    select
        player_days.lineup,
        player_days.platform,
        player_days.league_id,
        player_days.season,
        player_days.scoring_date,
        player_days.fantasy_team_id,
        {%- for column in fo_batting_columns() %}
        case when player_days.slot_role = 'hitter' then coalesce(stats.{{ column }}, 0) else 0 end as {{ column }},
        {%- endfor %}
        {%- for column in fo_pitching_columns() %}
        case when player_days.slot_role = 'pitcher' then coalesce(stats.{{ column }}, 0) else 0 end as {{ column }}
            {{- ',' if not loop.last }}
        {%- endfor %}
    from lineup_player_days as player_days
    inner join {{ ref('int_mlb__player_game_days') }} as stats
        on stats.mlbam_player_id = player_days.mlbam_player_id
        and stats.game_date = player_days.scoring_date

),

sides as (

    select {{ side_columns | join(', ') }}
    from {{ ref('int_fantasy__matchup_side_totals') }}

),

side_totals as (

    select
        {%- for column in side_columns %}
        sides.{{ column }},
        {%- endfor %}
        lineups.lineup,
        {%- for column in stat_columns %}
        coalesce(sum(credited.{{ column }}), 0) as {{ column }}{% if not loop.last %},{% endif %}
        {%- endfor %}
    from sides
    cross join (values ('actual'), ('optimal')) as lineups (lineup)
    left join {{ ref('int_fantasy__matchup_periods') }} as periods
        on periods.platform = sides.platform
        and periods.league_id = sides.league_id
        and periods.season = sides.season
        and periods.matchup_period = sides.matchup_period
    left join credited_days as credited
        on credited.lineup = lineups.lineup
        and credited.platform = periods.platform
        and credited.league_id = periods.league_id
        and credited.season = periods.season
        and credited.scoring_date = periods.scoring_date
        and credited.fantasy_team_id = sides.fantasy_team_id
    group by
        {%- for column in side_columns %}
        sides.{{ column }},
        {%- endfor %}
        lineups.lineup

),

components as (

    {%- for column in stat_columns %}
    select
        {{ side_columns | join(', ') }},
        lineup,
        '{{ column }}' as component,
        cast({{ column }} as double) as component_value
    from side_totals
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

parts as (

    select
        {%- for column in side_columns %}
        components.{{ column }},
        {%- endfor %}
        components.lineup,
        rules.stat_key,
        rules.part,
        sum(rules.weight * components.component_value) as part_value
    from components
    inner join {{ ref('int_fantasy__stat_components') }} as rules
        on rules.platform = components.platform
        and rules.component = components.component
    group by
        {%- for column in side_columns %}
        components.{{ column }},
        {%- endfor %}
        components.lineup,
        rules.stat_key,
        rules.part

),

stat_values as (

    select
        {{ side_columns | join(',\n        ') }},
        lineup,
        stat_key,
        max(part_value) filter (where part = 'numerator') as numerator,
        max(part_value) filter (where part = 'denominator') as denominator,
        case
            when count(*) filter (where part = 'denominator') = 0
                then max(part_value) filter (where part = 'numerator')
            else
                max(part_value) filter (where part = 'numerator')
                / nullif(max(part_value) filter (where part = 'denominator'), 0)
        end as stat_value
    from parts
    group by
        {{ side_columns | join(',\n        ') }},
        lineup,
        stat_key

),

unvalued_sides as (

    select distinct
        sides.platform,
        sides.league_id,
        sides.season,
        sides.matchup_id,
        sides.fantasy_team_id
    from sides
    inner join {{ ref('int_fantasy__matchup_periods') }} as periods
        on periods.platform = sides.platform
        and periods.league_id = sides.league_id
        and periods.season = sides.season
        and periods.matchup_period = sides.matchup_period
    inner join {{ ref('int_fantasy__lineup_options') }} as options
        on options.platform = periods.platform
        and options.league_id = periods.league_id
        and options.season = periods.season
        and options.scoring_date = periods.scoring_date
        and options.fantasy_team_id = sides.fantasy_team_id
    where options.option_value is null

)

select
    stat_values.platform,
    stat_values.league_id,
    stat_values.season,
    stat_values.matchup_id,
    stat_values.matchup_period,
    stat_values.fantasy_team_id,
    categories.category_key,
    stat_values.lineup,
    -- The one statement that names a lineup: an unvalued week has no optimal total (R5.4).
    case when stat_values.lineup = 'optimal' and unvalued_sides.matchup_id is not null
        then null else stat_values.numerator end as numerator,
    case when stat_values.lineup = 'optimal' and unvalued_sides.matchup_id is not null
        then null else stat_values.denominator end as denominator,
    case when stat_values.lineup = 'optimal' and unvalued_sides.matchup_id is not null
        then null else stat_values.stat_value end as category_value
from stat_values
inner join {{ ref('int_fantasy__categories') }} as categories
    on categories.platform = stat_values.platform
    and categories.league_id = stat_values.league_id
    and categories.season = stat_values.season
    and categories.category_key = stat_values.stat_key
left join unvalued_sides
    on unvalued_sides.platform = stat_values.platform
    and unvalued_sides.league_id = stat_values.league_id
    and unvalued_sides.season = stat_values.season
    and unvalued_sides.matchup_id = stat_values.matchup_id
    and unvalued_sides.fantasy_team_id = stat_values.fantasy_team_id
