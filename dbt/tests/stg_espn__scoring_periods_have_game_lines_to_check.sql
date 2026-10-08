{{ config(severity='warn') }}

-- Scoring periods that stg_espn__scoring_periods_agree_with_espn_game_lines could not
-- check: the league-season has roster entries, MLB played regular-season games on the
-- period's date, but ESPN has no game line for the period. This catches that test
-- passing because it had nothing to compare (for instance if ESPN changed the shape of
-- its stat lines).
--
-- A warning, not an error: it is expected for a day or two in season, before a period's
-- roster is captured again after it closes (a roster is captured before its games are
-- played). It returns nothing in CI, whose fixture rosters carry two periods of real
-- game lines (ADR 0025), and on the real 2026 season.

with rostered_league_seasons as (
    select distinct league_id, season
    from {{ ref('stg_espn__roster_entries') }}
),

played_dates as (
    select distinct official_date
    from {{ ref('stg_mlb__games') }}
    where game_type = 'R' and is_played
),

game_line_periods as (
    select distinct league_id, season, scoring_period
    from {{ ref('stg_espn__player_game_stats') }}
)

select periods.league_id, periods.season, periods.scoring_period, periods.scoring_date
from {{ ref('stg_espn__scoring_periods') }} as periods
inner join rostered_league_seasons
    using (league_id, season)
inner join played_dates
    on played_dates.official_date = periods.scoring_date
left join game_line_periods
    using (league_id, season, scoring_period)
where game_line_periods.scoring_period is null
