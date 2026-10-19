{{ config(severity='warn') }}

-- Every league-season with rosters has a count of scheduled matchups M the scales can use.
-- Returns each one whose settings give no positive M, with the two settings M comes from:
-- matchup_period_count null, team_count null, or matchup_period_count * floor(team_count / 2)
-- not above 0. A null team_count already fails the build at the not_null test of
-- stg_espn__league_settings (spec 0161, amendment of 2026-10-18), so its clause here is a
-- backstop; the case this test is for is a settings capture without the matchup period count.
--
-- It warns rather than fails (the owner's choice, 2026-10-18): the scales of such a
-- league-season fall back to ADR 0027's weight, fantasy_scale_prior_matchups, so a live
-- season is still valued. The warning names it, so the first in-season build shows a
-- settings capture without the count.
--
-- Catches: a missing M going unseen (spec 0161, R1.8; ADR 0086).

select
    settings.league_id,
    settings.season,
    settings.matchup_period_count,
    settings.team_count
from {{ ref('stg_espn__league_settings') }} as settings
inner join {{ ref('int_fantasy__league_seasons') }} as league_seasons
    on league_seasons.league_id = settings.league_id
    and league_seasons.season = settings.season
where
    league_seasons.has_rosters
    and (
        settings.matchup_period_count is null
        or settings.team_count is null
        or settings.matchup_period_count * floor(settings.team_count / 2) <= 0
    )
