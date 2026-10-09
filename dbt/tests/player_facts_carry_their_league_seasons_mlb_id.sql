-- Each player fact's mlbam_player_id must be that of the row's own league-season in
-- dim_player_league_seasons (R3.1, R3.4), nulls compared as equal. Returns every fact row
-- (as its distinct key) that has no league-season row for its own (platform, league_id,
-- season, platform_player_id), or whose mlbam_player_id differs from that row's.
--
-- It catches a fact row whose player exists only in another league-season (a one-column
-- relationships test to the player dimension passes on him), an id taken from the wrong
-- league-season, and a null id where the league-season has one, or the reverse.

with fact_players as (

    select distinct 'fct_player_category_value' as fact,
        platform, league_id, season, platform_player_id, mlbam_player_id
    from {{ ref('fct_player_category_value') }}
    union all
    select distinct 'fct_player_season_value' as fact,
        platform, league_id, season, platform_player_id, mlbam_player_id
    from {{ ref('fct_player_season_value') }}
    union all
    select distinct 'fct_transaction_impact' as fact,
        platform, league_id, season, platform_player_id, mlbam_player_id
    from {{ ref('fct_transaction_impact') }}

)

select
    fact_players.fact,
    fact_players.platform,
    fact_players.league_id,
    fact_players.season,
    fact_players.platform_player_id,
    fact_players.mlbam_player_id as fact_mlbam_player_id,
    league_seasons.mlbam_player_id as league_season_mlbam_player_id
from fact_players
left join {{ ref('dim_player_league_seasons') }} as league_seasons
    on league_seasons.platform = fact_players.platform
    and league_seasons.league_id = fact_players.league_id
    and league_seasons.season = fact_players.season
    and league_seasons.platform_player_id = fact_players.platform_player_id
where league_seasons.platform_player_id is null
    or fact_players.mlbam_player_id is distinct from league_seasons.mlbam_player_id
