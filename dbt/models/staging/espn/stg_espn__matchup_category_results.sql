-- One row per (matchup, team, stat): the category score and whether it was won.
--
-- This is where a categories league is actually decided. Two things to know:
--
-- * scoreByStat carries MORE than the scored categories -- 24 keys for a league that
--   scores 17 -- because ESPN also reports the components behind ratio categories
--   (at-bats and hits alongside AVG). Those extra rows have result = null and are kept
--   deliberately: they are what makes AVG, ERA and WHIP recomputable from components.
-- * stat 34 is stored as outs but displayed as IP; see the espn_stat_ids seed.
--
-- Each matchup's JSON is small (~2 KB), so carrying it through the unnest is fine here.
-- The same shape over roster payloads is what exhausted memory in
-- stg_espn__roster_entries -- size is what matters, not the pattern.

with latest as (

    {{ fo_espn_latest('matchups') }}

),

header as (

    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        fetched_at,
        {{ fo_json_array('payload', '$.schedule[*]') }} as schedule
    from latest

),

matchups as (

    select
        league_id,
        season,
        fetched_at,
        matchup
    from header
    {{ fo_unnest('header.schedule', 'matchup') }}

),

stat_keys as (

    -- One branch per side, so every JSON path is a constant. A bye has an empty `away`
    -- object, whose teamId filter drops it, as before. Keys and values are unnested
    -- together, so each stat_key stays paired with its own stat_value and no path is
    -- built from a key.
    {% for side in ['home', 'away'] %}
    {%- set score_by_stat = '$.' ~ side ~ '.cumulativeScore.scoreByStat' %}
    -- stat_key and stat_value are the names fo_unnest_pair gives the two unnested values.
    -- What they would be qualified with differs by warehouse, so they stay bare.
    select
        matchups.league_id,
        matchups.season,
        matchups.fetched_at,
        matchups.matchup,
        '{{ side }}' as side,
        {{ fo_json_int('matchups.matchup', '$.' ~ side ~ '.teamId') }} as team_id,
        stat_key,  -- noqa: RF02
        stat_value  -- noqa: RF02
    from matchups
    {{ fo_unnest_pair(
        fo_json_keys('matchups.matchup', score_by_stat), 'stat_key',
        fo_json_values('matchups.matchup', score_by_stat), 'stat_value'
    ) }}
    where {{ fo_json_string('matchups.matchup', '$.' ~ side ~ '.teamId') }} is not null
    {{ 'union all' if not loop.last }}
    {% endfor %}

),

results as (

    select
        league_id,
        season,
        fetched_at,
        side,
        stat_key,
        team_id,
        {{ fo_json_int('matchup', '$.id') }} as matchup_id,
        {{ fo_json_int('matchup', '$.matchupPeriodId') }} as matchup_period,
        {{ fo_safe_cast(fo_json_string('stat_value', '$.score'), fo_type_float()) }} as score,
        {{ fo_json_text('stat_value', '$.result') }} as result
    from stat_keys

)

select
    results.league_id,
    results.season,
    results.matchup_id,
    results.matchup_period,
    results.team_id,
    results.side,
    {{ fo_safe_cast('results.stat_key', 'bigint') }} as stat_id,
    stats.stat_abbrev,
    stats.display_label,
    results.score,
    results.result,
    -- A category the league scores has a win/loss/tie; the rest are the components
    -- ESPN reports alongside them.
    results.result is not null as is_scored_category,
    {{ fo_parse_fetched_at('results.fetched_at') }} as fetched_at
from results
left join {{ ref('espn_stat_ids') }} as stats
    on stats.stat_id = {{ fo_safe_cast('results.stat_key', 'bigint') }}
