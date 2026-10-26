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
-- The line filter (applied to each player's list before the unnest) is statSourceId 0
-- (actual; 1 is ESPN's projection) and statSplitTypeId 5.
-- `scoringPeriodId` is 0 on every such line (C1) and is not filtered on, so that a capture
-- where ESPN fills it is not silently emptied. The `stats` object becomes rows, keys
-- beside values; a value that is not a number leaves that stat out and keeps the line's
-- others (R1.5). ESPN's rates are not staged either (`is_rate` in espn_stat_ids, ADR 0099),
-- and the "Infinity" that R1.5 drops is ESPN's undefined K/BB. A stat id the seed does
-- not know is kept. A bye has no lines.
--
-- Memory (AGENTS.md, rule 1; spec 0150): the capture view parses the file into the fields
-- declared there, so no name and no member data is a value here. Which captures are read
-- is chosen on the manifest's narrow columns (`fo_espn_latest`, then the last scoring
-- period) and kept by a semi-join on file_path, never by ranking parsed rows. Each unnest
-- runs beside the narrow identifier columns only, and the sides of a matchup are unnested
-- from one list, so the schedule is read once. The parsed captures are read once, by
-- `header`, which keeps the chosen ones by a join on file_path (the chosen ones are
-- newest captures, so fo_espn_latest's own filter would only repeat the manifest query);
-- `newest` takes its columns from the manifest. The matchups and the lines are
-- chosen by fo_list_filter before their unnests, and the stats object is unnested as map
-- entries, because DuckDB plans a WHERE over unnested elements, and fo_unnest_pair, as a
-- delim join that holds every parsed capture (spec 0156).
--
-- In the BigQuery slice (ADR 0051): written once for both warehouses. CI holds three
-- matchup_days captures of the fixture's matchups, so this model holds the lines of the newest
-- (scoring period 7) there; its logic is also covered by unit tests.
--
-- A plain table: it reads the captures at once, as the view streams them (spec 0150).

{{ config(materialized='table') }}

with newest as (

    -- The manifest's narrow columns of the newest capture of each scoring period: the same
    -- captures fo_espn_latest keeps, chosen by the same rule. They come from the manifest,
    -- not from the parsed captures, which only `header` reads: DuckDB materializes parsed
    -- captures that are read twice (spec 0156).
    select
        manifest.file_path,
        {{ fo_json_text('manifest.partitions', '$.league_id') }} as league_id,
        cast({{ fo_json_int('manifest.partitions', '$.season') }} as integer) as season,
        {{ fo_request_param('manifest.request_key', 'scoringPeriodId') }} as scoring_period
    from {{ fo_capture_keys() }} as manifest
    where manifest.file_path in (
        {{ fo_espn_latest_paths('matchup_days', extra_partition='scoringPeriodId') }}
    )

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

    -- The chosen captures only (the inner join on file_path), with each one's matchups of
    -- the chosen matchup period (R1.2). The matchups are chosen with fo_list_filter before
    -- the unnest, not with a WHERE after it, which DuckDB plans as a delim join holding
    -- every parsed capture (spec 0156).
    select
        captures.id as league_id,
        captures.seasonId as season,
        {{ fo_request_param('captures.request_key', 'scoringPeriodId') }} as scoring_period,
        captures.fetched_at,
        chosen.matchup_period,
        {{ fo_list_filter(
            'captures.schedule', 'candidate', 'candidate.matchupPeriodId = chosen.matchup_period'
        ) }} as schedule
    from {{ ref('stg_raw__espn_matchup_days') }} as captures
    inner join chosen
        on chosen.file_path = captures.file_path

),

matchups as (

    -- A matchup's two sides as one list, so that the schedule is unnested once.
    select
        header.league_id,
        header.season,
        header.scoring_period,
        header.fetched_at,
        header.matchup_period,
        matchup.id as matchup_id,
        [matchup.home, matchup.away] as sides
    from header
    {{ fo_unnest('header.schedule', 'matchup') }}

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
        {{ fo_list_filter(
            'entry.playerPoolEntry.player.stats', 'candidate',
            'candidate.statSourceId = 0 and candidate.statSplitTypeId = 5'
        ) }} as player_lines
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

stat_entries as (

    -- The lines are the actual ones for the whole period, chosen above (R1.1). The stats
    -- object is a map: an entry's key is the stat id as text, its value the stat's value
    -- as JSON.
    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        matchup_period,
        matchup_id,
        team_id,
        espn_player_id,
        {{ fo_map_entries('line.stats') }} as line_entries
    from lines

),

stat_rows as (

    select
        stat_entries.league_id,
        stat_entries.season,
        stat_entries.scoring_period,
        stat_entries.fetched_at,
        stat_entries.matchup_period,
        stat_entries.matchup_id,
        stat_entries.team_id,
        stat_entries.espn_player_id,
        line_entry.key as stat_key,
        line_entry.value as stat_value
    from stat_entries
    {{ fo_unnest('stat_entries.line_entries', 'line_entry') }}

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
        -- A value that is not a JSON number gives null, and the row is left out (R1.5): a
        -- string, even one that reads as a number, is not ESPN's count.
        case
            when {{ fo_json_is_number('stat_value', '$') }}
                then {{ fo_safe_cast(fo_json_string('stat_value', '$'), fo_type_float()) }}
        end as stat_value,
        scoring_period,
        {{ fo_parse_fetched_at() }} as fetched_at
    from stat_rows

)

select
    numbered.league_id,
    numbered.season,
    numbered.matchup_period,
    numbered.matchup_id,
    numbered.team_id,
    numbered.espn_player_id,
    numbered.stat_id,
    numbered.stat_value,
    numbered.scoring_period,
    numbered.fetched_at
from numbered
left join {{ ref('espn_stat_ids') }} as stat_ids
    on stat_ids.stat_id = numbered.stat_id
where
    numbered.stat_value is not null
    and not coalesce(stat_ids.is_rate, false)
