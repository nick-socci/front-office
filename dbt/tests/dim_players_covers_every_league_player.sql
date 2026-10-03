-- Every player the league touched must have a dim_players row: anyone on a roster day or
-- in a transaction. Returns the ids that are missing.
--
-- Catches a player dropped by the roster/transaction union (R1.1), for instance a
-- transaction-only player lost to an inner join against the id map. A player who cannot
-- be resolved still gets a row (R1.3), so an unresolved id is never an excuse to be absent.

select league_players.platform_player_id
from (
    select platform_player_id from {{ ref('int_fantasy__roster_days') }}
    union
    select platform_player_id from {{ ref('int_fantasy__transactions') }}
    where platform_player_id is not null
) as league_players
left join {{ ref('dim_players') }} as players
    on players.platform_player_id = league_players.platform_player_id
where players.platform_player_id is null
