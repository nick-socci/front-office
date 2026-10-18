-- One row per (matchup, side, ESPN player, stat): ESPN's own record of what each player
-- was credited with in a head-to-head matchup, summed by ESPN over the matchup period.
--
-- Beside the totals that decide a matchup (scoreByStat, in stg_espn__matchup_category_results),
-- every matchup-days capture holds, for each side of the matchups of the period asked,
-- `rosterForMatchupPeriod`: each player's entry with one stat line for the whole period
-- (statSourceId 0, statSplitTypeId 5). They are what ESPN credited after its own rules,
-- and a second record to set our totals and ESPN's totals against (spec 0147, C1 to C4).
-- The reconciliation reads these lines; this model only stages them.
--
-- Which captures (R1.2): a matchup's lines are read from the capture of the LAST scoring
-- period of its matchup period that has a capture, the newest capture of that scoring
-- period. For a finished season any day of the period gives the same lines (C3); the last
-- is the one a period in progress has most of. The matchup period of each scoring period
-- is stg_espn__matchup_days'. A capture carries lines only for the matchups of the period
-- it was asked about (C1), and the matchup period is filtered on again here so that a
-- capture is never read for a matchup of another period.
--
-- The line filter is statSourceId 0 (actual; 1 is ESPN's projection) and statSplitTypeId 5.
-- `scoringPeriodId` is 0 on every such line (C1) and is not filtered on, so that a capture
-- where ESPN fills it is not silently emptied. The `stats` object becomes rows, keys
-- beside values; a value that is not a number leaves that stat out and keeps the line's
-- others (R1.5). A bye has no lines.
--
-- Memory (AGENTS.md, rule 1; spec 0150): the capture view parses the file into the fields
-- declared there, so no name and no member data is a value here. Which captures are read
-- is chosen on the manifest's narrow columns (`fo_espn_latest`, then the last scoring
-- period) and kept by a semi-join on file_path, never by ranking parsed rows. Each unnest
-- runs beside the narrow identifier columns only, and the sides of a matchup are unnested
-- from one list, so the schedule is read once.
--
-- In the BigQuery slice (ADR 0051): written once for both warehouses. In CI there are no
-- matchup_days captures, so this model is empty there; its logic is covered by unit tests.
--
-- A plain table: it reads the captures at once, as the view streams them (spec 0150).

{{ config(materialized='table') }}

with latest as (

    {{ fo_espn_latest('matchup_days', extra_partition='scoringPeriodId') }}

),

newest as (

    -- The manifest's narrow columns of the newest capture of each scoring period.
    select
        file_path,
        league_id,
        season,
        {{ fo_request_param('request_key', 'scoringPeriodId') }} as scoring_period
    from latest

),

last_periods as (

    -- The last scoring period of each matchup period that has a capture.
    select
        league_id,
        season,
        matchup_period,
        max(scoring_period) as scoring_period
    from {{ ref('stg_espn__matchup_days') }}
    group by league_id, season, matchup_period

),

chosen as (

    select
        newest.file_path,
        last_periods.league_id,
        last_periods.season,
        last_periods.matchup_period,
        last_periods.scoring_period
    from last_periods
    inner join newest
        on newest.league_id = last_periods.league_id
        and newest.season = last_periods.season
        and newest.scoring_period = last_periods.scoring_period

),

header as (

    -- The chosen captures only: the semi-join on file_path keeps the view's rows.
    select
        latest.id as league_id,
        latest.seasonId as season,
        {{ fo_request_param('latest.request_key', 'scoringPeriodId') }} as scoring_period,
        latest.fetched_at,
        latest.file_path,
        latest.schedule
    from latest
    where latest.file_path in (select chosen.file_path from chosen)

),

matchups as (

    -- A matchup's two sides as one list, so that the schedule is unnested once. Only the
    -- matchup of the capture's chosen matchup period is kept.
    select
        header.league_id,
        header.season,
        header.scoring_period,
        header.fetched_at,
        chosen.matchup_period,
        matchup.id as matchup_id,
        [matchup.home, matchup.away] as sides
    from header
    inner join chosen
        on chosen.file_path = header.file_path
    {{ fo_unnest('header.schedule', 'matchup') }}
    where matchup.matchupPeriodId = chosen.matchup_period

),

side_entries as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        matchup_period,
        matchup_id,
        side.teamId as team_id,
        side.rosterForMatchupPeriod.entries as roster_entries
    from matchups
    {{ fo_unnest('matchups.sides', 'side') }}

),

entries as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        matchup_period,
        matchup_id,
        team_id,
        entry.playerId as espn_player_id,
        entry.playerPoolEntry.player.stats as player_lines
    from side_entries
    {{ fo_unnest('side_entries.roster_entries', 'entry') }}

),

lines as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        matchup_period,
        matchup_id,
        team_id,
        espn_player_id,
        line
    from entries
    {{ fo_unnest('entries.player_lines', 'line') }}

),

period_lines as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        matchup_period,
        matchup_id,
        team_id,
        espn_player_id,
        line.stats as line_stats
    from lines
    where
        line.statSourceId = 0
        and line.statSplitTypeId = 5

),

stat_rows as (

    -- stat_key and stat_value are the names fo_unnest_pair gives the two unnested values,
    -- the keys of the stats object beside the values of the same keys (a JSON value each).
    select
        period_lines.league_id,
        period_lines.season,
        period_lines.scoring_period,
        period_lines.fetched_at,
        period_lines.matchup_period,
        period_lines.matchup_id,
        period_lines.team_id,
        period_lines.espn_player_id,
        stat_key,  -- noqa: RF02
        stat_value  -- noqa: RF02
    from period_lines
    {{ fo_unnest_pair(
        fo_json_keys('period_lines.line_stats', '$'), 'stat_key',
        fo_json_values('period_lines.line_stats', '$'), 'stat_value'
    ) }}

),

numbered as (

    select
        league_id,
        season,
        matchup_period,
        matchup_id,
        team_id,
        espn_player_id,
        cast(stat_key as bigint) as stat_id,
        {{ fo_safe_cast(fo_json_string('stat_value', '$'), fo_type_float()) }} as stat_value,
        scoring_period,
        {{ fo_parse_fetched_at() }} as fetched_at
    from stat_rows

)

select
    league_id,
    season,
    matchup_period,
    matchup_id,
    team_id,
    espn_player_id,
    stat_id,
    stat_value,
    scoring_period,
    fetched_at
from numbered
where stat_value is not null
