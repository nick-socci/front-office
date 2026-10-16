-- The league and season a response was filed under agree with the ones its payload names.
--
-- fo_espn_latest picks the newest response per league and season from the partitions the
-- loader stored (the folder the capture was landed in), while the staging models read
-- league and season from the payload itself. A capture landed under the wrong folder
-- would therefore be attributed to one league-season by the selection and to another by
-- the model, and nothing else would notice: both are well-formed. This returns every such
-- response.
--
-- Read from the endpoints' capture views. The roster view gives `id` and `seasonId` as
-- fields of their own, and this reads nothing else of it: its `teams` never cross the
-- query (rule 1: these payloads are megabytes). The other three endpoints are small, and
-- their payload is read for the two keys.

with responses as (

    -- Every landed response of these endpoints, not only the latest of each league-season:
    -- a misfiled capture is wrong whether or not a newer one hides it (R2.3).
    select
        'roster' as endpoint,
        partitions,
        id as payload_league_id,
        seasonId as payload_season
    from {{ ref('stg_raw__espn_roster') }}

    {% for endpoint in ['settings', 'teams', 'matchups'] %}
    union all

    select
        '{{ endpoint }}' as endpoint,
        partitions,
        {{ fo_json_text('payload', '$.id') }} as payload_league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as payload_season
    from {{ ref('stg_raw__espn_' ~ endpoint) }}
    {% endfor %}

),

header as (

    select
        endpoint,
        {{ fo_json_text('partitions', '$.league_id') }} as partition_league_id,
        cast({{ fo_json_int('partitions', '$.season') }} as integer) as partition_season,
        payload_league_id,
        payload_season
    from responses

)

select *
from header
where
    partition_league_id is distinct from payload_league_id
    or partition_season is distinct from payload_season
