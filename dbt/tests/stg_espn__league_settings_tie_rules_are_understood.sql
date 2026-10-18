-- Every league-season with rosters uses ESPN's default for a level matchup. Returns each
-- one whose playoff_matchup_tie_rule or matchup_tie_rule is anything but 'NONE', with
-- both values.
--
-- fct_matchup_results gives a level playoff matchup to the home side, the higher seed, and
-- leaves a level regular-season matchup a tie (ADRs 0080, 0081). That is what 'NONE'
-- means in ESPN's settings, and it is the only value this project has seen. A league that
-- sets another rule would have the models apply the default silently, so the build fails
-- here by name instead (ADR 0082).
--
-- A null is a failure too, not a pass: a capture without the setting is not known to use
-- the default, and `<> 'NONE'` would let it through. `is distinct from` counts it.
--
-- Only league-seasons with rosters: a past season landed for its matchup totals alone has
-- no model that applies the rule to it (int_fantasy__league_seasons.has_rosters).

select
    settings.league_id,
    settings.season,
    settings.playoff_matchup_tie_rule,
    settings.matchup_tie_rule
from {{ ref('stg_espn__league_settings') }} as settings
inner join {{ ref('int_fantasy__league_seasons') }} as league_seasons
    on league_seasons.league_id = settings.league_id
    and league_seasons.season = settings.season
where
    league_seasons.has_rosters
    and (
        settings.playoff_matchup_tie_rule is distinct from 'NONE'
        or settings.matchup_tie_rule is distinct from 'NONE'
    )
