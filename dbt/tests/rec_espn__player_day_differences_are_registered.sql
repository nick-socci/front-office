-- Every player-day difference is accounted for: by the register of known residuals, or by
-- ESPN's own matchup lines when they differ from ours by the same amount (ADR 0077).
-- Returns each (matchup, side, stat) with a verified difference that neither accounts for,
-- with why: no register row and not carried by the lines, or a register row of another size.
--
-- Catches a scoring change nobody registered and the lines do not carry, including
-- differences that cancel on a side and so leave its total matching; a register row of the
-- wrong size; a difference in one league-season excused by another league-season's register
-- row; and a player-day ESPN credited differently from us, which its matchup lines leave
-- out (a start past the games-started limit, #152).
--
-- In CI this judges nothing: no fixture row is a difference (every fixture started
-- player-day is missing_boxscore, so every row is unverified). Its rule is exercised there
-- by the unit tests of rec_espn__player_day_residuals; the real season is where it bites.
--
-- The rule itself is the `problem` column of the view, where unit tests hold it.

select
    league_id,
    season,
    matchup_id,
    fantasy_team_id,
    stat_id,
    difference_sum,
    difference_rows,
    expected_difference,
    problem
from {{ ref('rec_espn__player_day_residuals') }}
where problem is not null
