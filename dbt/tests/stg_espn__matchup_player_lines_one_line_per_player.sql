-- A player's entry in a matchup holds exactly one actual period line. Returns each
-- (capture, matchup, side, player) with more than one.
--
-- stg_espn__matchup_player_lines keeps every line with statSourceId 0 and statSplitTypeId
-- 5, and its rows are per stat, so a second such line would add to the player's stats
-- unseen unless the two lines share a stat key (which its uniqueness test would catch).
-- ESPN gave one on all 28,222 entries sampled (spec 0147, C1). This counts the lines
-- themselves, in the newest capture of every scoring period: a second line would mean
-- the line filter no longer picks out "the matchup's line", and the rows built from it
-- cannot be trusted as the player's period total.
--
-- The unnest runs beside the narrow identifier columns only (AGENTS.md, rule 1), exactly
-- as the model's does, and the lines are chosen with fo_list_filter before it, not with a
-- WHERE after it, so DuckDB streams the parsed captures (spec 0156). Empty where no
-- matchup_days response is loaded; CI loads the fixture's three.

with latest as (

    {{ fo_espn_latest('matchup_days', extra_partition='scoringPeriodId') }}

),

header as (

    select
        id as league_id,
        seasonId as season,
        {{ fo_request_param('request_key', 'scoringPeriodId') }} as scoring_period,
        schedule
    from latest

),

matchups as (

    select
        league_id,
        season,
        scoring_period,
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
        matchup_id,
        team_id,
        entry.playerId as espn_player_id,
        {{ fo_list_filter(
            'entry.playerPoolEntry.player.stats', 'line',
            'line.statSourceId = 0 and line.statSplitTypeId = 5'
        ) }} as player_lines
    from side_entries
    {{ fo_unnest('side_entries.roster_entries', 'entry') }}

),

lines as (

    select
        league_id,
        season,
        scoring_period,
        matchup_id,
        team_id,
        espn_player_id,
        line
    from entries
    {{ fo_unnest('entries.player_lines', 'line') }}

)

select
    league_id,
    season,
    scoring_period,
    matchup_id,
    team_id,
    espn_player_id,
    count(*) as period_lines
from lines
group by league_id, season, scoring_period, matchup_id, team_id, espn_player_id
having count(*) > 1
