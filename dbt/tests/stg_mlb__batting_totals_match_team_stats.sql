-- Every boxscore states its own team totals. The sum of the player rows this model
-- produced must equal them.
--
-- This is the strongest available check that nothing is dropped or double-counted while
-- flattening the payload: it compares the model back against the source for all ~4,800
-- team-sides in the season. A filter mistake (say, requiring plate appearances) or a
-- dedupe mistake (dropping a real player row) shows up here immediately.

with claimed as (

    select
        {{ fo_request_param('request_key', 'gamePk') }} as game_pk,
        side,
        try_cast(
            json_extract_string(payload, '$.teams.' || side || '.teamStats.batting.hits') as bigint
        ) as team_hits,
        try_cast(
            json_extract_string(payload, '$.teams.' || side || '.teamStats.batting.runs') as bigint
        ) as team_runs,
        try_cast(
            json_extract_string(payload, '$.teams.' || side || '.teamStats.batting.atBats') as bigint
        ) as team_at_bats
    from (
        select
            payload,
            request_key,
            unnest(['home', 'away']) as side
        from {{ source('raw', 'api_responses') }}
        where source = 'mlb'
          and endpoint = 'boxscore'
    )

),

summed as (

    select
        game_pk,
        side,
        sum(hits) as hits,
        sum(runs) as runs,
        sum(at_bats) as at_bats
    from {{ ref('stg_mlb__batting_game_logs') }}
    group by game_pk, side

)

select
    c.game_pk,
    c.side,
    c.team_hits,
    s.hits,
    c.team_runs,
    s.runs,
    c.team_at_bats,
    s.at_bats
from claimed as c
inner join summed as s
    on c.game_pk = s.game_pk
    and c.side = s.side
where c.team_hits != s.hits
   or c.team_runs != s.runs
   or c.team_at_bats != s.at_bats
