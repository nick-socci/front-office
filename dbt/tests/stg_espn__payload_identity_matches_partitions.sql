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

with latest as (

    select 'settings' as endpoint, payload, league_id, season
    from ({{ fo_espn_latest('settings') }})

    union all

    select 'teams' as endpoint, payload, league_id, season
    from ({{ fo_espn_latest('teams') }})

    union all

    select 'roster' as endpoint, payload, league_id, season
    from ({{ fo_espn_latest('roster', extra_partition='scoringPeriodId') }})

    union all

    select 'matchups' as endpoint, payload, league_id, season
    from ({{ fo_espn_latest('matchups') }})

),

header as (

    select
        endpoint,
        league_id as partition_league_id,
        season as partition_season,
        {{ fo_json_text('payload', '$.id') }} as payload_league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as payload_season
    from latest

)

select *
from header
where partition_league_id is distinct from payload_league_id
   or partition_season is distinct from payload_season
