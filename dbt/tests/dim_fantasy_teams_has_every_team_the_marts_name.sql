-- Every team id a mart names has a row in dim_fantasy_teams for its league-season (spec 0232).
--
-- A dashboard page shows a team by joining its id to the dimension, so an id with no row
-- would show as a number or vanish from an inner join. The key is (platform, league_id,
-- season, fantasy_team_id), which a generic relationships test cannot express, so this
-- reads every team column of every mart and returns the ids with no row. fct_team_standings
-- is built from the same teams and is held by its own grain test.
{% set team_columns = [
    ('fct_matchup_results', 'home_team_id'),
    ('fct_matchup_results', 'away_team_id'),
    ('fct_matchup_category_scores', 'fantasy_team_id'),
    ('fct_matchup_category_scores', 'opponent_team_id'),
    ('fct_lineup_decisions', 'fantasy_team_id'),
    ('fct_lineup_decision_categories', 'fantasy_team_id'),
    ('fct_lineup_decision_categories', 'opponent_team_id'),
    ('fct_player_category_value', 'fantasy_team_id'),
    ('fct_player_season_value', 'fantasy_team_id'),
    ('fct_transaction_impact', 'fantasy_team_id'),
    ('fct_transaction_impact', 'next_added_by_team_id'),
] %}

with named as (

    {% for mart, team_column in team_columns %}
    select
        '{{ mart }}' as mart,
        '{{ team_column }}' as team_column,
        platform,
        league_id,
        season,
        {{ team_column }} as team_id
    from {{ ref(mart) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}

),

missing as (

    select distinct
        named.mart,
        named.team_column,
        named.platform,
        named.league_id,
        named.season,
        named.team_id
    from named
    left join {{ ref('dim_fantasy_teams') }} as teams
        on teams.platform = named.platform
        and teams.league_id = named.league_id
        and teams.season = named.season
        and teams.fantasy_team_id = named.team_id
    where
        named.team_id is not null
        and teams.fantasy_team_id is null

)

select * from missing
