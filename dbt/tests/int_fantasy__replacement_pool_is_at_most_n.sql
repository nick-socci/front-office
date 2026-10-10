-- A replacement pool holds at most one player per fantasy team: N is the number of
-- teams of THE LEAGUE AND SEASON the pool belongs to, so a larger pool means the top-N cut
-- was made at the wrong size (or at the size of another league). Returns the offending
-- league-season day kinds.
--
-- For the batting and relief pools. The start pool is not a set of N players: it is every
-- free-agent start by a pitcher who was a starter at the time, however many pitchers
-- that is (ADR 0029).
with league_season_sizes as (

    select
        platform,
        league_id,
        season,
        count(*) as team_count
    from {{ ref('int_fantasy__teams') }}
    group by platform, league_id, season

)

select
    levels.platform,
    levels.league_id,
    levels.season,
    levels.day_kind,
    max(levels.pool_players) as pool_players
from {{ ref('int_fantasy__replacement_levels') }} as levels
inner join league_season_sizes as sizes
    on sizes.platform = levels.platform
    and sizes.league_id = levels.league_id
    and sizes.season = levels.season
where levels.day_kind in ('batting', 'relief')
group by levels.platform, levels.league_id, levels.season, levels.day_kind, sizes.team_count
having max(levels.pool_players) > sizes.team_count
