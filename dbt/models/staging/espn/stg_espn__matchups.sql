-- One row per (matchup period, matchup): who played whom and who won.
--
-- Category results live in stg_espn__matchup_category_results; this model carries the
-- head-to-head outcome and the category win/loss/tie tally behind it.

with latest as (

    {{ fo_espn_latest('matchups') }}

),

header as (

    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        fetched_at,
        {{ fo_json_array('payload', '$.schedule[*]') }} as schedule
    from latest

),

matchups as (

    select
        league_id,
        season,
        fetched_at,
        unnest(schedule) as matchup
    from header

)

select
    league_id,
    season,
    {{ fo_json_int('matchup', '$.id') }} as matchup_id,
    {{ fo_json_int('matchup', '$.matchupPeriodId') }} as matchup_period,
    {{ fo_json_int('matchup', '$.home.teamId') }} as home_team_id,
    {{ fo_json_int('matchup', '$.away.teamId') }} as away_team_id,
    {{ fo_json_text('matchup', '$.winner') }} as winner,
    {{ fo_json_text('matchup', '$.playoffTierType') }} as playoff_tier,
    {{ fo_json_int('matchup', '$.home.cumulativeScore.wins') }} as home_category_wins,
    {{ fo_json_int('matchup', '$.home.cumulativeScore.losses') }} as home_category_losses,
    {{ fo_json_int('matchup', '$.home.cumulativeScore.ties') }} as home_category_ties,
    {{ fo_parse_fetched_at() }} as fetched_at
from matchups
-- Two of the 145 schedule entries are playoff BYES: the away side is an empty object and
-- the home team advances without playing. They are dropped because this model's grain is
-- "who played whom", and a bye has no opponent and no category results. The team's
-- advancement is still visible in the bracket via playoff_tier on its next matchup.
where {{ fo_json_int('matchup', '$.away.teamId') }} is not null
{{ fo_latest_by_entity(['league_id', 'season', "matchup ->> '$.id'"]) }}
