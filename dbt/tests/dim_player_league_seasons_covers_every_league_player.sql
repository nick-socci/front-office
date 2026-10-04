-- Every player a league-season touched must have a dim_player_league_seasons row in THAT
-- league-season: anyone on its roster days or in its transactions. Returns the (league,
-- season, player) triples that are missing.
--
-- Catches a player dropped by the roster/transaction union (R1.1), for instance a
-- transaction-only player lost to an inner join against the id map, and (#28) a player
-- present only because he has a row in another league or season. A player who cannot be
-- resolved still gets a row (R1.3), so an unresolved id is never an excuse to be absent.

select
    league_players.platform,
    league_players.league_id,
    league_players.season,
    league_players.platform_player_id
from (
    select platform, league_id, season, platform_player_id
    from {{ ref('int_fantasy__roster_days') }}
    union
    select platform, league_id, season, platform_player_id
    from {{ ref('int_fantasy__transactions') }}
    where platform_player_id is not null
) as league_players
left join {{ ref('dim_player_league_seasons') }} as players
    on players.platform = league_players.platform
    and players.league_id = league_players.league_id
    and players.season = league_players.season
    and players.platform_player_id = league_players.platform_player_id
where players.platform_player_id is null
