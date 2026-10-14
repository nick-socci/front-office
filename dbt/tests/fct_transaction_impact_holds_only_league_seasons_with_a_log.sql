-- fct_transaction_impact holds rows only for a league-season with a landed transaction log
-- (spec 0083, R4.3). Returns each (platform, league, season) that has rows there while
-- int_fantasy__league_seasons says no log is landed, or has no row for it at all.
--
-- ESPN serves the log of the current season only, so a past season covered for its rosters
-- has none (ADR 0056). Catches a transaction source that invents rows for such a season,
-- and a league-season missing from int_fantasy__league_seasons.

with held as (

    select
        platform,
        league_id,
        season,
        count(*) as row_count
    from {{ ref('fct_transaction_impact') }}
    group by platform, league_id, season

)

select
    held.platform,
    held.league_id,
    held.season,
    held.row_count
from held
left join {{ ref('int_fantasy__league_seasons') }} as league_seasons
    on league_seasons.platform = held.platform
    and league_seasons.league_id = held.league_id
    and league_seasons.season = held.season
where league_seasons.has_transaction_log is distinct from true
