-- example: {"mlbam_player_id": 668939}
-- One player's facts from MLB (position, bats, throws).
select mlbam_player_id, player_name, primary_position, bats, throws, birth_date, mlb_debut_date
from marts.dim_players
where mlbam_player_id = $mlbam_player_id
