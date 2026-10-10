-- Identities between fct_player_season_value's day counts and the started-day grain it is
-- counted from. Returns each (player, team) that breaks one.
--
--   played_started_days <= started_days, started_days_outside_matchups <= started_days
--   first_started_date <= last_started_date
--   started_days equals the count of the pair's rows in int_fantasy__started_player_days
--   unverified_started_days equals the count of those whose input_status is neither
--     'played' nor 'verified_off', recomputed here from the day grain (R4.5)
--   played_started_days equals the days with an appearance on the side the slot credits
--     (hitter slot and games_batted > 0, pitcher slot and games_pitched > 0), recomputed
--     here from the day grain (R4.4)
--   every row of fct_player_category_value carries the played days of ITS side: hitter-slot
--     days batted on a batting category, pitcher-slot days pitched on a pitching one
--     (R4.7). Compared side by side, never as a sum, so days put on the wrong side show
--
-- Catches bye-week days vanishing, unverified zeroes counted as real days, a count taken
-- from the wrong model, played days counted from the grain's any-appearance `played`
-- flag, and the two facts disagreeing about how many days a pair played.

-- The pair is (platform, league, season, player, team): the recomputation is keyed by all
-- five, or a player on team 3 of two leagues would be compared with the sum of both (#28).

with recomputed as (

    select
        platform,
        league_id,
        season,
        platform_player_id,
        fantasy_team_id,
        count(*) as started_days,
        count(*) filter (where input_status not in ('played', 'verified_off'))
            as unverified_started_days,
        count(*) filter (where slot_role = 'hitter' and games_batted > 0) as hitter_played_days,
        count(*) filter (where slot_role = 'pitcher' and games_pitched > 0) as pitcher_played_days
    from {{ ref('int_fantasy__started_player_days') }}
    group by platform, league_id, season, platform_player_id, fantasy_team_id

)

select
    fact.platform_player_id,
    fact.fantasy_team_id
from {{ ref('fct_player_season_value') }} as fact
left join recomputed
    on recomputed.platform = fact.platform
    and recomputed.league_id = fact.league_id
    and recomputed.season = fact.season
    and recomputed.platform_player_id = fact.platform_player_id
    and recomputed.fantasy_team_id = fact.fantasy_team_id
where
    fact.played_started_days > fact.started_days
    or fact.started_days_outside_matchups > fact.started_days
    or fact.first_started_date > fact.last_started_date
    or fact.started_days is distinct from recomputed.started_days
    or fact.unverified_started_days is distinct from recomputed.unverified_started_days
    or fact.played_started_days
    is distinct from recomputed.hitter_played_days + recomputed.pitcher_played_days

union

-- A category's side comes from its components in int_fantasy__stat_components and the
-- fo_*_columns lists, NOT from the fact row being checked: a row whose side and played
-- days were both wrong would otherwise agree with itself.
select
    categories.platform_player_id,
    categories.fantasy_team_id
from {{ ref('fct_player_category_value') }} as categories
inner join (
    select
        platform,
        stat_key as category_key,
        max(
            case
                when
                    component in (
                        '{{ fo_batting_columns() | join("', '") }}'
                    )
                    then 'batting'
                else 'pitching'
            end
        )
            as side
    from {{ ref('int_fantasy__stat_components') }}
    group by platform, stat_key
) as category_sides
    on category_sides.platform = categories.platform
    and category_sides.category_key = categories.category_key
left join recomputed
    on recomputed.platform = categories.platform
    and recomputed.league_id = categories.league_id
    and recomputed.season = categories.season
    and recomputed.platform_player_id = categories.platform_player_id
    and recomputed.fantasy_team_id = categories.fantasy_team_id
where
    categories.played_days is distinct from
    case category_sides.side
        when 'batting' then recomputed.hitter_played_days
        else recomputed.pitcher_played_days
    end
