-- What a replacement player produces per day played, for each kind of day, in each league
-- and season: one row per (platform, league_id, season, day_kind, component), the kind being
-- batting, start or relief. Every player's value is
-- measured against this (#11, #52): a player is worth what he did above what a free agent
-- would have done in the same playing time, and a pitcher's start is measured against a
-- free agent's start, his relief appearance against a free agent's relief appearance
-- (ADR 0008).
--
-- DEFINITION, everything per league and season (#28). The batting and relief pools are the
-- top N MLB players of their kind among those nobody in THAT LEAGUE had rostered, N being
-- that league-season's own number of fantasy teams (count of int_fantasy__teams, never a
-- literal 12), joined in, not read as one scalar over every league. The start pool is not
-- a set of players at all (3b).
--   1. Free-agent days: rows of int_mlb__player_game_days, of the league-season's own MLB
--      season, on one of its scoring dates (any date of its int_fantasy__roster_days) where
--      the player is on none of ITS rosters that date. He may be rostered in another league
--      the same day and is still a free agent here.
--   2. Batting pool: free agents whose fo_replacement_group over their free-agent days is
--      hitter, top N by plate appearances, ties broken by mlbam_player_id. A played day is
--      one with games_batted > 0, and only batting components are credited, so a hitter's
--      mop-up inning is neither a played day nor a component of batting.
--   3. Relief pool: each free-agent day is classified by fo_pitching_day_kind, from that
--      day's own games_started and games_pitched. Every free agent with at least one
--      relief day is a candidate, ranked by how many he had, then by outs recorded over
--      them, then by mlbam_player_id; the top N are in. No replacement group is consulted,
--      so a hitter who pitched a mop-up inning may be in the relief pool.
--   3b. Start pool (ADR 0029, ADR 0031): every free-agent day that is a start, by a pitcher
--      who was a starter at the time, as fo_is_starter_at_the_time says, over his MLB days
--      of the season strictly before that day. He is one if any of these holds:
--        - he had not pitched yet (a debut, or the first turn of a rotation);
--        - fo_replacement_group says SP (at least half his games pitched were starts);
--        - his two most recent pitching days were both starts (a pitcher who changed role).
--      Not ranked, and not cut to N. An opener who had been relieving is not in, nor is a
--      reliever's first or only start after relief: nothing known before the game tells
--      it from an opener's, and the outing itself is never judged. Two starts running is
--      a rotation turn taken twice. In 2026 this takes 1,518 starts by 182 pitchers: 120
--      admitted by a first appearance and 108 by two starts running, on top of the 1,290
--      the count alone takes; 357 stay out. #92 was the issue, ADR 0031 the decision; a
--      role carried from a previous season waits for more than one MLB season (#83).
--   4. Level: pitching components are summed over the pool's free-agent days of that kind
--      only (the relief pool members' relief days; the start pool's days), and divided by
--      the count of those days (pool_played_days). For the start kind pool_players is the
--      number of pitchers with a day in the pool. A relief
--      pool member's start is in neither pool_total nor pool_played_days of relief.
--      level_per_played_day = pool_total / pool_played_days. This mirrors slot-role
--      crediting in int_fantasy__started_player_days: a day is credited on one side only.
--   5. Every kind gets its rows. The output starts from a spine of the league-seasons crossed
--      with the three kinds and their components and left-joins the pools, so an empty pool
--      yields rows with pool_players = 0, pool_played_days = 0 and a NULL level, not no rows
--      (which an inner join downstream would turn into players vanishing) and not 0 (which
--      would say replacement produces nothing).
-- Components only, never rates: AVG or ERA is computed from these totals downstream.
--
-- WHY THE START POOL IS DIFFERENT. Ranked like the others, by appearances while unrostered,
-- it was the twelve pitchers who started all year and whom nobody wanted: 306 starts at a
-- 5.41 ERA, when free-agent starts by starters ran at 4.89 (1,518 of them by 182 pitchers
-- in 2026, at 14.78 outs). No ranking does better: by usage at the time the
-- most-used free-agent starters are the worst (ERA 5.88 for the top 6 a week), and by
-- performance to date there are too few free-agent starters a day (about 11) to choose
-- among. And none is needed: a free-agent starter's quality does not depend on how much
-- he has pitched (ERA 4.87 to 4.93 whether 3, 5 or 10 earlier starts are asked for, under
-- the rule of ADR 0029; 4.89 and 4.89 in the two halves of the season), only the length
-- of his outing does, which the role filter takes care of. For relievers and hitters the
-- unranked pool is not the players doing the job (long men and call-ups at 3.58 outs; bench
-- players with one at-bat), so their pools stay ranked.
--
-- BIAS. Two, pulling opposite ways, in the batting and relief pools.
--   * The pool is players nobody rostered that date; a free agent who got added leaves
--     it. Replacement is therefore the never-owned remainder, probably lower than what a
--     manager could actually have had on the wire. (This is what ADR 0029 removed for
--     starts, where it was half a run of ERA.)
--   * Ranking by appearances picks the pitchers MLB teams used most, and teams use good
--     relievers most. The relief pool's ERA (3.49) is about what rostered relievers post
--     in relief while started (3.37), so a reliever earns little on ERA or WHIP here and
--     nearly all his value on saves, holds and strikeouts. Accepted in ADR 0009, which
--     also measures the alternatives: ranking by outs picks long men (4.20 outs an
--     appearance against a rostered reliever's 3.01), and pooling every free-agent relief
--     appearance gives a weaker ERA floor (4.24) but a longer outing still (3.58 outs).
--
-- SENSITIVITY. Measured on the 2026 season (12 teams) at N/2, N and 2N -- pool sizes of
-- 6, 12 and 24:
--   batting  AVG   .2410 / .2416 / .2420
-- The start pool has no N: 14.78 outs, ERA 4.89, WHIP 1.404.
--   relief   outs   2.68 /  2.80 /  2.83   ERA 3.18 / 3.49 / 3.58   WHIP 1.31 / 1.26 / 1.28
-- Started players, for scale: .254; 16.39 outs and ERA 3.89 in a start; 3.01 outs and ERA
-- 3.37 in relief. The size of a relief outing, which decides innings and strikeouts,
-- barely moves with the pool size. Relief ERA does (0.40 of a run across the
-- range, better the smaller the pool), which is the second bias above showing itself.
--
-- The sensitivity figures above are the 2026 league's; each league-season has its own.

{{ config(materialized='table') }}

with league_seasons as (

    select
        platform,
        league_id,
        season,
        count(*) as team_count
    from {{ ref('int_fantasy__teams') }}
    group by platform, league_id, season

),

scoring_dates as (

    select distinct
        platform,
        league_id,
        season,
        scoring_date
    from {{ ref('int_fantasy__roster_days') }}

),

rostered_days as (

    select distinct
        platform,
        league_id,
        season,
        mlbam_player_id,
        scoring_date
    from {{ ref('int_fantasy__roster_days') }}
    where mlbam_player_id is not null

),

-- days.* carries the MLB season; joining on it makes the league-season's season the MLB
-- season of every free-agent day (R4.6), so `season` here is both.
free_agent_days as (

    select
        scoring_dates.platform,
        scoring_dates.league_id,
        days.*
    from {{ ref('int_mlb__player_game_days') }} as days
    inner join scoring_dates
        on scoring_dates.scoring_date = days.game_date
        and scoring_dates.season = days.season
    left join rostered_days
        on rostered_days.platform = scoring_dates.platform
        and rostered_days.league_id = scoring_dates.league_id
        and rostered_days.season = scoring_dates.season
        and rostered_days.mlbam_player_id = days.mlbam_player_id
        and rostered_days.scoring_date = days.game_date
    where rostered_days.mlbam_player_id is null

),

player_totals as (

    select
        platform,
        league_id,
        season,
        mlbam_player_id,
        sum(plate_appearances) as plate_appearances,
        sum(batters_faced) as batters_faced,
        sum(outs_recorded) as outs_recorded,
        sum(games_pitched) as games_pitched,
        sum(games_started) as games_started
    from free_agent_days
    group by platform, league_id, season, mlbam_player_id

),

hitter_totals as (

    select
        platform,
        league_id,
        season,
        mlbam_player_id,
        plate_appearances
    from player_totals
    where {{ fo_replacement_group(
        'plate_appearances', 'batters_faced', 'outs_recorded', 'games_pitched', 'games_started'
    ) }} = 'hitter'

),

batting_pool as (

    select
        hitter_totals.platform,
        hitter_totals.league_id,
        hitter_totals.season,
        hitter_totals.mlbam_player_id,
        'batting' as day_kind
    from hitter_totals
    inner join league_seasons
        on league_seasons.platform = hitter_totals.platform
        and league_seasons.league_id = hitter_totals.league_id
        and league_seasons.season = hitter_totals.season
    qualify row_number() over (
        partition by hitter_totals.platform, hitter_totals.league_id, hitter_totals.season
        order by hitter_totals.plate_appearances desc, hitter_totals.mlbam_player_id asc
    ) <= league_seasons.team_count

),

pitching_days as (

    select
        platform,
        league_id,
        season,
        mlbam_player_id,
        {{ fo_pitching_day_kind('games_pitched', 'games_started') }} as day_kind,
        outs_recorded
    from free_agent_days

),

pitching_candidates as (

    select
        platform,
        league_id,
        season,
        mlbam_player_id,
        day_kind,
        count(*) as kind_days,
        sum(coalesce(outs_recorded, 0)) as kind_outs
    from pitching_days
    -- Only the relief pool is ranked; see start_pool_days.
    where day_kind = 'relief'
    group by platform, league_id, season, mlbam_player_id, day_kind

),

pitching_pool as (

    select
        pitching_candidates.platform,
        pitching_candidates.league_id,
        pitching_candidates.season,
        pitching_candidates.mlbam_player_id,
        pitching_candidates.day_kind
    from pitching_candidates
    inner join league_seasons
        on league_seasons.platform = pitching_candidates.platform
        and league_seasons.league_id = pitching_candidates.league_id
        and league_seasons.season = pitching_candidates.season
    qualify row_number() over (
        partition by
            pitching_candidates.platform,
            pitching_candidates.league_id,
            pitching_candidates.season,
            pitching_candidates.day_kind
        order by
            pitching_candidates.kind_days desc,
            pitching_candidates.kind_outs desc,
            pitching_candidates.mlbam_player_id asc
    ) <= league_seasons.team_count

),

pool as (

    select * from batting_pool
    union all
    select * from pitching_pool

),

-- What each pitcher had been before each of his days: fo_replacement_group over his MLB
-- days of the same season strictly before it. From all his days, not only the free-agent
-- ones: what a pitcher has been doing is the same whoever rosters him. His first day of a
-- season has no totals, and the macro then says hitter.
roles_to_date as (

    select
        mlbam_player_id,
        season,
        game_date,
        {{ fo_replacement_group(
            'sum(plate_appearances) over prior_days',
            'sum(batters_faced) over prior_days',
            'sum(outs_recorded) over prior_days',
            'sum(games_pitched) over prior_days',
            'sum(games_started) over prior_days'
        ) }} as role_to_date
    from {{ ref('int_mlb__player_game_days') }}
    window prior_days as (
        partition by mlbam_player_id, season
        order by game_date
        rows between unbounded preceding and 1 preceding
    )

),

-- What each pitcher had done on his pitching days before each of his days, this season:
-- how many there were, and whether the latest two were starts (null when there is no such
-- day). Over pitching days only, so a day he only batted is not an appearance and does not
-- break "his last two". A doubleheader day with a start and a relief outing is one
-- pitching day, a start, as fo_pitching_day_kind says everywhere else.
pitching_days_to_date as (

    select
        mlbam_player_id,
        season,
        game_date,
        row_number() over pitching_order - 1 as earlier_pitching_days,
        lag({{ fo_pitching_day_kind('games_pitched', 'games_started') }} = 'start', 1)
            over pitching_order as last_was_start,
        lag({{ fo_pitching_day_kind('games_pitched', 'games_started') }} = 'start', 2)
            over pitching_order as one_before_was_start
    from {{ ref('int_mlb__player_game_days') }}
    where games_pitched > 0
    window pitching_order as (
        partition by mlbam_player_id, season
        order by game_date
    )

),

-- The start pool is days, not players (ADR 0029): every free-agent start by a pitcher who
-- was a starter up to then, as fo_is_starter_at_the_time says (ADR 0031). Not ranked and
-- not cut to N. A day he did not pitch has no row in pitching_days_to_date, but a start
-- is a pitching day, so the join finds one for every start.
start_pool_days as (

    select
        'start' as day_kind,
        free_agent_days.*
    from free_agent_days
    inner join roles_to_date
        on roles_to_date.mlbam_player_id = free_agent_days.mlbam_player_id
        and roles_to_date.season = free_agent_days.season
        and roles_to_date.game_date = free_agent_days.game_date
    inner join pitching_days_to_date
        on pitching_days_to_date.mlbam_player_id = free_agent_days.mlbam_player_id
        and pitching_days_to_date.season = free_agent_days.season
        and pitching_days_to_date.game_date = free_agent_days.game_date
    where
        {{ fo_pitching_day_kind(
            'free_agent_days.games_pitched',
            'free_agent_days.games_started'
        ) }} = 'start'
        and {{ fo_is_starter_at_the_time(
            'pitching_days_to_date.earlier_pitching_days',
            'roles_to_date.role_to_date',
            'pitching_days_to_date.last_was_start',
            'pitching_days_to_date.one_before_was_start'
        ) }}

),

-- Only the side and kind each pool is credited for: a day is played on that side, in
-- that kind, or not at all.
pool_played_days as (

    select
        pool.day_kind,
        free_agent_days.*
    from free_agent_days
    inner join pool
        on pool.platform = free_agent_days.platform
        and pool.league_id = free_agent_days.league_id
        and pool.season = free_agent_days.season
        and pool.mlbam_player_id = free_agent_days.mlbam_player_id
    where
        case pool.day_kind
            when 'batting' then free_agent_days.games_batted > 0
            else {{ fo_pitching_day_kind(
                'free_agent_days.games_pitched',
                'free_agent_days.games_started'
            ) }} = pool.day_kind
        end

    union all

    select * from start_pool_days

),

kind_components as (

    {%- for column in fo_batting_columns() %}
    select 'batting' as day_kind, '{{ column }}' as component
    union all
    {%- endfor %}
    {%- for column in fo_pitching_columns() %}
    select 'start' as day_kind, '{{ column }}' as component
    union all
    select 'relief' as day_kind, '{{ column }}' as component
    {{- '\n    union all' if not loop.last }}
    {%- endfor %}

),

spine as (

    select
        league_seasons.platform,
        league_seasons.league_id,
        league_seasons.season,
        kinds.day_kind,
        kinds.component
    from league_seasons
    cross join kind_components as kinds

),

pool_sizes as (

    select
        platform,
        league_id,
        season,
        day_kind,
        count(*) as pool_players
    from pool
    group by platform, league_id, season, day_kind

    union all

    -- The start pool has no members, only days: its size is the pitchers who have one.
    select
        platform,
        league_id,
        season,
        day_kind,
        count(distinct mlbam_player_id) as pool_players
    from start_pool_days
    group by platform, league_id, season, day_kind

),

played_day_counts as (

    select
        platform,
        league_id,
        season,
        day_kind,
        count(*) as pool_played_days
    from pool_played_days
    group by platform, league_id, season, day_kind

),

-- One query per component rather than a pivot: the component lists are macros, and the
-- model names no column of its own.
pool_totals as (

    {%- for column in fo_batting_columns() %}
    select
        platform,
        league_id,
        season,
        day_kind,
        '{{ column }}' as component,
        sum(coalesce({{ column }}, 0)) as pool_total
    from pool_played_days
    where day_kind = 'batting'
    group by platform, league_id, season, day_kind
    union all
    {%- endfor %}
    {%- for column in fo_pitching_columns() %}
    select
        platform,
        league_id,
        season,
        day_kind,
        '{{ column }}' as component,
        sum(coalesce({{ column }}, 0)) as pool_total
    from pool_played_days
    where day_kind in ('start', 'relief')
    group by platform, league_id, season, day_kind
    {{- '\n    union all' if not loop.last }}
    {%- endfor %}

)

select
    spine.platform,
    spine.league_id,
    spine.season,
    spine.day_kind,
    spine.component,
    coalesce(pool_sizes.pool_players, 0) as pool_players,
    coalesce(played_day_counts.pool_played_days, 0) as pool_played_days,
    pool_totals.pool_total,
    pool_totals.pool_total / nullif(played_day_counts.pool_played_days, 0) as level_per_played_day
from spine
left join pool_sizes
    on pool_sizes.platform = spine.platform
    and pool_sizes.league_id = spine.league_id
    and pool_sizes.season = spine.season
    and pool_sizes.day_kind = spine.day_kind
left join played_day_counts
    on played_day_counts.platform = spine.platform
    and played_day_counts.league_id = spine.league_id
    and played_day_counts.season = spine.season
    and played_day_counts.day_kind = spine.day_kind
left join pool_totals
    on pool_totals.platform = spine.platform
    and pool_totals.league_id = spine.league_id
    and pool_totals.season = spine.season
    and pool_totals.day_kind = spine.day_kind
    and pool_totals.component = spine.component
