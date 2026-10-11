-- A matchup_days response is about the scoring period it was asked for.
--
-- The scoring period of stg_espn__matchup_days comes from the request, because the
-- marker only means something relative to it. If ESPN answered a different period (for
-- example by ignoring `scoringPeriodId` and returning the current one), the marker
-- would be filed under the wrong day and nothing else would notice. Returns each newest
-- capture whose payload `scoringPeriodId` differs from the request's.

with latest as (

    {{ fo_espn_latest('matchup_days', extra_partition='scoringPeriodId') }}

),

header as (

    select
        league_id,
        season,
        {{ fo_request_param('request_key', 'scoringPeriodId') }} as requested_scoring_period,
        {{ fo_json_int('payload', '$.scoringPeriodId') }} as answered_scoring_period
    from latest

)

select *
from header
where requested_scoring_period is distinct from answered_scoring_period
