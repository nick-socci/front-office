-- example: {"platform": "espn", "league_id": "111111", "season": 2026}
-- The season's adds and drops with what each player did in MLB afterwards. outs_recorded stays
-- a count: the page shows innings from it, for display only.
select
    i.transacted_at,
    i.movement,
    i.method,
    i.fantasy_team_id,
    t.team_name,
    i.platform_player_id,
    d.player_name,
    i.window_start,
    i.window_end,
    i.rostered_days,
    i.started_days,
    i.played_started_days,
    i.played_days,
    i.games_batted,
    i.plate_appearances,
    i.at_bats,
    i.hits,
    i.home_runs,
    i.runs,
    i.runs_batted_in,
    i.stolen_bases,
    i.games_pitched,
    i.games_started,
    i.outs_recorded,
    i.earned_runs,
    i.pitcher_strikeouts,
    i.wins,
    i.saves,
    i.total_value
from marts.fct_transaction_impact as i
inner join marts.dim_fantasy_teams as t
    on
        i.platform = t.platform
        and i.league_id = t.league_id
        and i.season = t.season
        and i.fantasy_team_id = t.fantasy_team_id
left join marts.dim_player_league_seasons as d
    on
        i.platform = d.platform
        and i.league_id = d.league_id
        and i.season = d.season
        and i.platform_player_id = d.platform_player_id
where i.platform = $platform and i.league_id = $league_id and i.season = $season
order by i.transacted_at desc, i.transaction_id, i.platform_player_id
