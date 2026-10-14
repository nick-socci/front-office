-- One row per (scoring period, matchup period): which matchup period ESPN marked in the
-- response it gave for that scoring period.
--
-- A past season's matchups carry no `pointsByScoringPeriod` (the mapping that
-- stg_espn__matchup_periods reads), so its days cannot be assigned to matchups from the
-- matchups capture. ADR 0055 found another signal: asked for one scoring period with
-- views mMatchupScore and mScoreboard, ESPN puts `rosterForCurrentScoringPeriod` on the
-- sides of the matchups of exactly one matchup period, the one that day belongs to, and
-- on no others. One request per scoring period (`backfill espn --only matchup-days`)
-- therefore maps every day.
--
-- Only the EXISTENCE of that key is read. The roster inside it is never selected: these
-- responses also hold `teams` and `settings`, which carry member data.
--
-- The scoring period comes from the request (`scoringPeriodId`), not from the payload:
-- the marker only means something relative to the day that was asked for, and a test
-- checks that ESPN answered that day.
--
-- Rule 1: `payload` is projected away in `header` before the unnest, which runs beside
-- the small identifier columns only, one constant-path branch per side, as in
-- stg_espn__matchup_periods. A playoff bye has an empty `away`, which simply has no key.
-- `select distinct` gives one row however many sides and matchups carry the marker.
--
-- Built a season at a time. DuckDB holds every parsed payload of a run at once, so dbt
-- runs this model once per calendar year (microbatch), reading one season's captures
-- through stg_raw__season_responses. Every build redoes every season. On BigQuery it is a
-- plain table (spec 0143, ADRs 0058 to 0060). season_start, the column dbt batches on, is
-- small and is carried beside the other header columns; the payload is still dropped in
-- `header`. It is a function of the capture's season, so it cannot split a row of the
-- `select distinct` below.
--
-- In CI there are no matchup_days captures, so this model is empty there; its logic is
-- covered by unit tests.

{{ config(
    materialized=('incremental' if target.type == 'duckdb' else 'table'),
    incremental_strategy=('microbatch' if target.type == 'duckdb' else none),
    event_time='season_start',
    batch_size='year',
    begin=var('first_season_start'),
    lookback=fo_batches_back_to_first_season(),
    concurrent_batches=false,
    on_schema_change='fail'
) }}

with latest as (

    {{ fo_espn_latest(
        'matchup_days',
        extra_partition='scoringPeriodId',
        relation=ref('stg_raw__season_responses')
    ) }}

),

header as (

    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        {{ fo_request_param('request_key', 'scoringPeriodId') }} as scoring_period,
        fetched_at,
        season_start,
        {{ fo_json_array('payload', '$.schedule[*]') }} as schedule
    from latest

),

matchups as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        season_start,
        matchup
    from header
    {{ fo_unnest('header.schedule', 'matchup') }}

),

marked as (

    -- One branch per side, so every JSON path is a constant.
    {% for side in ['home', 'away'] %}
    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        season_start,
        {{ fo_json_int('matchup', '$.matchupPeriodId') }} as matchup_period
    from matchups
    where {{ fo_json_exists('matchup', '$.' ~ side ~ '.rosterForCurrentScoringPeriod') }}
    {{ 'union all' if not loop.last }}
    {% endfor %}

)

select distinct
    league_id,
    season,
    scoring_period,
    matchup_period,
    {{ fo_parse_fetched_at() }} as fetched_at,
    season_start
from marked
