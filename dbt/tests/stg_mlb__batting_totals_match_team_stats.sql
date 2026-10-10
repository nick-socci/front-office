-- Every boxscore states its own team totals. The sum of the player rows this model
-- produced must equal them.
--
-- This is the strongest available check that nothing is dropped or double-counted while
-- flattening the payload: it compares the model back against the source for all ~4,800
-- team-sides in the season. A filter mistake (say, requiring plate appearances) or a
-- dedupe mistake (dropping a real player row) shows up here immediately.
--
-- Three rules keep it from passing when it should not:
-- * Only the LATEST snapshot of each game is the claim. Official scorers revise games,
--   and staging keeps the latest; comparing against an older snapshot would fail on a
--   legitimate correction, while comparing against all of them passes nothing useful.
-- * A full outer join on (game_pk, side): player rows with no totals, or totals with no
--   player rows, are compared rather than silently dropped. A side with no player rows
--   sums to zero, so it passes only when the boxscore itself claims zero (a cancelled
--   game's boxscore does: 2026 game 823490).
-- * A missing (null) total is a failure, never a comparison that quietly yields null.

with latest_responses as (

    {{ fo_latest_boxscore_responses() }}

),

claimed as (

    -- One branch per side, so every JSON path is a constant.
    {% for side in ['home', 'away'] %}
    select
        {{ fo_request_param('request_key', 'gamePk') }} as game_pk,
        '{{ side }}' as side,
        {{ fo_json_int('payload', '$.teams.' ~ side ~ '.teamStats.batting.hits') }} as team_hits,
        {{ fo_json_int('payload', '$.teams.' ~ side ~ '.teamStats.batting.runs') }} as team_runs,
        {{ fo_json_int('payload', '$.teams.' ~ side ~ '.teamStats.batting.atBats') }}
            as team_at_bats
    from latest_responses
    {{ 'union all' if not loop.last }}
    {% endfor %}

),

summed as (

    select
        game_pk,
        side,
        sum(hits) as hits,
        sum(runs) as runs,
        sum(at_bats) as at_bats
    from {{ ref('stg_mlb__batting_game_logs') }}
    group by 1, 2

)

select
    coalesce(c.game_pk, s.game_pk) as game_pk,
    coalesce(c.side, s.side) as side,
    c.team_hits,
    coalesce(s.hits, 0) as hits,
    c.team_runs,
    coalesce(s.runs, 0) as runs,
    c.team_at_bats,
    coalesce(s.at_bats, 0) as at_bats
from claimed as c
full outer join summed as s
    on s.game_pk = c.game_pk
    and s.side = c.side
where
    c.team_hits is null
    or c.team_runs is null
    or c.team_at_bats is null
    or c.team_hits != coalesce(s.hits, 0)
    or c.team_runs != coalesce(s.runs, 0)
    or c.team_at_bats != coalesce(s.at_bats, 0)
