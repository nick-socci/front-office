-- A unit of total_value buys the same number of real category wins whichever group of
-- players it belongs to. Returns each league-season and replacement group that breaks
-- that, with why.
--
-- The real wins come from scoring every matchup again with each player swapped for
-- replacement (rec_fantasy__category_wins_added), which uses no scale and so is evidence
-- the value facts do not produce themselves. A judged group's slope must lie in 0.34 to
-- 0.47, about 15% either side of the 0.40 that theory gives. Scaling a group's values by
-- f divides its slope by f, so from 2026's slopes (0.43 starters, 0.40 hitters) this
-- fails when starters' values are inflated by about a quarter or hitters' by 18%, and
-- when either is deflated by 9% to 15%.
--
-- Catches a change to a replacement level, a scale or a formula that tilts one group
-- against another (spec 0089, R3.5). Which groups are judged is decided in
-- rec_fantasy__category_wins_by_group, by a measure and not by name.
--
-- A group of 100 or more pairs fails as not checkable if any of its pairs has no value or
-- no wins added (R3.8): a slope from part of a group is not the group's. Smaller groups
-- are not judged, which is all the small CI fixture is: seven days, with rosters on three.

-- The rule itself is the `problem` column of the group model, where unit tests hold it.

select
    platform,
    league_id,
    season,
    replacement_group,
    matchups_rescored,
    pairs,
    pairs_unmeasured,
    slope,
    correlation,
    problem
from {{ ref('rec_fantasy__category_wins_by_group') }}
where problem is not null
