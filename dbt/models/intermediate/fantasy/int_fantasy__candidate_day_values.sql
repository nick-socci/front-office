-- What one day of a candidate's MLB production was worth, on each side he played (#12).
-- The lineup decisions ask what a team could have started instead of whom it did start;
-- this is the price list for that question: one number per (candidate, date, side), on the
-- same scale as the season facts, so a lineup's total is a sum of these.
--
-- THE VALUES FEED A HINDSIGHT-OPPORTUNITY COMPARISON, not a measure of manager skill. They
-- are known only after the games, and nothing here says a manager could have known them.
--
-- Candidate (R1.1): a roster day in a starting slot, or in a bench slot that is not an
-- injured-list slot (is_injured_list_slot, from the espn_lineup_slots seed). A candidate
-- with no MLB id has no row, since there is no line to look up.
--
-- One row per team-day, player and side: `batting` where games_batted > 0, `pitching`
-- where games_pitched > 0, from int_mlb__player_game_days. A candidate who did not play
-- has no row. Both sides of a two-way player's day are valued; which one counts is the
-- slot's business, in the next model. The day's line is the FULL line of that side, not
-- the slot-credited one in int_fantasy__started_player_days, because a bench player has no
-- credited line.
--
-- The arithmetic is fct_player_category_value's at the grain of a day (R1.3). The side's
-- components are unpivoted one query per column of fo_batting_columns / fo_pitching_columns
-- and weighted by int_fantasy__stat_components. The day's kind is `batting`, or `start` /
-- `relief` by fo_pitching_day_kind (ADR 0008), and meets the replacement level of that kind
-- (int_fantasy__replacement_levels) and only the components of its own side. The value over
-- replacement is fo_value_over_replacement with ONE played day, the scaled value
-- fo_scaled_value with the row of int_fantasy__category_scales. The scales are LEFT-joined,
-- as in the season fact, so a missing, null or zero scale is worth 0 by the macro's rules
-- instead of dropping a category. Every scored category of the side contributes, even one in
-- which the day's components are all zero: it still charges the replacement level, exactly
-- as the season fact does for a played day. A side on which the league-season scores no
-- category (a league with pitcher slots but no pitching categories) is worth 0, an empty
-- sum, and still has its row: he played, so he is an option and counts toward the
-- played-starter floor of R3.1. That 0 is not the NULL below, which is a side WITH scored
-- categories and an unknown level.
--
-- day_value is the scaled values summed in category order (a sum of doubles is only
-- reproducible in a fixed order, #28), and NULL if any is null (R1.4): a null replacement
-- level means unknown, and a plain sum would skip it and report a partial value as complete.
-- The singular test candidate_day_values_add_back_to_season_value holds the started days'
-- values to fct_player_season_value.total_value (R1.5).
--
-- WHAT THE COMPARISON BUILT ON THESE IS (ADR 0037, ADR 0038). The optimal lineup downstream
-- follows the rule of R3.1: a starter who played is replaced only by another player who
-- played; injured-list slots are not candidates, which is why they have no row here; a tie
-- keeps the actual lineup. A day value itself rests on no eligibility: where a player could
-- have started is ESPN's eligibility as fetched, not of the day, and enters in
-- int_fantasy__lineup_options. The league's limit on pitcher starts is not applied anywhere.

{{ config(materialized='table') }}

{%- set batting_columns = fo_batting_columns() %}
{%- set pitching_columns = fo_pitching_columns() %}
{%- set day_keys = ['platform', 'league_id', 'season', 'scoring_date', 'fantasy_team_id', 'platform_player_id', 'side'] %}

with candidates as (

    select
        days.platform,
        days.league_id,
        days.season,
        days.scoring_date,
        days.fantasy_team_id,
        days.platform_player_id,
        days.mlbam_player_id
    from {{ ref('int_fantasy__roster_days') }} as days
    inner join {{ ref('espn_lineup_slots') }} as slots
        on slots.lineup_slot_id = days.roster_slot_id
    where
        days.mlbam_player_id is not null
        and (days.is_started or (days.slot_role = 'bench' and not slots.is_injured_list_slot))

),

-- One row per candidate and side he played, with that side's full line and the day's kind.
played_sides as (

    select
        candidates.*,
        'batting' as side,
        'batting' as day_kind,
        {%- for column in batting_columns + pitching_columns %}
        stats.{{ column }}{% if not loop.last %},{% endif %}
        {%- endfor %}
    from candidates
    inner join {{ ref('int_mlb__player_game_days') }} as stats
        on stats.mlbam_player_id = candidates.mlbam_player_id
        and stats.game_date = candidates.scoring_date
    where stats.games_batted > 0

    union all

    select
        candidates.*,
        'pitching' as side,
        {{ fo_pitching_day_kind('stats.games_pitched', 'stats.games_started') }} as day_kind,
        {%- for column in batting_columns + pitching_columns %}
        stats.{{ column }}{% if not loop.last %},{% endif %}
        {%- endfor %}
    from candidates
    inner join {{ ref('int_mlb__player_game_days') }} as stats
        on stats.mlbam_player_id = candidates.mlbam_player_id
        and stats.game_date = candidates.scoring_date
    where stats.games_pitched > 0

),

-- One row per (day, component): the day's total of the component, one query per column.
-- A side unpivots only its own columns, so a day meets only the components of its own side.
day_components as (

    {%- for column in batting_columns %}
    select
        {%- for key in day_keys %}
        {{ key }},
        {%- endfor %}
        day_kind,
        '{{ column }}' as component,
        cast(coalesce({{ column }}, 0) as double) as component_total
    from played_sides
    where side = 'batting'
    union all
    {%- endfor %}
    {%- for column in pitching_columns %}
    select
        {%- for key in day_keys %}
        {{ key }},
        {%- endfor %}
        day_kind,
        '{{ column }}' as component,
        cast(coalesce({{ column }}, 0) as double) as component_total
    from played_sides
    where side = 'pitching'
    {{- '\n    union all' if not loop.last }}
    {%- endfor %}

),

-- The weighted sums per (day, category, part): what the day did, and what a replacement
-- would have done in a day of that kind. A null level anywhere makes the replacement null.
day_parts as (

    select
        {%- for key in day_keys %}
        components.{{ key }},
        {%- endfor %}
        rules.stat_key as category_key,
        rules.part,
        sum(rules.weight * components.component_total) as part_total,
        case
            when bool_or(levels.level_per_played_day is null) then null
            else sum(rules.weight * levels.level_per_played_day order by rules.component)
        end as part_replacement
    from day_components as components
    inner join {{ ref('int_fantasy__stat_components') }} as rules
        on rules.platform = components.platform
        and rules.component = components.component
    left join {{ ref('int_fantasy__replacement_levels') }} as levels
        on levels.platform = components.platform
        and levels.league_id = components.league_id
        and levels.season = components.season
        and levels.component = components.component
        and levels.day_kind = components.day_kind
    group by
        {%- for key in day_keys %}
        components.{{ key }},
        {%- endfor %}
        rules.stat_key,
        rules.part

),

day_parts_pivoted as (

    select
        {%- for key in day_keys %}
        {{ key }},
        {%- endfor %}
        category_key,
        bool_or(part = 'denominator') as is_rate,
        max(part_total) filter (where part = 'numerator') as numerator,
        max(part_total) filter (where part = 'denominator') as denominator,
        max(part_replacement) filter (where part = 'numerator') as replacement_numerator,
        max(part_replacement) filter (where part = 'denominator') as replacement_denominator
    from day_parts
    group by
        {%- for key in day_keys %}
        {{ key }},
        {%- endfor %}
        category_key

),

-- One row per (day, scored category of its side) with the scaled value of that one day.
day_category_values as (

    select
        {%- for key in day_keys %}
        parts.{{ key }},
        {%- endfor %}
        parts.category_key,
        {{ fo_scaled_value(
            fo_value_over_replacement(
                'parts.numerator', 'parts.denominator', '1',
                'parts.replacement_numerator', 'parts.replacement_denominator', 'categories.is_lower_better'
            ),
            '1', 'scales.margin_scale', 'scales.side_denominator', 'parts.is_rate'
        ) }} as scaled_value
    from day_parts_pivoted as parts
    inner join {{ ref('int_fantasy__categories') }} as categories
        on categories.platform = parts.platform
        and categories.league_id = parts.league_id
        and categories.season = parts.season
        and categories.category_key = parts.category_key
    left join {{ ref('int_fantasy__category_scales') }} as scales
        on scales.platform = parts.platform
        and scales.league_id = parts.league_id
        and scales.season = parts.season
        and scales.category_key = parts.category_key

),

day_values as (

    select
        {%- for key in day_keys %}
        {{ key }},
        {%- endfor %}
        case
            when count(*) filter (where scaled_value is null) > 0 then null
            else sum(scaled_value order by category_key)
        end as day_value
    from day_category_values
    group by
    {%- for key in day_keys %}
        {{ key }}{% if not loop.last %},{% endif %}
    {%- endfor %}

)

select
    {%- for key in day_keys %}
    played_sides.{{ key }},
    {%- endfor %}
    played_sides.mlbam_player_id,
    played_sides.day_kind,
    -- No day_values row means the league-season scores no category on this side: an empty
    -- sum, worth 0. A row with a null day_value is a different thing (R1.4) and stays null.
    case when day_values.side is null then 0 else day_values.day_value end as day_value
from played_sides
left join day_values
    on day_values.platform = played_sides.platform
    and day_values.league_id = played_sides.league_id
    and day_values.season = played_sides.season
    and day_values.scoring_date = played_sides.scoring_date
    and day_values.fantasy_team_id = played_sides.fantasy_team_id
    and day_values.platform_player_id = played_sides.platform_player_id
    and day_values.side = played_sides.side
