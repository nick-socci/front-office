-- Every roster entry, and every eligible-slot row, names a team of ITS OWN league and
-- season.
--
-- This replaces two single-column `relationships` tests on team_id. Those compared the
-- value alone, so with two leagues loaded a roster entry for a team id that exists only
-- in another league would have passed (#28). Returns the offending rows.

with roster_teams as (

    select distinct
        league_id,
        season,
        team_id,
        'stg_espn__roster_entries' as model
    from {{ ref('stg_espn__roster_entries') }}

    union all

    select distinct
        league_id,
        season,
        team_id,
        'stg_espn__roster_entry_slots'
    from {{ ref('stg_espn__roster_entry_slots') }}

)

select
    roster_teams.model,
    roster_teams.league_id,
    roster_teams.season,
    roster_teams.team_id
from roster_teams
left join {{ ref('stg_espn__teams') }} as teams
    on teams.league_id = roster_teams.league_id
    and teams.season = roster_teams.season
    and teams.team_id = roster_teams.team_id
where teams.team_id is null
