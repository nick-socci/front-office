-- Every league-season with rosters has no minimum, or one the models can apply. Returns
-- each one whose minimum cannot be read, with the stat, the limit and the scoring type.
--
-- The models apply ESPN's statQualificationMinimum only as outs (stat 34) per matchup in a
-- head-to-head league (ADRs 0083, 0085). A minimum on another stat, one with a stat but no
-- limit, or one in a league that is not head-to-head would be applied as a guess, so the
-- build fails here by name instead.
--
-- Four ways to fail:
--   - a minimum whose stat is not 34. `is distinct from` counts a null stat as a failure.
--   - a stat with no limit.
--   - a minimum that is present (has_qualification_minimum) but whose stat or limit did not
--     parse, so that it stages as null and is not mistaken for no minimum.
--   - any minimum while scoring_type is not known to be head-to-head. A null scoring_type
--     fails too. substr, not LIKE, because `_` in 'H2H_%' is a wildcard.
--
-- Only league-seasons with rosters: a past season landed for its matchup totals alone has
-- no model that applies the minimum to it (int_fantasy__league_seasons.has_rosters).

select
    settings.league_id,
    settings.season,
    settings.has_qualification_minimum,
    settings.qualification_stat_id,
    settings.qualification_minimum,
    settings.scoring_type
from {{ ref('stg_espn__league_settings') }} as settings
inner join {{ ref('int_fantasy__league_seasons') }} as league_seasons
    on league_seasons.league_id = settings.league_id
    and league_seasons.season = settings.season
where
    league_seasons.has_rosters
    and (
        (
            settings.qualification_minimum is not null
            and settings.qualification_stat_id is distinct from 34
        )
        or (
            settings.qualification_stat_id is not null
            and settings.qualification_minimum is null
        )
        or (
            settings.has_qualification_minimum
            and (
                settings.qualification_stat_id is null
                or settings.qualification_minimum is null
            )
        )
        or (
            settings.has_qualification_minimum
            and coalesce(substr(settings.scoring_type, 1, 4) = 'H2H_', false) is not true
        )
    )
