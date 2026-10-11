-- The two ways of mapping a scoring period to its matchup period give the same answer.
--
-- stg_espn__matchup_periods reads the keys of each side's `pointsByScoringPeriod`;
-- stg_espn__matchup_days reads which matchup period ESPN marked, in the response for that
-- scoring period, with `rosterForCurrentScoringPeriod` (ADR 0055). int_fantasy__matchup_periods
-- takes the first and falls back to the second, so a disagreement would be invisible there:
-- it is where the marker is checked against the established source. Returns every scoring
-- period the two map to different matchup periods. A scoring period only one of them
-- knows is not a disagreement and is not returned.

select
    periods.league_id,
    periods.season,
    periods.scoring_period,
    periods.matchup_period as points_matchup_period,
    days.matchup_period as marker_matchup_period
from {{ ref('stg_espn__matchup_periods') }} as periods
inner join {{ ref('stg_espn__matchup_days') }} as days
    on days.league_id = periods.league_id
    and days.season = periods.season
    and days.scoring_period = periods.scoring_period
where days.matchup_period != periods.matchup_period
