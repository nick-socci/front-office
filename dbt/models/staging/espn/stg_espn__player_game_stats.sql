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
-- before any unnest. The stats object becomes a MAP, unnested to rows.
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
        "stats": "MAP(VARCHAR, DOUBLE)"
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

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        season_start,
        unnest(teams_list) as team
    from header

),

entries as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        season_start,
        team.id as team_id,
        unnest(team.roster.entries) as entry
    from teams

),

lines as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        season_start,
        team_id,
        entry.playerId as espn_player_id,
        unnest(entry.playerPoolEntry.player.stats) as line
    from entries

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
        line.stats
    from lines
    where
        line.statSourceId = 0
        and line.statSplitTypeId = 5
        and line.scoringPeriodId = scoring_period

),

stat_rows as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        season_start,
        team_id,
        espn_player_id,
        espn_game_id,
        unnest(map_keys(stats)) as stat_key,
        unnest(map_values(stats)) as stat_value
    from game_lines

)

select
    league_id,
    season,
    scoring_period,
    team_id,
    espn_player_id,
    espn_game_id,
    cast(stat_key as bigint) as stat_id,
    stat_value,
    {{ fo_parse_fetched_at() }} as fetched_at,
    season_start
from stat_rows
