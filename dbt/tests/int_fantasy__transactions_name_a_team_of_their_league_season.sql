-- Every transaction's acting team must be a team of the transaction's own league and
-- season. Returns the transactions whose team is not.
--
-- This is the league-season-correct form of a relationships test (#28): a plain
-- relationships test on fantasy_team_id alone would pass for a team id that exists only in
-- another league, which is exactly the mix-up league and season were added to prevent.

select
    transactions.platform,
    transactions.league_id,
    transactions.season,
    transactions.transaction_id,
    transactions.fantasy_team_id
from {{ ref('int_fantasy__transactions') }} as transactions
left join {{ ref('int_fantasy__teams') }} as teams
    on teams.platform = transactions.platform
    and teams.league_id = transactions.league_id
    and teams.season = transactions.season
    and teams.fantasy_team_id = transactions.fantasy_team_id
where
    transactions.fantasy_team_id is not null
    and teams.fantasy_team_id is null
