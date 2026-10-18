-- Every limit entry of a covered league-season must be one int_fantasy__start_limits
-- understands. Returns one row per offending entry, with the reason.
--
-- Catches a limit applied as if it were something it is not, or silently ignored, when ESPN
-- files one the build has no rule for (ADR 0071):
--
--   * an entry whose stat_id is not 33: only games started is read, so a limit on another
--     stat (the 2020 rotisserie league's 545 on stat 81) would be dropped without a word;
--   * a league-season with more than one stat-33 entry (on different slots): each period
--     would then get one row per entry, and its limit multiplied;
--   * any entry of a league-season that is not head-to-head: the limit_value of a
--     rotisserie league is a season total, and times the days of a period it would be wrong.
--
-- Covered league-seasons only (has_rosters, ADR 0026): a season landed for its matchup
-- totals alone credits nothing, so its limits are not applied and need not be understood.

with covered_entries as (

    select
        limits.league_id,
        limits.season,
        limits.lineup_slot_id,
        limits.stat_id,
        limits.limit_value,
        settings.scoring_type
    from {{ ref('stg_espn__lineup_slot_stat_limits') }} as limits
    inner join {{ ref('int_fantasy__league_seasons') }} as league_seasons
        on league_seasons.platform = 'espn'
        and league_seasons.league_id = limits.league_id
        and league_seasons.season = limits.season
        and league_seasons.has_rosters
    left join {{ ref('stg_espn__league_settings') }} as settings
        on settings.league_id = limits.league_id
        and settings.season = limits.season

),

games_started_entries as (

    select
        league_id,
        season,
        count(*) as entries
    from covered_entries
    where stat_id = 33
    group by league_id, season

),

reasons as (

    select
        covered_entries.*,
        'stat_id is not 33' as reason
    from covered_entries
    where covered_entries.stat_id != 33

    union all

    select
        covered_entries.*,
        'more than one stat 33 entry in the league-season' as reason
    from covered_entries
    inner join games_started_entries
        on games_started_entries.league_id = covered_entries.league_id
        and games_started_entries.season = covered_entries.season
    where covered_entries.stat_id = 33 and games_started_entries.entries > 1

    union all

    select
        covered_entries.*,
        'scoring_type is not head-to-head' as reason
    from covered_entries
    where not coalesce(starts_with(covered_entries.scoring_type, 'H2H_'), false)

)

select
    league_id,
    season,
    lineup_slot_id,
    stat_id,
    limit_value,
    scoring_type,
    reason
from reasons
