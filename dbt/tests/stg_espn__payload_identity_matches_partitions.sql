-- The league and season a response was filed under agree with the ones its payload names.
--
-- fo_espn_latest picks the newest response per league and season from the partitions the
-- loader stored (the folder the capture was landed in), while the staging models read
-- league and season from the payload itself. A capture landed under the wrong folder
-- would therefore be attributed to one league-season by the selection and to another by
-- the model, and nothing else would notice: both are well-formed. This returns every such
-- response.
--
-- Each payload-derived field is computed in its own CTE before the comparison, and
-- `payload` is not carried past it (rule 1: these payloads are megabytes).

with responses as (

    -- Every landed response of these endpoints, not only the latest of each league-season:
    -- a misfiled capture is wrong whether or not a newer one hides it (R2.3).
    select
        endpoint,
        payload,
        {{ fo_json_text('partitions', '$.league_id') }} as league_id,
        {{ fo_json_int('partitions', '$.season') }}::integer as season
    from {{ source('raw', 'api_responses') }}
    where
        source = 'espn'
        and endpoint in ('settings', 'teams', 'roster', 'matchups')

),

header as (

    select
        endpoint,
        league_id as partition_league_id,
        season as partition_season,
        {{ fo_json_text('payload', '$.id') }} as payload_league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as payload_season
    from responses

)

select *
from header
where
    partition_league_id is distinct from payload_league_id
    or partition_season is distinct from payload_season
