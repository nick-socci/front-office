-- Each team's computed regular-season record equals ESPN's, less the matchups ESPN's
-- winner differs on (spec 0232, R1.4).
--
-- fct_team_standings counts finished regular-season matchups by our winner. ESPN's record is
-- by its own, and the two differ only where rec_espn__winner_differences lists a matchup
-- (a regular-season matchup ESPN calls differently, ADR 0078). So for each team the
-- difference, wins - reported_wins and likewise for losses and ties, must equal the sum
-- over its listed regular-season matchups of our result less ESPN's, and zero when it has
-- none. A difference left over is a matchup counted wrongly, one missing, or one counted
-- that ESPN does not.
--
-- This copy holds a season whose regular season is complete, so the record is final: an error.
-- Rows with no computed record (a league that does not score head-to-head categories) are
-- not compared. Returns the offending teams.

with listed as (

    select
        results.platform,
        results.league_id,
        results.season,
        results.home_team_id,
        results.away_team_id,
        differences.our_winner,
        differences.espn_winner
    from {{ ref('rec_espn__winner_differences') }} as differences
    inner join {{ ref('fct_matchup_results') }} as results
        on results.platform = 'espn'
        and results.league_id = differences.league_id
        and results.season = differences.season
        and results.matchup_id = differences.matchup_id
    where results.playoff_tier = 'NONE'

),

sides as (

    select
        platform,
        league_id,
        season,
        home_team_id as fantasy_team_id,
        (case when our_winner = 'HOME' then 1 else 0 end)
        - (case when espn_winner = 'HOME' then 1 else 0 end) as win_difference,
        (case when our_winner = 'AWAY' then 1 else 0 end)
        - (case when espn_winner = 'AWAY' then 1 else 0 end) as loss_difference,
        (case when our_winner = 'TIE' then 1 else 0 end)
        - (case when espn_winner = 'TIE' then 1 else 0 end) as tie_difference
    from listed

    union all

    select
        platform,
        league_id,
        season,
        away_team_id as fantasy_team_id,
        (case when our_winner = 'AWAY' then 1 else 0 end)
        - (case when espn_winner = 'AWAY' then 1 else 0 end) as win_difference,
        (case when our_winner = 'HOME' then 1 else 0 end)
        - (case when espn_winner = 'HOME' then 1 else 0 end) as loss_difference,
        (case when our_winner = 'TIE' then 1 else 0 end)
        - (case when espn_winner = 'TIE' then 1 else 0 end) as tie_difference
    from listed

),

expected as (

    -- order-exempt: sums of 0, 1 and -1, at most a few dozen terms a team.
    select
        platform,
        league_id,
        season,
        fantasy_team_id,
        sum(win_difference) as win_difference,
        sum(loss_difference) as loss_difference,
        sum(tie_difference) as tie_difference
    from sides
    group by platform, league_id, season, fantasy_team_id

)

select
    standings.platform,
    standings.league_id,
    standings.season,
    standings.fantasy_team_id,
    standings.wins - standings.reported_wins as win_difference,
    standings.losses - standings.reported_losses as loss_difference,
    standings.ties - standings.reported_ties as tie_difference,
    coalesce(expected.win_difference, 0) as expected_win_difference,
    coalesce(expected.loss_difference, 0) as expected_loss_difference,
    coalesce(expected.tie_difference, 0) as expected_tie_difference
from {{ ref('fct_team_standings') }} as standings
left join expected
    on expected.platform = standings.platform
    and expected.league_id = standings.league_id
    and expected.season = standings.season
    and expected.fantasy_team_id = standings.fantasy_team_id
where
    standings.matchups is not null
    and standings.is_regular_season_complete = true
    and (
        standings.wins - standings.reported_wins != coalesce(expected.win_difference, 0)
        or standings.losses - standings.reported_losses != coalesce(expected.loss_difference, 0)
        or standings.ties - standings.reported_ties != coalesce(expected.tie_difference, 0)
    )
