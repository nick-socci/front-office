-- One row per (player, fantasy team): how many category results, and how many matchups,
-- actually went the team's way because of him. Every matchup he had a started day in is
-- scored again with his production taken out and replacement production put in its place,
-- and the results that change are counted.
--
-- This is a check, not a valuation (spec 0089). The value facts turn production into
-- "matchup margins" by a linear scale; this model uses no scale at all, only the rules
-- that score a category and the same replacement level. If the value facts are sound, a
-- unit of total_value buys the same number of real category wins whoever it belongs to:
-- about 0.40, because for a margin that is normal with the scale as its root mean square
-- a small contribution of x scale units moves the expected result by x / sqrt(2 * pi).
-- rec_fantasy__category_wins_by_group measures that per group of players, and
-- values_track_rescored_category_wins holds the facts to it. It is what showed, in 2026,
-- that the arithmetic was even-handed between starters and hitters and that the tilt
-- toward pitching was in the level a start was measured against (ADR 0029).
--
-- It lives with the reconciliation models because it sets our numbers against an
-- independent account of the same thing. It is not a mart: one player's figures are
-- noisy (a category flips or it does not), and it is read in aggregate.
--
-- WHICH MATCHUPS. Those fct_matchup_results gives a winner, with has_unverified_inputs
-- false: a result resting on a missing boxscore or an unresolved player is not a result
-- to score again. Playoffs included, since the values being checked count every started
-- day. A matchup in progress has a winner so far and is scored again as it stands.
--
-- THE SWAP, in components (AGENTS.md rule 4). The side's totals, minus the pair's started
-- production in the matchup, plus what replacement is expected to produce in the pair's
-- played days of each kind (a batting day, a start, a relief day: ADR 0008), by the
-- levels of int_fantasy__replacement_levels. Every scored category is then computed for
-- that side by the rules of int_fantasy__stat_components and judged against the
-- opponent's actual value, at 9 decimal places as fct_matchup_category_scores does.
--
-- WHOLE NUMBERS. Replacement's expected production is fractional: 0.25 wins a start, a
-- quarter of a steal a week. Real totals are whole, and many categories are close (14% of
-- stolen-base results are ties), so a fraction added to one side breaks every tie in its
-- category the same way. Measured in 2026, that alone moved the slopes from 0.41, 0.39
-- and 0.39 to 0.36, 0.32 and 0.46. So each expected amount is rounded down, and up with
-- probability equal to its fraction, twenty times, and the results averaged. The draw is
-- the first 32 bits of an MD5 of the pair, the matchup, the component and the draw's
-- number: the same on every build and on every version of the engine. Components are
-- drawn independently, so a draw is not a realistic box score; it does not need to be.
--
-- A NULL LEVEL (an empty pool) for a kind of day the pair played in such a matchup makes
-- both measures null for the pair, as the value facts give it a null value, and the row
-- stays. A category undefined for the swapped side in a draw is left out of that draw.
--
-- matchup_wins_added uses the league's rule as fct_matchup_results has it: more categories
-- won than lost is a win, equal is a tie. A win counts 1 and a tie one half, throughout.

{{ config(materialized='table') }}

{%- set draws = 20 %}
{%- set batting_columns = fo_batting_columns() %}
{%- set pitching_columns = fo_pitching_columns() %}
{%- set pair_keys = [
    'platform',
    'league_id',
    'season',
    'matchup_id',
    'fantasy_team_id',
    'platform_player_id'
] %}

with rescorable_sides as (

    select
        sides.platform,
        sides.league_id,
        sides.season,
        sides.matchup_id,
        sides.matchup_period,
        sides.fantasy_team_id,
        sides.opponent_team_id
    from {{ ref('int_fantasy__matchup_sides') }} as sides
    inner join {{ ref('fct_matchup_results') }} as results
        on results.platform = sides.platform
        and results.league_id = sides.league_id
        and results.season = sides.season
        and results.matchup_id = sides.matchup_id
    where
        results.winner is not null
        and not results.has_unverified_inputs

),

-- The pair's started production in each matchup, and its played days of each kind.
pair_matchups as (

    select
        sides.platform,
        sides.league_id,
        sides.season,
        sides.matchup_id,
        sides.fantasy_team_id,
        sides.opponent_team_id,
        days.platform_player_id,
        count(*) filter (
            where days.slot_role = 'hitter' and days.games_batted > 0
        ) as batting_days,
        count(*) filter (
            where days.slot_role = 'pitcher'
            and {{ fo_pitching_day_kind('days.games_pitched', 'days.games_started') }} = 'start'
        ) as start_days,
        count(*) filter (
            where days.slot_role = 'pitcher'
            and {{ fo_pitching_day_kind('days.games_pitched', 'days.games_started') }} = 'relief'
        ) as relief_days,
        {%- for column in batting_columns + pitching_columns %}
        sum(coalesce(days.{{ column }}, 0)) as {{ column }}{% if not loop.last %},{% endif %}
        {%- endfor %}
    from {{ ref('int_fantasy__started_player_days') }} as days
    inner join {{ ref('int_fantasy__matchup_periods') }} as periods
        on periods.platform = days.platform
        and periods.league_id = days.league_id
        and periods.season = days.season
        and periods.scoring_date = days.scoring_date
    inner join rescorable_sides as sides
        on sides.platform = days.platform
        and sides.league_id = days.league_id
        and sides.season = days.season
        and sides.matchup_period = periods.matchup_period
        and sides.fantasy_team_id = days.fantasy_team_id
    group by
        sides.platform,
        sides.league_id,
        sides.season,
        sides.matchup_id,
        sides.fantasy_team_id,
        sides.opponent_team_id,
        days.platform_player_id

),

levels as (

    select
        platform,
        league_id,
        season,
        day_kind,
        component,
        level_per_played_day
    from {{ ref('int_fantasy__replacement_levels') }}

),

-- One row per (pair, matchup, component): what the pair produced, and what replacement is
-- expected to in the same played days. A kind the pair did not play charges nothing,
-- whatever its level; a kind it did play with a null level makes the expectation null.
pair_components as (

    {%- for column in batting_columns %}
    select
        {%- for key in pair_keys %}
        pair_matchups.{{ key }},
        {%- endfor %}
        '{{ column }}' as component,
        pair_matchups.{{ column }}::double as pair_total,
        case
            when pair_matchups.batting_days = 0 then 0
            else pair_matchups.batting_days * batting.level_per_played_day
        end as replacement_expected
    from pair_matchups
    left join levels as batting
        on batting.platform = pair_matchups.platform
        and batting.league_id = pair_matchups.league_id
        and batting.season = pair_matchups.season
        and batting.day_kind = 'batting'
        and batting.component = '{{ column }}'
    union all
    {%- endfor %}
    {%- for column in pitching_columns %}
    select
        {%- for key in pair_keys %}
        pair_matchups.{{ key }},
        {%- endfor %}
        '{{ column }}' as component,
        pair_matchups.{{ column }}::double as pair_total,
        case
            when pair_matchups.start_days = 0 then 0
            else pair_matchups.start_days * starts.level_per_played_day
        end
        + case
            when pair_matchups.relief_days = 0 then 0
            else pair_matchups.relief_days * relief.level_per_played_day
        end as replacement_expected
    from pair_matchups
    left join levels as starts
        on starts.platform = pair_matchups.platform
        and starts.league_id = pair_matchups.league_id
        and starts.season = pair_matchups.season
        and starts.day_kind = 'start'
        and starts.component = '{{ column }}'
    left join levels as relief
        on relief.platform = pair_matchups.platform
        and relief.league_id = pair_matchups.league_id
        and relief.season = pair_matchups.season
        and relief.day_kind = 'relief'
        and relief.component = '{{ column }}'
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

-- A pair is all or nothing: one unknown level leaves the whole pair unmeasured.
unmeasured_pairs as (

    select distinct
        platform,
        league_id,
        season,
        fantasy_team_id,
        platform_player_id
    from pair_components
    where replacement_expected is null

),

side_components as (

    {%- for column in batting_columns + pitching_columns %}
    select
        platform,
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        '{{ column }}' as component,
        {{ column }}::double as side_total
    from {{ ref('int_fantasy__matchup_side_totals') }}
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

draw_numbers as (

    select unnest(range(1, {{ draws + 1 }})) as draw

),

-- The side's totals with the pair swapped for a whole-number draw of replacement.
swapped_components as (

    select
        {%- for key in pair_keys %}
        pair_components.{{ key }},
        {%- endfor %}
        draw_numbers.draw,
        pair_components.component,
        side_components.side_total
        - pair_components.pair_total
        + floor(pair_components.replacement_expected)
        + case
            when (
                '0x' || substr(md5(concat_ws(
                    '|',
                    pair_components.platform,
                    pair_components.league_id,
                    pair_components.season::varchar,
                    pair_components.matchup_id::varchar,
                    pair_components.fantasy_team_id::varchar,
                    pair_components.platform_player_id::varchar,
                    pair_components.component,
                    draw_numbers.draw::varchar
                )), 1, 8)
            )::bigint / 4294967296.0
            < pair_components.replacement_expected - floor(pair_components.replacement_expected)
                then 1
            else 0
        end as swapped_total
    from pair_components
    cross join draw_numbers
    inner join side_components
        on side_components.platform = pair_components.platform
        and side_components.league_id = pair_components.league_id
        and side_components.season = pair_components.season
        and side_components.matchup_id = pair_components.matchup_id
        and side_components.fantasy_team_id = pair_components.fantasy_team_id
        and side_components.component = pair_components.component
    left join unmeasured_pairs
        on unmeasured_pairs.platform = pair_components.platform
        and unmeasured_pairs.league_id = pair_components.league_id
        and unmeasured_pairs.season = pair_components.season
        and unmeasured_pairs.fantasy_team_id = pair_components.fantasy_team_id
        and unmeasured_pairs.platform_player_id = pair_components.platform_player_id
    where unmeasured_pairs.platform_player_id is null

),

scored_rules as (

    select
        categories.platform,
        categories.league_id,
        categories.season,
        categories.category_key,
        categories.is_lower_better,
        rules.part,
        rules.component,
        rules.weight
    from {{ ref('int_fantasy__categories') }} as categories
    inner join {{ ref('int_fantasy__stat_components') }} as rules
        on rules.platform = categories.platform
        and rules.stat_key = categories.category_key

),

-- Each scored category's value for the swapped side, as int_fantasy__matchup_stat_values
-- computes it for a real one.
swapped_values as (

    select
        {%- for key in pair_keys %}
        swapped.{{ key }},
        {%- endfor %}
        swapped.draw,
        scored_rules.category_key,
        scored_rules.is_lower_better,
        case
            when count(*) filter (where scored_rules.part = 'denominator') = 0
                then
                    sum(scored_rules.weight * swapped.swapped_total)
                    filter (where scored_rules.part = 'numerator')
            else
                sum(scored_rules.weight * swapped.swapped_total)
                filter (where scored_rules.part = 'numerator')
                / nullif(
                    sum(scored_rules.weight * swapped.swapped_total)
                    filter (where scored_rules.part = 'denominator'),
                    0
                )
        end as swapped_value
    from swapped_components as swapped
    inner join scored_rules
        on scored_rules.platform = swapped.platform
        and scored_rules.league_id = swapped.league_id
        and scored_rules.season = swapped.season
        and scored_rules.component = swapped.component
    group by
        {%- for key in pair_keys %}
        swapped.{{ key }},
        {%- endfor %}
        swapped.draw,
        scored_rules.category_key,
        scored_rules.is_lower_better

),

actual_values as (

    select
        platform,
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        opponent_team_id,
        stat_key as category_key,
        round(stat_value, 9) as stat_value
    from {{ ref('int_fantasy__matchup_stat_values') }}

),

-- The category's result with the pair and with replacement, against the same opponent.
category_results as (

    select
        {%- for key in pair_keys %}
        swapped.{{ key }},
        {%- endfor %}
        swapped.draw,
        swapped.category_key,
        case
            when team.stat_value = opponent.stat_value then 'TIE'
            when (team.stat_value < opponent.stat_value) = swapped.is_lower_better then 'WIN'
            else 'LOSS'
        end as actual_result,
        case
            when round(swapped.swapped_value, 9) = opponent.stat_value then 'TIE'
            when
                (round(swapped.swapped_value, 9) < opponent.stat_value) = swapped.is_lower_better
                then 'WIN'
            else 'LOSS'
        end as swapped_result
    from swapped_values as swapped
    inner join actual_values as team
        on team.platform = swapped.platform
        and team.league_id = swapped.league_id
        and team.season = swapped.season
        and team.matchup_id = swapped.matchup_id
        and team.fantasy_team_id = swapped.fantasy_team_id
        and team.category_key = swapped.category_key
    inner join actual_values as opponent
        on opponent.platform = team.platform
        and opponent.league_id = team.league_id
        and opponent.season = team.season
        and opponent.matchup_id = team.matchup_id
        and opponent.fantasy_team_id = team.opponent_team_id
        and opponent.category_key = team.category_key
    -- Undefined on any of the three sides: left out of this draw.
    where
        swapped.swapped_value is not null
        and team.stat_value is not null
        and opponent.stat_value is not null

),

matchup_draws as (

    select
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        draw,
        sum(case actual_result when 'WIN' then 1.0 when 'TIE' then 0.5 else 0 end)
        - sum(case swapped_result when 'WIN' then 1.0 when 'TIE' then 0.5 else 0 end)
            as category_wins_added,
        case
            when
                count(*) filter (where actual_result = 'WIN')
                > count(*) filter (where actual_result = 'LOSS') then 1.0
            when
                count(*) filter (where actual_result = 'WIN')
                = count(*) filter (where actual_result = 'LOSS') then 0.5
            else 0
        end
        - case
            when
                count(*) filter (where swapped_result = 'WIN')
                > count(*) filter (where swapped_result = 'LOSS') then 1.0
            when
                count(*) filter (where swapped_result = 'WIN')
                = count(*) filter (where swapped_result = 'LOSS') then 0.5
            else 0
        end as matchup_wins_added
    from category_results
    group by
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        draw

),

measured as (

    select
        platform,
        league_id,
        season,
        fantasy_team_id,
        platform_player_id,
        -- Summed in a fixed order: the last digit of a floating-point sum depends on the
        -- order of its terms, and row order changes from build to build.
        sum(category_wins_added order by matchup_id, draw) / {{ draws }} as category_wins_added,
        sum(matchup_wins_added order by matchup_id, draw) / {{ draws }} as matchup_wins_added
    from matchup_draws
    group by platform, league_id, season, fantasy_team_id, platform_player_id

),

pairs as (

    select
        platform,
        league_id,
        season,
        fantasy_team_id,
        platform_player_id,
        count(*) as matchups_rescored
    from pair_matchups
    group by platform, league_id, season, fantasy_team_id, platform_player_id

)

select
    pairs.platform,
    pairs.league_id,
    pairs.season,
    pairs.platform_player_id,
    pairs.fantasy_team_id,
    pairs.matchups_rescored,
    measured.category_wins_added,
    measured.matchup_wins_added
from pairs
left join measured
    on measured.platform = pairs.platform
    and measured.league_id = pairs.league_id
    and measured.season = pairs.season
    and measured.fantasy_team_id = pairs.fantasy_team_id
    and measured.platform_player_id = pairs.platform_player_id
