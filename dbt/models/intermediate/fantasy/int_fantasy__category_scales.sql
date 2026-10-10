-- One row per scored category of a league-season with rosters: the usual gap between two
-- teams in that category, and the typical size of a side's denominator. Both value facts
-- divide by these, so they are held here once.
--
-- Why a matchup margin (ADR 0010): a category is won by finishing ahead of the other team,
-- so a unit of production matters in proportion to the usual gap between two teams. A
-- margin of innings is wide and a margin of steals is narrow; dividing each category by
-- its own margin puts them in one unit, "matchup margins".
--
-- WHICH MATCHUPS THE SCALE IS MEASURED FROM (ADR 0027, amending ADR 0010). Two cases, per
-- category, decided by how much history the league has; scale_source says which.
--
--   prior_and_current_seasons   The league's earlier seasons hold at least
--       fantasy_scale_prior_matchups (100) measured matchups in the category. The scale
--       is then a blend, sqrt((S + w * p^2) / (n + w)): p is the root mean square of all
--       those earlier margins, S and n are the sum of squares and the count of this
--       season's own decided matchups, and w is the same 100. The earlier seasons count
--       as 100 matchups however many there are: more of them make p more precise, not
--       more relevant to this season. With no matchup decided the scale is p.
--
--   current_season   No such history: a new league, or a category scored for the first
--       time. The scale is measured from this league-season's own matchups, recomputed
--       from our totals, exactly as ADR 0010 had it for every league-season.
--
-- Why blend. Measured on eight seasons, a season's first two matchup periods predict the
-- scale of the rest of it with a 24% error and its earlier seasons with 9%; by the end
-- the season's own matchups are the better guide. The blend is as good as the better of
-- the two throughout. And a change in the game (a rule, how pitchers are used) is not in
-- the history: it can only reach the scale from the season's own matchups.
--
-- Why 100, twice. A scale from n near-normal margins has a relative standard error of
-- about 1 / sqrt(2n): 7% at 100, which is how much seasons differ from each other. Below
-- that, history is noisier than the thing it stands in for; at it, history and a season
-- of the same size are equally good evidence. It is a variable so that tests and the
-- isolation check can lower it. It is not a method switch.
--
-- What is blended is the league host's reported margins, for the earlier seasons and for
-- this one alike (int_fantasy__reported_matchup_margins): regular-season matchups only,
-- decided ones only, each restated for a matchup period of usual volume. One source for
-- everything in the formula; the reconciliation shows how close it is to our totals.
--
-- A RATE'S DENOMINATOR GOES WITH ITS SCALE. side_denominator converts a rate's value over
-- replacement (in numerator units over a player's own denominator) into the units of a
-- side. A rate's gaps are wider when sides are smaller, so the two are measured from the
-- same matchups with the same weights: blended, (D + 2w * q) / (2n + 2w), with q the mean
-- denominator of the earlier matchups' sides and D the sum over this season's. A rate
-- whose denominator the host never reported in earlier seasons has no measured history,
-- and takes current_season for both. A count has no denominator: its side_denominator is
-- null, and "is a rate" is read from the data, not listed here.
--
-- margin_scale is a root mean square about zero, not a standard deviation about the mean.
-- Which side of a matchup is "home" is arbitrary, and a deviation about the mean would
-- change if the two sides were swapped; sqrt(avg(margin^2)) does not.
--
-- Only league-seasons with rosters have a row (ADR 0026): this is the scale values are
-- divided by, and only they have values. Within one, the spine is the category list, so
-- a scored category with nothing measured keeps a row (matchups_measured 0, margin_scale
-- null) rather than vanishing from the facts through an inner join.
--
-- RATE CONVERSION. A rate's value over replacement arrives in numerator units over the
-- player's own denominator (earned runs x 27 saved over his outs). Dividing by
-- side_denominator turns it into the change it makes to a typical side's rate, which is
-- the unit margin_scale is in. It is a first-order conversion: a pitcher's effect on a
-- side with fewer innings than typical is larger than stated.
--
-- WHAT COMES WITH READING THE SEASON'S OWN MATCHUPS (accepted by the owner: #55, then
-- #57). Under current_season in full, under the blend damped by the weight of history
-- (the season carries 56% of it after a 126-matchup regular season):
--   * player value moves as matchups are decided or restated, even for a player whose
--     own production did not change;
--   * the players being valued are in the sides the scale is measured from;
--   * early in a season with no history the scale rests on few matchups and is noisy.
-- And with history, a league-season's values depend on its league's earlier seasons:
-- loading or correcting one moves a later one (ADR 0028).

{{ config(materialized='table') }}

with scored_values as (

    select
        values_.platform,
        values_.league_id,
        values_.season,
        values_.matchup_id,
        values_.is_home,
        categories.category_key,
        values_.denominator,
        values_.stat_value
    from {{ ref('int_fantasy__matchup_stat_values') }} as values_
    inner join {{ ref('int_fantasy__categories') }} as categories
        on categories.platform = values_.platform
        and categories.league_id = values_.league_id
        and categories.season = values_.season
        and categories.category_key = values_.stat_key

),

matchup_margins as (

    select
        home.platform,
        home.league_id,
        home.season,
        home.category_key,
        home.matchup_id,
        home.stat_value - away.stat_value as margin
    from scored_values as home
    inner join scored_values as away
        on away.platform = home.platform
        and away.league_id = home.league_id
        and away.season = home.season
        and away.matchup_id = home.matchup_id
        and away.category_key = home.category_key
    where
        home.is_home
        and not away.is_home
        and home.stat_value is not null
        and away.stat_value is not null

),

margin_scales as (

    select
        platform,
        league_id,
        season,
        category_key,
        count(*) as matchups_measured,
        -- Summed in matchup order, not avg(): the last digit of a floating-point sum depends
        -- on the order of its terms, and row order changes from build to build (#28, R4.13).
        sqrt(sum(margin * margin order by matchup_id) / count(*)) as margin_scale
    from matchup_margins
    group by platform, league_id, season, category_key

),

side_denominators as (

    select
        platform,
        league_id,
        season,
        category_key,
        avg(denominator) as side_denominator
    from scored_values
    where stat_value is not null
    group by platform, league_id, season, category_key

),

-- The league host's reported margins for this league's earlier seasons, and for this
-- league-season itself, per category. Summed in (season, matchup) order: ESPN reuses
-- matchup ids across seasons.
covered_categories as (

    select
        categories.platform,
        categories.league_id,
        categories.season,
        categories.category_key
    from {{ ref('int_fantasy__categories') }} as categories
    inner join {{ ref('int_fantasy__league_seasons') }} as league_seasons
        on league_seasons.platform = categories.platform
        and league_seasons.league_id = categories.league_id
        and league_seasons.season = categories.season
        and league_seasons.has_rosters

),

earlier_seasons as (

    select
        categories.platform,
        categories.league_id,
        categories.season,
        categories.category_key,
        count(*) as prior_matchups,
        count(distinct margins.season) as prior_seasons,
        sum(
            margins.standard_margin * margins.standard_margin
            order by margins.season, margins.matchup_id
        ) as prior_sum_of_squares,
        sum(
            (margins.home_denominator + margins.away_denominator) / margins.relative_volume
            order by margins.season, margins.matchup_id
        ) as prior_denominator_sum
    from covered_categories as categories
    inner join {{ ref('int_fantasy__reported_matchup_margins') }} as margins
        on margins.platform = categories.platform
        and margins.league_id = categories.league_id
        and margins.category_key = categories.category_key
        and margins.season < categories.season
    where margins.is_measured
    group by categories.platform, categories.league_id, categories.season, categories.category_key

),

reported_own as (

    select
        platform,
        league_id,
        season,
        category_key,
        count(*) as own_matchups,
        sum(standard_margin * standard_margin order by matchup_id) as own_sum_of_squares,
        sum((home_denominator + away_denominator) / relative_volume order by matchup_id)
            as own_denominator_sum
    from {{ ref('int_fantasy__reported_matchup_margins') }}
    where is_measured
    group by platform, league_id, season, category_key

),

chosen as (

    select
        categories.platform,
        categories.league_id,
        categories.season,
        categories.category_key,
        coalesce(earlier_seasons.prior_matchups, 0)
        >= {{ var('fantasy_scale_prior_matchups') }} as uses_history,
        {{ var('fantasy_scale_prior_matchups') }} as history_weight,
        coalesce(earlier_seasons.prior_matchups, 0) as prior_matchups,
        coalesce(earlier_seasons.prior_seasons, 0) as prior_seasons,
        earlier_seasons.prior_sum_of_squares / earlier_seasons.prior_matchups as prior_mean_square,
        earlier_seasons.prior_denominator_sum
        / (2 * earlier_seasons.prior_matchups) as prior_side_denominator,
        coalesce(reported_own.own_matchups, 0) as own_matchups,
        coalesce(reported_own.own_sum_of_squares, 0) as own_sum_of_squares,
        -- Null for a count, whose denominators are null in every row; zero for a rate
        -- with no decided matchup yet.
        case
            when earlier_seasons.prior_denominator_sum is not null
                then coalesce(reported_own.own_denominator_sum, 0)
        end as own_denominator_sum,
        coalesce(margin_scales.matchups_measured, 0) as season_matchups_measured,
        margin_scales.margin_scale as season_margin_scale,
        side_denominators.side_denominator as season_side_denominator
    from covered_categories as categories
    left join earlier_seasons
        on earlier_seasons.platform = categories.platform
        and earlier_seasons.league_id = categories.league_id
        and earlier_seasons.season = categories.season
        and earlier_seasons.category_key = categories.category_key
    left join reported_own
        on reported_own.platform = categories.platform
        and reported_own.league_id = categories.league_id
        and reported_own.season = categories.season
        and reported_own.category_key = categories.category_key
    left join margin_scales
        on margin_scales.platform = categories.platform
        and margin_scales.league_id = categories.league_id
        and margin_scales.season = categories.season
        and margin_scales.category_key = categories.category_key
    left join side_denominators
        on side_denominators.platform = categories.platform
        and side_denominators.league_id = categories.league_id
        and side_denominators.season = categories.season
        and side_denominators.category_key = categories.category_key

)

select
    platform,
    league_id,
    season,
    category_key,
    case when uses_history then own_matchups else season_matchups_measured end as matchups_measured,
    case
        when uses_history
            then sqrt(
                (own_sum_of_squares + history_weight * prior_mean_square)
                / (own_matchups + history_weight)
            )
        else season_margin_scale
    end as margin_scale,
    case
        when uses_history
            then
                (own_denominator_sum + 2 * history_weight * prior_side_denominator)
                / (2 * own_matchups + 2 * history_weight)
        else season_side_denominator
    end as side_denominator,
    case when uses_history then 'prior_and_current_seasons' else 'current_season' end
        as scale_source,
    prior_matchups as prior_matchups_measured,
    prior_seasons as prior_seasons_measured,
    case when uses_history then sqrt(prior_mean_square) end as prior_margin_scale
from chosen
