-- Independent check of the scoring-period dates against ESPN's own game lines: on each
-- scoring period, ESPN never scores more games than MLB played on the mapped date.
--
-- The model dates periods from ESPN's pro schedule (ADR 0023); this test remains the
-- cross-source count check against MLB's games. ESPN's player_game_stats rows, keyed by
-- scoring period, are compared with MLB's schedule. This catches a whole-season shift of
-- the mapping: shifted by a day or more, many periods are held against a day with fewer
-- games.
--
-- It compares counts, not games (ESPN's game ids are not MLB's), so it is a partial
-- signal: it shows there were enough games that day, not that they were the same games.
-- The player-level check is rec_espn__player_day_differences.
--
-- `>` and not `!=`: ESPN's lines cover only rostered players, so a game in which no
-- rostered player appeared is missing from ESPN's side and is no error.
--
-- In CI it reads three periods of real ESPN lines (periods 1, 6 and 7 of a seven-period
-- season): the fixture rosters are from the MLB fixture days (ADR 0025, ADR 0030).
-- See stg_espn__scoring_periods_have_game_lines_to_check, which warns when a period has
-- no line to check.

with espn_games as (
    select
        league_id,
        season,
        scoring_period,
        count(distinct espn_game_id) as espn_games
    from {{ ref('stg_espn__player_game_stats') }}
    group by league_id, season, scoring_period
),

mlb_games as (
    select
        official_date,
        count(*) as mlb_games
    from {{ ref('stg_mlb__games') }}
    where game_type = 'R' and is_played
    group by official_date
)

select
    espn_games.*,
    periods.scoring_date,
    mlb_games.mlb_games
from espn_games
inner join {{ ref('stg_espn__scoring_periods') }} as periods
    using (league_id, season, scoring_period)
left join mlb_games
    on mlb_games.official_date = periods.scoring_date
where espn_games.espn_games > coalesce(mlb_games.mlb_games, 0)
