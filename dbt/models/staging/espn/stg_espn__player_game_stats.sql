-- One row per (scoring period, player, ESPN game line, stat): ESPN's own record of what
-- a rostered player did in one game.
--
-- Every roster payload embeds each player's stat lines. The ones kept here are
-- statSourceId 0 (actual, not projected) and statSplitTypeId 5 (a single game), for the
-- snapshot's own scoring period. The same lines reappear in the next period's snapshot;
-- taking each period's from its own snapshot gives every line exactly once.
--
-- One line per GAME, keyed by ESPN's game id (externalId), which is not MLB's game_pk.
-- A doubleheader is two lines on one scoring period; anything comparing a player's day
-- must sum them. Taking one would invent a difference on every doubleheader day.
--
-- This exists for the reconciliation (#10): it lets each difference between a matchup
-- total and ESPN's be traced to the player-day that causes it. It covers only players
-- on a roster in that period, which is every started player.
--
-- Same memory rules as stg_espn__roster_entries, and for the same reason -- each payload
-- is ~2.3 MB of embedded stats: parse with an explicit schema, and drop the payload
-- before any unnest. The stats object is left as JSON, and its keys and values are
-- unnested together to rows.
--
-- Built a season at a time. DuckDB holds every parsed payload of a run at once, and two
-- seasons took the build to its memory limit, so dbt runs this model once per calendar
-- year (microbatch), reading one season's captures through stg_raw__season_responses.
-- Every build redoes every season. On BigQuery it is a plain table (spec 0143, ADRs 0058
-- to 0060).

{{ config(
    materialized=('incremental' if target.type == 'duckdb' else 'table'),
    incremental_strategy=('microbatch' if target.type == 'duckdb' else none),
    event_time='season_start',
    batch_size='year',
    begin=var('first_season_start'),
    lookback=fo_batches_back_to_first_season(),
    concurrent_batches=false,
    on_schema_change='fail'
) }}

{% set roster_stats_schema %}
[{
  "id": "BIGINT",
  "roster": {"entries": [{
    "playerId": "BIGINT",
    "playerPoolEntry": {"player": {
      "stats": [{
        "scoringPeriodId": "BIGINT",
        "statSourceId": "BIGINT",
        "statSplitTypeId": "BIGINT",
        "externalId": "VARCHAR",
        "stats": "JSON"
      }]
    }}
  }]}
}]
{% endset %}

with latest as (

    {{ fo_espn_latest(
        'roster',
        extra_partition='scoringPeriodId',
        relation=ref('stg_raw__season_responses')
    ) }}

),

header as (

    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        {{ fo_request_param('request_key', 'scoringPeriodId') }} as scoring_period,
        fetched_at,
        season_start,
        {{ fo_json_parse('payload', '$.teams', roster_stats_schema) }} as teams_list
    from latest

),

teams as (

    -- A team's entries are taken out as a column of their own here: fo_unnest is given a
    -- column, never an expression (see stg_espn__roster_entries).
    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        season_start,
        team.id as team_id,
        team.roster.entries as roster_entries
    from header
    {{ fo_unnest('header.teams_list', 'team') }}

),

entries as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        season_start,
        team_id,
        entry.playerId as espn_player_id,
        entry.playerPoolEntry.player.stats as player_lines
    from teams
    {{ fo_unnest('teams.roster_entries', 'entry') }}

),

lines as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        season_start,
        team_id,
        espn_player_id,
        line
    from entries
    {{ fo_unnest('entries.player_lines', 'line') }}

),

game_lines as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        season_start,
        team_id,
        espn_player_id,
        line.externalId as espn_game_id,
        line.stats as line_stats
    from lines
    where
        line.statSourceId = 0
        and line.statSplitTypeId = 5
        and line.scoringPeriodId = scoring_period

),

stat_rows as (

    -- stat_key and stat_value are the names fo_unnest_pair gives the two unnested values,
    -- the keys of the stats object beside the values of the same keys (a JSON number each).
    select
        game_lines.league_id,
        game_lines.season,
        game_lines.scoring_period,
        game_lines.fetched_at,
        game_lines.season_start,
        game_lines.team_id,
        game_lines.espn_player_id,
        game_lines.espn_game_id,
        stat_key,  -- noqa: RF02
        stat_value  -- noqa: RF02
    from game_lines
    {{ fo_unnest_pair(
        fo_json_keys('game_lines.line_stats', '$'), 'stat_key',
        fo_json_values('game_lines.line_stats', '$'), 'stat_value'
    ) }}

)

select
    league_id,
    season,
    scoring_period,
    team_id,
    espn_player_id,
    espn_game_id,
    cast(stat_key as bigint) as stat_id,
    {{ fo_safe_cast(fo_json_string('stat_value', '$'), fo_type_float()) }} as stat_value,
    {{ fo_parse_fetched_at() }} as fetched_at,
    season_start
from stat_rows
