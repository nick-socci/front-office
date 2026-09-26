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
        unnest(schedule) as matchup
    from header

),

sides as (

    select
        league_id,
        season,
        fetched_at,
        matchup,
        unnest(['home', 'away']) as side
    from matchups

),

stat_keys as (

    select
        league_id,
        season,
        fetched_at,
        matchup,
        side,
        unnest(json_keys(matchup, '$.' || side || '.cumulativeScore.scoreByStat')) as stat_key
    from sides
    where json_extract_string(matchup, '$.' || side || '.teamId') is not null

),

results as (

    select
        league_id,
        season,
        fetched_at,
        side,
        stat_key,
        try_cast(json_extract_string(matchup, '$.id') as bigint) as matchup_id,
        try_cast(json_extract_string(matchup, '$.matchupPeriodId') as bigint) as matchup_period,
        try_cast(json_extract_string(matchup, '$.' || side || '.teamId') as bigint) as team_id,
        try_cast(
            json_extract_string(
                matchup,
                '$.' || side || '.cumulativeScore.scoreByStat.' || stat_key || '.score'
            ) as double
        ) as score,
        nullif(
            json_extract_string(
                matchup,
                '$.' || side || '.cumulativeScore.scoreByStat.' || stat_key || '.result'
            ),
            ''
        ) as result
    from stat_keys

)

select
    results.league_id,
    results.season,
    results.matchup_id,
    results.matchup_period,
    results.team_id,
    results.side,
    try_cast(results.stat_key as bigint) as stat_id,
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
    on stats.stat_id = try_cast(results.stat_key as bigint)
