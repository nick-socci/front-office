-- Every scoring period a matchup period covers is a scoring period of ITS OWN league and
-- season.
--
-- This replaces a single-column `relationships` test on scoring_period, which compared
-- the value alone: with a long season and a short one loaded, a matchup of the short
-- season pointing at a period that exists only in the long one would have passed (#28).
-- Returns the offending rows.

select
    matchup_periods.league_id,
    matchup_periods.season,
    matchup_periods.matchup_period,
    matchup_periods.scoring_period
from {{ ref('stg_espn__matchup_periods') }} as matchup_periods
left join {{ ref('stg_espn__scoring_periods') }} as scoring_periods
    on scoring_periods.league_id = matchup_periods.league_id
    and scoring_periods.season = matchup_periods.season
    and scoring_periods.scoring_period = matchup_periods.scoring_period
where scoring_periods.scoring_period is null
