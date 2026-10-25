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
-- is ~2.3 MB of embedded stats: it is read from the roster capture view, which keeps only
-- the declared fields, and everything else is computed before any unnest. The stats
-- object is left as JSON, and its keys and values are unnested together to rows.
--
-- ESPN's rates (15 stat ids, `is_rate` in espn_stat_ids) are not staged. ESPN writes a
-- value for a rate even when its denominator is zero, in encodings that change by season:
-- the largest double in 2018, NaN for RC in 2021, 0.0 from 2019 (which cannot be told from
-- a real zero); and two largest doubles in one sum overflow. The project keeps components,
-- never rates (AGENTS.md, rule 4); ADR 0099. A stat id the seed does not know is kept.
--
-- A plain table: it reads every capture at once, as the view streams them (spec 0150).

{{ config(materialized='table') }}

with latest as (

    {{ fo_espn_latest('roster', extra_partition='scoringPeriodId') }}

),

header as (

    select
        id as league_id,
        seasonId as season,
        {{ fo_request_param('request_key', 'scoringPeriodId') }} as scoring_period,
        fetched_at,
        teams as teams_list
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
    stat_rows.league_id,
    stat_rows.season,
    stat_rows.scoring_period,
    stat_rows.team_id,
    stat_rows.espn_player_id,
    stat_rows.espn_game_id,
    cast(stat_rows.stat_key as bigint) as stat_id,
    {{ fo_safe_cast(fo_json_string('stat_rows.stat_value', '$'), fo_type_float()) }} as stat_value,
    {{ fo_parse_fetched_at() }} as fetched_at
from stat_rows
left join {{ ref('espn_stat_ids') }} as stat_ids
    on stat_ids.stat_id = cast(stat_rows.stat_key as bigint)
where not coalesce(stat_ids.is_rate, false)
