-- A scale that says it uses the league's earlier seasons rests on at least
-- fantasy_scale_prior_matchups of their matchups, and has a scale, the history's own
-- scale, and for a rate a denominator. A scale that says it does not has no history
-- scale. Returns each row that breaks one of these, with which.
--
-- Catches a scale labelled as blended that rests on too little (the threshold applied to
-- the wrong count, or not at all), and a rate blended with no denominator to go with it
-- (spec 0057, R3.7 and R4.4). A current_season row is not held to "scale and denominator
-- together": today's method can give a rate a denominator and no scale, when one side
-- of its only matchup has a zero denominator, and that is kept as it is.

with rate_categories as (

    select distinct
        platform,
        stat_key as category_key
    from {{ ref('int_fantasy__stat_components') }}
    where part = 'denominator'

),

checked as (

    select
        scales.platform,
        scales.league_id,
        scales.season,
        scales.category_key,
        case
            when
                scales.scale_source = 'prior_and_current_seasons'
                and scales.prior_matchups_measured < {{ var('fantasy_scale_prior_matchups') }}
                then 'uses history that is below the threshold'
            when
                scales.scale_source = 'prior_and_current_seasons'
                and (scales.margin_scale is null or scales.prior_margin_scale is null)
                then 'uses history and has no scale'
            when
                scales.scale_source = 'prior_and_current_seasons'
                and rate_categories.category_key is not null
                and scales.side_denominator is null
                then 'a rate that uses history and has no denominator'
            when
                scales.scale_source = 'current_season'
                and scales.prior_matchups_measured >= {{ var('fantasy_scale_prior_matchups') }}
                then 'has enough history and does not use it'
            when
                scales.scale_source = 'current_season'
                and scales.prior_margin_scale is not null
                then 'does not use history and carries its scale'
        end as problem
    from {{ ref('int_fantasy__category_scales') }} as scales
    left join rate_categories
        on rate_categories.platform = scales.platform
        and rate_categories.category_key = scales.category_key

)

select * from checked
where problem is not null
