-- One row per (matchup period, scoring period): which days a head-to-head matchup covers.
--
-- A categories matchup is scored over a span of days, so nothing above staging can join
-- ESPN's matchup results to daily rosters or MLB game logs without this bridge.
--
-- The mapping is not in the settings payload in usable form -- `scheduleSettings.
-- matchupPeriods` reports {"1": [1], "2": [2], ...} for this league, which is the weekly
-- period type talking about itself, not about scoring days. The real mapping is implicit
-- in each matchup side's `pointsByScoringPeriod`, an object keyed by scoring period:
-- {"69": 12.0, "70": 8.0, ...}. Here the KEYS are the fact and the values are ignored,
-- which is why this reads json_keys rather than unnesting an array.
--
-- Matchup periods are NOT all the same length in this league: period 1 covers 12 days
-- (the opening stretch) and period 15 covers 14 (the All-Star break folded in); the rest
-- cover 7. Downstream code must take the span from this model and never assume a week.
--
-- Both sides are read and the result deduplicated, because a playoff bye has an empty
-- `away` object -- see stg_espn__matchups.

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

period_keys as (

    -- One branch per side, so every JSON path is a constant.
    {% for side in ['home', 'away'] %}
    select
        league_id,
        season,
        fetched_at,
        {{ fo_json_int('matchup', '$.matchupPeriodId') }} as matchup_period,
        unnest(
            {{ fo_json_keys('matchup', '$.' ~ side ~ '.pointsByScoringPeriod') }}
        ) as scoring_period_key
    from matchups
    where {{ fo_json_exists('matchup', '$.' ~ side ~ '.pointsByScoringPeriod') }}
    {{ 'union all' if not loop.last }}
    {% endfor %}

)

select distinct
    league_id,
    season,
    matchup_period,
    try_cast(scoring_period_key as bigint) as scoring_period,
    {{ fo_parse_fetched_at() }} as fetched_at
from period_keys
