-- One row per (matchup side, stat) on either end: our recomputed value against ESPN's
-- scoreByStat, and a status saying whether any difference is accounted for.
--
-- This is the reconciliation (#10). It pairs the production marts' inputs with ESPN
-- staging, which only this boundary may do. A full outer join, so a side or stat that
-- exists on one end only is a row with a status, never silently dropped.
--
-- Only league-seasons with rosters are compared (ADR 0026). A past season loaded for its
-- matchup totals alone has ESPN's side and, by design, nothing of ours: every one of its
-- rows would be 'missing_ours', which is a finding about a season we compute, not a
-- description of one we do not. ESPN's side is restricted where it is read, so the
-- formula check and the bye rule below see the same seasons.
--
-- ESPN keeps two records of a matchup: the side total that decided it (scoreByStat) and,
-- for every player, the line it credited him with (rosterForMatchupPeriod, read by
-- stg_espn__matchup_player_lines). The statuses set our value against both, through
-- rec_espn__matchup_line_totals (the sum of a side's lines, counts only). The first link is
-- our value, less its game-line difference, equalling the lines; the second is the lines
-- differing from ESPN's total (spec 0147).
--
-- status, decided in this order:
--   bye                    ESPN reports the bye team's stats; a bye has no opponent or
--                          result, and is out of scope (2 sides in 2026).
--   missing_ours           ESPN has the side or stat, we don't.
--   missing_espn           we have it, ESPN doesn't.
--   unverified             the side rests on a missing boxscore or unresolved player
--                          (#25): not compared, because a difference would prove nothing.
--   formula_mismatch       a rate: our formula applied to ESPN's OWN components ran, and
--                          does not reproduce ESPN's rate. The formula is wrong, whatever
--                          our inputs say. A rate for which ESPN gives no components (2018
--                          has no at-bats, hits allowed, walks allowed or earned runs) has
--                          no formula value: the check did not run, and the rate goes on to
--                          the value statuses below (ADR 0063).
--   match                  within tolerance: exact for counts, 1e-6 for rates.
--   registered             a count off by exactly the difference recorded for this
--                          league-season, matchup, side and stat in the
--                          espn_reconciliation_residuals seed, with its cause.
--   explained_by_game_lines  a count with no register row, off by exactly (1e-9) the sum of
--                          this side's player-day differences against ESPN's own game
--                          lines for the stat (game_line_difference). The cause is not
--                          named; it is very likely an official scoring change (ADR 0064).
--                          A register row always wins: this is decided after 'registered'.
--                          A count of several components (SVHD, saves plus holds) takes
--                          the sum of its components' game-line differences (ADR 0075).
--   explained_by_matchup_lines  a count with no register row that is not
--                          explained_by_game_lines, whose value less its game-line
--                          difference (0 when it has none) equals the sum of ESPN's
--                          matchup lines for the side and stat (matchup_line_value),
--                          while that sum differs from ESPN's total. Our value reaches
--                          ESPN's own lines exactly, and ESPN's total is where it parts
--                          from them (ADR 0074). The cause is not named: seven past-season
--                          sides played a suspended game (C7) and most of the rest are
--                          the season's last matchups (C8). A side with no lines is never
--                          explained this way; a stat absent from a side that has lines is
--                          0. What ESPN's lines apply and we do not still fails: the games-
--                          started limit's start (C4, C17).
--   explained_by_component a rate that differs from ESPN's but equals, within 1e-6, the
--                          rate the register implies: our rules applied to ESPN's own
--                          components, each shifted by its registered difference on
--                          this side, or, where it has none, by our value less ESPN's if
--                          the component is explained_by_matchup_lines, or by its
--                          game-line difference (ADRs 0064, 0074). Rates are never
--                          registered themselves; their difference must follow exactly
--                          from the components'.
--   unexplained            anything else. The singular test fails on it.
--
-- formula_checked says whether the formula check ran (ADR 0063): true for a rate whose
-- espn_formula_value is not null, false for a rate whose is null, null for a count. A rate
-- with a recovered part (below) has no formula value either, so it stays false: a
-- recovered part reproduces ESPN's rate by construction, and the formula was not checked.
--
-- A rate part ESPN does not report (ADR 0076; 2018's AB, hits and walks allowed, earned
-- runs). When one part of a rate (numerator or denominator) has no component in ESPN's
-- side totals and the other has all of its own, ESPN's total of the missing part is
-- recovered from ESPN's rate: weighted missing part = rate x weighted reported part (a
-- missing numerator), or reported part / rate (a missing denominator), divided by the
-- missing part's weight (AB = H / AVG; hits plus walks allowed = WHIP x outs / 3; ER = ERA
-- x outs / 27). A recovered total within 1e-4 of a whole number is used, rounded
-- (recovered_value, a sum over the part's components); otherwise, with a zero rate or a
-- zero reported part, nothing is recovered and the rate is judged as before. The recovered
-- part is then ESPN's component total in the implied value, shifted by the game-line
-- difference of its components if our part less that difference equals it; otherwise by
-- our part less ESPN's, if our part less the difference equals the matchup lines' sum for
-- the part and that sum differs from the recovered total; otherwise by 0. Our part comes
-- from the side's credited components, since a stat ESPN does not report has no value row.
--
-- A registered residual that no longer occurs leaves its seed row attached to no
-- 'registered' row; the test fails on that too, so the register cannot go stale.

{{ config(materialized='table') }}

with rules as (

    select * from {{ ref('int_fantasy__stat_components') }}
    where platform = 'espn'

),

rate_stats as (

    select distinct stat_key from rules
    where part = 'denominator'

),

single_component_stats as (

    -- The bridge from a component column to the ESPN stat that is exactly it.
    {{ fo_single_component_stats('rules') }}

),

composite_stats as (

    -- Counts built from several components, all numerators of weight 1 and each one the
    -- component of a single-component stat (SVHD is saves plus holds): ADR 0075.
    select rules.stat_key
    from rules
    left join single_component_stats as bridge
        on bridge.component = rules.component
    group by rules.stat_key
    having
        count(*) > 1
        and min(rules.part) = 'numerator'
        and max(rules.part) = 'numerator'
        and min(rules.weight) = 1
        and max(rules.weight) = 1
        and count(bridge.stat_key) = count(*)

),

covered as (

    select
        league_id,
        season
    from {{ ref('int_fantasy__league_seasons') }}
    where platform = 'espn' and has_rosters

),

espn as (

    select
        results.league_id,
        results.season,
        results.matchup_id,
        results.team_id as fantasy_team_id,
        results.stat_id as stat_key,
        results.score as espn_value
    from {{ ref('stg_espn__matchup_category_results') }} as results
    inner join covered
        on covered.league_id = results.league_id
        and covered.season = results.season

),

played_matchups as (

    select
        league_id,
        season,
        matchup_id
    from {{ ref('stg_espn__matchups') }}

),

ours as (

    select
        stat_values.league_id,
        stat_values.season,
        stat_values.matchup_id,
        stat_values.fantasy_team_id,
        stat_values.stat_key,
        stat_values.stat_value as our_value,
        totals.verified_player_days = totals.started_player_days as is_verified
    from {{ ref('int_fantasy__matchup_stat_values') }} as stat_values
    inner join {{ ref('int_fantasy__matchup_side_totals') }} as totals
        on totals.platform = stat_values.platform
        and totals.league_id = stat_values.league_id
        and totals.season = stat_values.season
        and totals.matchup_id = stat_values.matchup_id
        and totals.fantasy_team_id = stat_values.fantasy_team_id
    where stat_values.platform = 'espn'

),

register as (

    select * from {{ ref('espn_reconciliation_residuals') }}

),

-- The sum of each side's ESPN matchup lines per count stat, for the sides that have lines
-- (spec 0147). A side with no lines has no row here.
line_totals as (

    select
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        stat_key,
        matchup_line_value
    from {{ ref('rec_espn__matchup_line_totals') }}

),

-- What ESPN's own game lines say of each side and stat: the sum of the player-day
-- differences against them (ADR 0064). Read from rec_espn__player_day_differences and not
-- from rec_espn__player_day_residuals, which reads this table.
single_game_lines as (

    select
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        stat_id as stat_key,
        -- In a fixed order, as every floating-point sum here is: the player-day key.
        {{ fo_sum_in_order(
            'difference', 'scoring_date, platform_player_id'
        ) }} as game_line_difference
    from {{ ref('rec_espn__player_day_differences') }}
    where status = 'difference'
    group by league_id, season, matchup_id, fantasy_team_id, stat_id

),

-- A composite count's game-line difference is the sum of its components' (ADR 0075). A
-- component with no player-day difference adds nothing; a side none of whose components
-- has one has no row, so game_line_difference stays null, as for a single stat.
composite_game_lines as (

    select
        single_game_lines.league_id,
        single_game_lines.season,
        single_game_lines.matchup_id,
        single_game_lines.fantasy_team_id,
        rules.stat_key,
        {{ fo_sum_in_order(
            'single_game_lines.game_line_difference', 'bridge.stat_key'
        ) }} as game_line_difference
    from single_game_lines
    inner join single_component_stats as bridge
        on bridge.stat_key = single_game_lines.stat_key
    inner join rules
        on rules.component = bridge.component
    inner join composite_stats
        on composite_stats.stat_key = rules.stat_key
    group by
        single_game_lines.league_id,
        single_game_lines.season,
        single_game_lines.matchup_id,
        single_game_lines.fantasy_team_id,
        rules.stat_key

),

game_lines as (

    select * from single_game_lines

    union all

    select * from composite_game_lines

),

compared as (

    select
        coalesce(ours.league_id, espn.league_id) as league_id,
        coalesce(ours.season, espn.season) as season,
        coalesce(ours.matchup_id, espn.matchup_id) as matchup_id,
        coalesce(ours.fantasy_team_id, espn.fantasy_team_id) as fantasy_team_id,
        coalesce(ours.stat_key, espn.stat_key) as stat_key,
        ours.our_value,
        espn.espn_value,
        ours.our_value - espn.espn_value as difference,
        ours.is_verified,
        ours.stat_key is not null as has_ours,
        espn.stat_key is not null as has_espn
    from ours
    full outer join espn
        on espn.league_id = ours.league_id
        and espn.season = ours.season
        and espn.matchup_id = ours.matchup_id
        and espn.fantasy_team_id = ours.fantasy_team_id
        and espn.stat_key = ours.stat_key

),

-- Each compared row with what the register, the game lines and the matchup lines say of
-- it, and whether its status is explained_by_matchup_lines. The flag is decided here, and
-- the status below only reads it, so a rate can ask it of each of its components: it
-- repeats the order of the status (a row that is a match, registered or
-- explained_by_game_lines is not flagged).
evidence as (

    select
        compared.league_id,
        compared.season,
        compared.matchup_id,
        compared.fantasy_team_id,
        compared.stat_key,
        compared.our_value,
        compared.espn_value,
        register.expected_difference as registered_difference,
        register.cause as registered_cause,
        game_lines.game_line_difference,
        line_totals.matchup_line_value,
        coalesce(
            compared.has_ours
            and compared.has_espn
            and compared.is_verified
            and rate_stats.stat_key is null
            and register.expected_difference is null
            and abs(compared.difference) > 1e-9
            and not coalesce(
                abs(compared.difference - game_lines.game_line_difference) <= 1e-9, false
            )
            and line_totals.matchup_line_value is not null
            and abs(
                compared.our_value
                - coalesce(game_lines.game_line_difference, 0)
                - line_totals.matchup_line_value
            ) <= 1e-9
            and abs(line_totals.matchup_line_value - compared.espn_value) > 1e-9,
            false
        ) as is_explained_by_matchup_lines
    from compared
    left join rate_stats
        on rate_stats.stat_key = compared.stat_key
    left join register
        on register.league_id = compared.league_id
        and register.season = compared.season
        and register.matchup_id = compared.matchup_id
        and register.team_id = compared.fantasy_team_id
        and register.stat_id = compared.stat_key
    left join game_lines
        on game_lines.league_id = compared.league_id
        and game_lines.season = compared.season
        and game_lines.matchup_id = compared.matchup_id
        and game_lines.fantasy_team_id = compared.fantasy_team_id
        and game_lines.stat_key = compared.stat_key
    left join line_totals
        on line_totals.league_id = compared.league_id
        and line_totals.season = compared.season
        and line_totals.matchup_id = compared.matchup_id
        and line_totals.fantasy_team_id = compared.fantasy_team_id
        and line_totals.stat_key = compared.stat_key

),

-- Each rate's components, with ESPN's score and the shift the evidence puts on it: its
-- registered difference; otherwise our value less ESPN's if it is
-- explained_by_matchup_lines; otherwise its game-line difference; otherwise 0.
rate_components as (

    select
        espn.league_id,
        espn.season,
        espn.matchup_id,
        espn.fantasy_team_id,
        rules.stat_key,
        rules.part,
        rules.component,
        rules.weight,
        component_scores.espn_value as component_value,
        coalesce(
            component_evidence.registered_difference,
            case
                when component_evidence.is_explained_by_matchup_lines
                    then component_evidence.our_value - component_evidence.espn_value
            end,
            component_evidence.game_line_difference,
            0
        ) as component_shift
    from espn
    inner join rules
        on rules.stat_key = espn.stat_key
    inner join rate_stats
        on rate_stats.stat_key = rules.stat_key
    inner join single_component_stats as bridge
        on bridge.component = rules.component
    inner join espn as component_scores
        on component_scores.league_id = espn.league_id
        and component_scores.season = espn.season
        and component_scores.matchup_id = espn.matchup_id
        and component_scores.fantasy_team_id = espn.fantasy_team_id
        and component_scores.stat_key = bridge.stat_key
    left join evidence as component_evidence
        on component_evidence.league_id = espn.league_id
        and component_evidence.season = espn.season
        and component_evidence.matchup_id = espn.matchup_id
        and component_evidence.fantasy_team_id = espn.fantasy_team_id
        and component_evidence.stat_key = bridge.stat_key

),

-- Each rate recomputed by our rules from ESPN's own component scores, twice: as ESPN
-- reports them (which must reproduce ESPN's rate -- the formula check), and shifted (the
-- rate the evidence implies -- what ours must be). The shifted numerator and denominator
-- are kept apart, so that a recovered part can stand in for the one ESPN does not report.
espn_formula as (

    select
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        stat_key,
        -- In component order, as every floating-point sum here is (AGENTS.md, ADR 0046).
        {{ fo_sum_in_order(
            "case when part = 'numerator' then weight * component_value end", 'component'
        ) }}
        / nullif({{ fo_sum_in_order(
            "case when part = 'denominator' then weight * component_value end", 'component'
        ) }}, 0)
            as espn_formula_value,
        {{ fo_sum_in_order(
            "case when part = 'numerator' then weight * (component_value + component_shift) end",
            'component'
        ) }} as implied_numerator,
        {{ fo_sum_in_order(
            "case when part = 'denominator' then weight * (component_value + component_shift) end",
            'component'
        ) }} as implied_denominator
    from rate_components
    group by league_id, season, matchup_id, fantasy_team_id, stat_key

),

-- A rate's two parts, per side: how many components each has, how many of them ESPN
-- reports, and ESPN's weighted total of those it reports (ADR 0076). A component is
-- reported when it is a single-component stat ESPN gives a score for on the side.
rate_parts as (

    select
        espn.league_id,
        espn.season,
        espn.matchup_id,
        espn.fantasy_team_id,
        espn.stat_key,
        espn.espn_value as rate_value,
        rules.part,
        count(*) as components,
        count(component_scores.espn_value) as reported,
        min(rules.weight) as weight_low,
        max(rules.weight) as weight_high,
        {{ fo_sum_in_order(
            'rules.weight * component_scores.espn_value', 'rules.component'
        ) }} as weighted_espn
    from espn
    inner join rate_stats
        on rate_stats.stat_key = espn.stat_key
    inner join rules
        on rules.stat_key = espn.stat_key
    left join single_component_stats as bridge
        on bridge.component = rules.component
    left join espn as component_scores
        on component_scores.league_id = espn.league_id
        and component_scores.season = espn.season
        and component_scores.matchup_id = espn.matchup_id
        and component_scores.fantasy_team_id = espn.fantasy_team_id
        and component_scores.stat_key = bridge.stat_key
    group by
        espn.league_id,
        espn.season,
        espn.matchup_id,
        espn.fantasy_team_id,
        espn.stat_key,
        espn.espn_value,
        rules.part

),

-- The rates with exactly one part wholly unreported and the other fully reported, and
-- ESPN's weighted total of the missing part, if it can be had: a rate of zero or a
-- reported part of zero gives none, nor does a part whose components differ in weight.
recoverable as (

    select
        numerators.league_id,
        numerators.season,
        numerators.matchup_id,
        numerators.fantasy_team_id,
        numerators.stat_key,
        case
            when numerators.reported = 0 and denominators.reported = denominators.components
                then 'numerator'
            when denominators.reported = 0 and numerators.reported = numerators.components
                then 'denominator'
        end as missing_part,
        case
            when
                numerators.reported = 0
                and denominators.reported = denominators.components
                and numerators.rate_value != 0
                and denominators.weighted_espn != 0
                and numerators.weight_low = numerators.weight_high
                then numerators.rate_value * denominators.weighted_espn / numerators.weight_low
            when
                denominators.reported = 0
                and numerators.reported = numerators.components
                and numerators.rate_value != 0
                and numerators.weighted_espn != 0
                and denominators.weight_low = denominators.weight_high
                then numerators.weighted_espn / numerators.rate_value / denominators.weight_low
        end as recovered_raw,
        case
            when numerators.reported = 0 then numerators.weight_low else denominators.weight_low
        end as missing_weight
    from rate_parts as numerators
    inner join rate_parts as denominators
        on denominators.league_id = numerators.league_id
        and denominators.season = numerators.season
        and denominators.matchup_id = numerators.matchup_id
        and denominators.fantasy_team_id = numerators.fantasy_team_id
        and denominators.stat_key = numerators.stat_key
    where numerators.part = 'numerator' and denominators.part = 'denominator'

),

recovered as (

    select
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        stat_key,
        missing_part,
        missing_weight,
        round(recovered_raw) as recovered_value
    from recoverable
    where
        missing_part is not null
        and recovered_raw is not null
        and abs(recovered_raw - round(recovered_raw)) <= 1e-4

),

-- The components of each recovered part, with the evidence for each: our credited total
-- (the side's totals, picked by component name: a stat ESPN does not report has no value
-- row), the game-line difference and the matchup lines.
recovered_components as (

    select
        recovered.league_id,
        recovered.season,
        recovered.matchup_id,
        recovered.fantasy_team_id,
        recovered.stat_key,
        recovered.missing_weight,
        recovered.recovered_value,
        rules.component,
        game_lines.game_line_difference,
        line_totals.matchup_line_value,
        case rules.component
            {%- for column in fo_batting_columns() + fo_pitching_columns() %}
            when '{{ column }}' then totals.{{ column }}
            {%- endfor %}
        end as our_component
    from recovered
    inner join rules
        on rules.stat_key = recovered.stat_key
        and rules.part = recovered.missing_part
    left join single_component_stats as bridge
        on bridge.component = rules.component
    left join {{ ref('int_fantasy__matchup_side_totals') }} as totals
        on totals.platform = 'espn'
        and totals.league_id = recovered.league_id
        and totals.season = recovered.season
        and totals.matchup_id = recovered.matchup_id
        and totals.fantasy_team_id = recovered.fantasy_team_id
    left join game_lines
        on game_lines.league_id = recovered.league_id
        and game_lines.season = recovered.season
        and game_lines.matchup_id = recovered.matchup_id
        and game_lines.fantasy_team_id = recovered.fantasy_team_id
        and game_lines.stat_key = bridge.stat_key
    left join line_totals
        on line_totals.league_id = recovered.league_id
        and line_totals.season = recovered.season
        and line_totals.matchup_id = recovered.matchup_id
        and line_totals.fantasy_team_id = recovered.fantasy_team_id
        and line_totals.stat_key = bridge.stat_key

),

-- Each recovered part summed over its components: ours, the game-line differences (none
-- counts as 0) and the matchup lines (null if any component has none).
recovered_parts as (

    select
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        stat_key,
        missing_weight,
        recovered_value,
        count(*) as components,
        count(our_component) as ours_present,
        count(matchup_line_value) as lines_present,
        {{ fo_sum_in_order('our_component', 'component') }} as part_ours,
        {{ fo_sum_in_order('coalesce(game_line_difference, 0)', 'component') }} as part_game_lines,
        {{ fo_sum_in_order('matchup_line_value', 'component') }} as part_matchup_lines
    from recovered_components
    group by
        league_id, season, matchup_id, fantasy_team_id, stat_key, missing_weight, recovered_value

),

-- The recovered part's shift (R3.4), in component units.
recovered_shifts as (

    select
        parts.league_id,
        parts.season,
        parts.matchup_id,
        parts.fantasy_team_id,
        parts.stat_key,
        parts.missing_weight,
        parts.recovered_value,
        case
            when
                parts.ours_present = parts.components
                and abs(parts.part_ours - parts.part_game_lines - parts.recovered_value) <= 1e-9
                then parts.part_game_lines
            when
                parts.ours_present = parts.components
                and parts.lines_present = parts.components
                and abs(parts.part_ours - parts.part_game_lines - parts.part_matchup_lines) <= 1e-9
                and abs(parts.part_matchup_lines - parts.recovered_value) > 1e-9
                then parts.part_ours - parts.recovered_value
            else 0
        end as part_shift
    from recovered_parts as parts

),

-- The rate the evidence implies. A recovered part stands in for the one ESPN does not
-- report, at its weight.
implied_rates as (

    select
        espn_formula.league_id,
        espn_formula.season,
        espn_formula.matchup_id,
        espn_formula.fantasy_team_id,
        espn_formula.stat_key,
        espn_formula.espn_formula_value,
        recovered.recovered_value,
        case
            when recovered.recovered_value is null
                then espn_formula.implied_numerator / nullif(espn_formula.implied_denominator, 0)
            when recovered.missing_part = 'numerator'
                then
                    recovered.missing_weight
                    * (recovered.recovered_value + recovered_shifts.part_shift)
                    / nullif(espn_formula.implied_denominator, 0)
            else
                espn_formula.implied_numerator
                / nullif(
                    recovered.missing_weight
                    * (recovered.recovered_value + recovered_shifts.part_shift),
                    0
                )
        end as implied_value
    from espn_formula
    left join recovered
        on recovered.league_id = espn_formula.league_id
        and recovered.season = espn_formula.season
        and recovered.matchup_id = espn_formula.matchup_id
        and recovered.fantasy_team_id = espn_formula.fantasy_team_id
        and recovered.stat_key = espn_formula.stat_key
    left join recovered_shifts
        on recovered_shifts.league_id = espn_formula.league_id
        and recovered_shifts.season = espn_formula.season
        and recovered_shifts.matchup_id = espn_formula.matchup_id
        and recovered_shifts.fantasy_team_id = espn_formula.fantasy_team_id
        and recovered_shifts.stat_key = espn_formula.stat_key

),

annotated as (

    select
        compared.*,
        rate_stats.stat_key is not null as is_rate,
        case when rate_stats.stat_key is not null then 1e-6 else 1e-9 end as tolerance,
        implied_rates.espn_formula_value,
        implied_rates.implied_value,
        implied_rates.recovered_value,
        played_matchups.matchup_id is null as is_bye,
        evidence.registered_difference,
        evidence.registered_cause,
        evidence.game_line_difference,
        evidence.matchup_line_value,
        evidence.is_explained_by_matchup_lines
    from compared
    left join rate_stats
        on rate_stats.stat_key = compared.stat_key
    left join implied_rates
        on implied_rates.league_id = compared.league_id
        and implied_rates.season = compared.season
        and implied_rates.matchup_id = compared.matchup_id
        and implied_rates.fantasy_team_id = compared.fantasy_team_id
        and implied_rates.stat_key = compared.stat_key
    left join played_matchups
        on played_matchups.league_id = compared.league_id
        and played_matchups.season = compared.season
        and played_matchups.matchup_id = compared.matchup_id
    left join evidence
        on evidence.league_id = compared.league_id
        and evidence.season = compared.season
        and evidence.matchup_id = compared.matchup_id
        and evidence.fantasy_team_id = compared.fantasy_team_id
        and evidence.stat_key = compared.stat_key

)

select
    league_id,
    season,
    matchup_id,
    fantasy_team_id,
    stat_key,
    is_rate,
    our_value,
    espn_value,
    difference,
    espn_formula_value,
    case when is_rate then espn_formula_value is not null end as formula_checked,
    implied_value,
    recovered_value,
    registered_difference,
    registered_cause,
    game_line_difference,
    matchup_line_value,
    case
        when not has_ours and is_bye then 'bye'
        when not has_ours then 'missing_ours'
        when not has_espn then 'missing_espn'
        when not is_verified then 'unverified'
        when
            is_rate and espn_formula_value is not null
            and abs(espn_formula_value - espn_value) > tolerance then 'formula_mismatch'
        when
            our_value is not null and abs(difference) <= tolerance
            and registered_difference is null then 'match'
        when
            not is_rate and registered_difference is not null
            and abs(difference - registered_difference) <= tolerance then 'registered'
        when
            not is_rate and registered_difference is null
            and game_line_difference is not null
            and abs(difference - game_line_difference) <= tolerance then 'explained_by_game_lines'
        when is_explained_by_matchup_lines then 'explained_by_matchup_lines'
        when
            is_rate and our_value is not null and implied_value is not null
            and abs(our_value - implied_value) <= tolerance then 'explained_by_component'
        else 'unexplained'
    end as status
from annotated
