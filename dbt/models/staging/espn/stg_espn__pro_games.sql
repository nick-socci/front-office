-- One row per (season, ESPN game): ESPN's own schedule of MLB games.
--
-- The pro_schedule resource lists, for every MLB team, its games keyed by the scoring
-- period ESPN assigns them to. It exists because it is ESPN's own statement of which day
-- each scoring period is (ADR 0023), and because its game id is the externalId of the
-- roster stat lines, so these rows join to stg_espn__player_game_stats on espn_game_id
-- (kept as text for that reason). It is not MLB's game_pk.
--
-- The newest capture of a season is read whole, not the newest row per game. A schedule
-- is a statement about the season at one moment: a game ESPN drops should drop out, not
-- linger from an older capture. AGENTS.md rule 5 is about one request split into
-- overlapping chunks; this response is not that. A pro schedule has no league, so
-- fo_espn_latest's league partition is null and all captures of a season form one group.
--
-- Every game is listed twice, identically: under its home team and under its away team.
-- The final select distinct collapses the two listings to one row. If the listings ever
-- differed, the two versions would both survive and the uniqueness test on
-- (season, espn_game_id) would fail -- that is intended, not something to paper over. A
-- doubleheader is two games in one period's list, each with its own id.
--
-- Team ids are ESPN's, not MLB's. startTimeTBD, statsOfficial, validForLocking and
-- byeWeek are not staged: what they mean is not established.
--
-- Same memory rules as stg_espn__roster_entries: the payload is ~850 KB, parsed once with
-- an explicit schema into narrow columns, and dropped before any unnest (AGENTS.md rule
-- 1). The per-period object is left as JSON by that parse: its values, the lists of
-- games, are taken with fo_json_values and each list parsed with its own schema. It was a
-- DuckDB MAP until the BigQuery slice (spec 0130); BigQuery has no map type.

{{ config(materialized='table') }}

{% set pro_teams_schema %}
[{
  "id": "BIGINT",
  "proGamesByScoringPeriod": "JSON"
}]
{% endset %}

{% set games_schema %}
[{
  "id": "BIGINT",
  "date": "BIGINT",
  "scoringPeriodId": "BIGINT",
  "homeProTeamId": "BIGINT",
  "awayProTeamId": "BIGINT"
}]
{% endset %}

with latest as (

    {{ fo_espn_latest('pro_schedule') }}

),

header as (

    select
        season,
        fetched_at,
        {{ fo_json_parse('payload', '$.settings.proTeams', pro_teams_schema) }} as teams_list
    from latest

),

-- Each step below computes the next list as a column and the step after unnests it:
-- fo_unnest is given a column, never an expression (see stg_espn__roster_entries).
teams as (

    select
        season,
        fetched_at,
        {{ fo_json_values('team.proGamesByScoringPeriod', '$') }} as period_lists
    from header
    {{ fo_unnest('header.teams_list', 'team') }}

),

game_lists as (

    select
        season,
        fetched_at,
        {{ fo_json_parse('games', '$', games_schema) }} as games_list
    from teams
    {{ fo_unnest('teams.period_lists', 'games') }}

),

listed_games as (

    select
        season,
        fetched_at,
        game
    from game_lists
    {{ fo_unnest('game_lists.games_list', 'game') }}

)

select distinct
    season,
    cast(game.id as {{ fo_type_text() }}) as espn_game_id,
    game.scoringPeriodId as scoring_period,
    {{ fo_timestamp_from_millis('game.date') }} as game_start_at_utc,
    {{ fo_eastern_date(fo_timestamp_from_millis('game.date')) }} as game_date,
    game.homeProTeamId as home_pro_team_id,
    game.awayProTeamId as away_pro_team_id,
    {{ fo_parse_fetched_at() }} as fetched_at
from listed_games
