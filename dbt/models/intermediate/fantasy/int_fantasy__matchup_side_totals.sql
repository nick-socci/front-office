-- One row per matchup side: every credited component summed over the matchup's days,
-- and how many of those player-days rest on complete inputs.
--
-- Components only. Rates are computed from these totals one level up, never averaged
-- from daily or per-game rates: a team's ERA for the week is 27 * its earned runs over
-- its outs, which no average of daily ERAs reproduces.
--
-- The days come from int_fantasy__matchup_periods, never from an assumed week: matchup
-- periods here run 12, 14 and 7 days.
--
-- Every side gets a row, even one that started nobody on any day -- left joins all the
-- way down, so a side is never silently dropped. Its components are then zero, and
-- started_player_days = 0 says why.
--
-- Only for league-seasons with rosters (ADR 0026). A past season loaded for its matchup
-- totals alone has sides and no started days, and the left joins below would give each
-- of its sides a row of zeroes: a total that reads as "this team produced nothing" when
-- nothing was ever loaded to add up. The inner join to the covered league-seasons is the
-- one place that is decided; the stat values, category scores and results computed from
-- this model follow it. "Every side gets a row" holds within a covered league-season.
--
-- The input counts carry #25's status up a level. A side's totals are only as good as
-- its least certain day, so marts report unverified_player_days next to the scores
-- rather than scoring a missing boxscore as zero.

{{ config(materialized='table') }}

{%- set stat_columns = fo_batting_columns() + fo_pitching_columns() %}

select
    sides.platform,
    sides.league_id,
    sides.season,
    sides.matchup_id,
    sides.matchup_period,
    sides.fantasy_team_id,
    sides.opponent_team_id,
    sides.is_home,

    count(days.scoring_date) as started_player_days,
    count(days.scoring_date) filter (
        where days.input_status in ('played', 'verified_off')
    ) as verified_player_days,
    count(days.scoring_date) filter (
        where days.input_status = 'missing_boxscore'
    ) as missing_boxscore_player_days,
    count(days.scoring_date) filter (
        where days.input_status = 'unresolved_player'
    ) as unresolved_player_days,
    {%- for column in stat_columns %}
    coalesce(sum(days.{{ column }}), 0) as {{ column }}{{ ',' if not loop.last }}
    {%- endfor %}
from {{ ref('int_fantasy__matchup_sides') }} as sides
inner join {{ ref('int_fantasy__league_seasons') }} as league_seasons
    on league_seasons.platform = sides.platform
    and league_seasons.league_id = sides.league_id
    and league_seasons.season = sides.season
    and league_seasons.has_rosters
left join {{ ref('int_fantasy__matchup_periods') }} as periods
    on periods.platform = sides.platform
    and periods.league_id = sides.league_id
    and periods.season = sides.season
    and periods.matchup_period = sides.matchup_period
left join {{ ref('int_fantasy__started_player_days') }} as days
    on days.platform = periods.platform
    and days.league_id = periods.league_id
    and days.season = periods.season
    and days.scoring_date = periods.scoring_date
    and days.fantasy_team_id = sides.fantasy_team_id
group by
    sides.platform,
    sides.league_id,
    sides.season,
    sides.matchup_id,
    sides.matchup_period,
    sides.fantasy_team_id,
    sides.opponent_team_id,
    sides.is_home
