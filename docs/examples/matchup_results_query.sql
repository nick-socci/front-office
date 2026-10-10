-- How did each team's regular season go?
--
-- A head-to-head standings table, rebuilt from the marts alone: each team's matchups
-- won, lost and tied, and under them the categories won, lost and tied that decided
-- those matchups.
--
-- fct_matchup_results has one row per matchup, with a home side and an away side. A
-- standings table wants one row per team, so each matchup is read twice, once from each
-- side, and then summed.
--
-- Run with:
--   duckdb data/warehouse.duckdb < docs/examples/matchup_results_query.sql
--
-- Teams are shown by id: fantasy teams' names are their owners' and are left out of
-- anything committed here.

.mode box

with sides as (
    select
        league_id,
        season,
        home_team_id as fantasy_team_id,
        winner = 'HOME' as won,
        winner = 'AWAY' as lost,
        winner = 'TIE' as tied,
        home_category_wins as category_wins,
        away_category_wins as category_losses,
        category_ties
    from marts.fct_matchup_results
    -- NONE is the regular season; every other tier is a playoff or consolation bracket.
    where playoff_tier = 'NONE'

    union all

    select
        league_id,
        season,
        away_team_id as fantasy_team_id,
        winner = 'AWAY' as won,
        winner = 'HOME' as lost,
        winner = 'TIE' as tied,
        away_category_wins as category_wins,
        home_category_wins as category_losses,
        category_ties
    from marts.fct_matchup_results
    where playoff_tier = 'NONE'
)

select
    season,
    fantasy_team_id,
    count(*) as matchups,
    count(*) filter (where won) as wins,
    count(*) filter (where lost) as losses,
    count(*) filter (where tied) as ties,
    sum(category_wins) as category_wins,
    sum(category_losses) as category_losses,
    sum(category_ties) as category_ties
from sides
group by league_id, season, fantasy_team_id
order by season, wins desc, category_wins desc, fantasy_team_id;
