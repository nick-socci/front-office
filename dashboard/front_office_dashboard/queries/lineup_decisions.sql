-- example: {"platform": "espn", "league_id": "111111", "season": 2026, "fantasy_team_id": 9}
-- One team's lineup decisions by day: what its lineup was worth against the best it could set.
select
    scoring_date,
    matchup_period,
    matchup_id,
    candidates,
    played_starters,
    optimal_starters,
    actual_value,
    optimal_value,
    value_gap,
    players_brought_in,
    players_sat,
    players_moved,
    actual_pitcher_starts,
    optimal_pitcher_starts,
    missed_start_mlbam_player_id,
    missed_start_slot,
    missed_start_value,
    is_unvalued,
    has_unverified_inputs
from marts.fct_lineup_decisions
where
    platform = $platform and league_id = $league_id and season = $season
    and fantasy_team_id = $fantasy_team_id
order by scoring_date
