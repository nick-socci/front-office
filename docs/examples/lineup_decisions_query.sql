-- How much did each team leave on its bench?
--
-- fct_lineup_decisions has one row per team and day: the value of the lineup the team
-- set, and of the best lineup it could have set from the players it held that day. The
-- best lineup is found with hindsight, and it swaps a starter who played only for a
-- bench player who also played (ADR 0037), so the gap counts lineup choices and not
-- starters who happened to have a bad day.
--
-- Read it as opportunity, not as skill: nobody knows in the morning what a player will
-- do that night. The unit is a matchup margin, as in fct_player_season_value.
--
-- Run with:
--   duckdb data/warehouse.duckdb < docs/examples/lineup_decisions_query.sql
--
-- Teams are shown by id: fantasy teams' names are their owners' and are left out of
-- anything committed here.

.mode box

select
    season,
    fantasy_team_id,
    count(*) as team_days,
    count(*) filter (where value_gap > 0) as days_with_a_better_lineup,
    round(sum(actual_value), 2) as actual_value,
    round(sum(optimal_value), 2) as optimal_value,
    round(sum(value_gap), 2) as value_left_on_bench,
    round(max(value_gap), 2) as worst_single_day
from marts.fct_lineup_decisions
-- A day with a player who could not be valued has no gap to report.
where not is_unvalued
group by league_id, season, fantasy_team_id
order by season, value_left_on_bench desc, fantasy_team_id;
