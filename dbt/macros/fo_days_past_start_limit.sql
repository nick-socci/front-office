{#
  Whether each team-day is past its matchup period's start limit (ADR 0071).

  The rule: a start is not credited when the team's earlier credited starts in the
  period reach the period's limit. The day that reaches the limit finishes (every start of
  that day is credited, however far it takes the team past); only the days after it are
  cut. So a day is past the limit when the starts of the team's EARLIER days in the same
  period already add up to the limit or more.

  Renders a SELECT over the CTE named by `team_day_starts`, which the caller defines with
  one row per team-day: platform, league_id, season, fantasy_team_id, scoring_date and
  day_starts (the games started that day in pitcher slots), plus any `extra_keys` (a
  lineup, say) that further separate the teams, unique on those keys together. It returns
  the keys and `is_past_start_limit`, never null:

    start_limit is not null and starts_before >= start_limit

  The comparison is exact: no rounding and no tolerance (ADR 0071; spec 0152 records
  how ESPN rounds a limit that is not a whole number as an open question). A league-season
  with no limit (start_limit null) is never past it. A date with no matchup period has no
  row here (the join to the periods is inner), so a caller left-joins this and treats the
  missing row as not past.

  day_starts may sum every start in a pitcher slot, credited or not, although only
  credited starts count toward the limit (R2.4): once a day is past the limit, every later
  day of the period is too, since the earlier total only grows, so adding the starts it
  left uncredited never changes the answer. A hitter-slot start is not counted by the
  caller.

  day_starts is an integer sum, exact in any order, so the window needs no ordering of its
  rows beyond the dates. Portable SQL (ADR 0051): the model using it is in the BigQuery
  slice.
#}
{% macro fo_days_past_start_limit(team_day_starts, extra_keys=[]) %}
    {%- set keys = ['platform', 'league_id', 'season', 'fantasy_team_id'] + extra_keys %}
    select
        {%- for key in keys %}
        team_days.{{ key }},
        {%- endfor %}
        team_days.scoring_date,
        coalesce(
            limits.start_limit is not null
            and coalesce(
                sum(team_days.day_starts) over (
                    partition by
                        {%- for key in keys %}
                        team_days.{{ key }},
                        {%- endfor %}
                        periods.matchup_period
                    order by team_days.scoring_date
                    rows between unbounded preceding and 1 preceding
                ),
                0
            ) >= limits.start_limit,
            false
        ) as is_past_start_limit
    from {{ team_day_starts }} as team_days
    inner join {{ ref('int_fantasy__matchup_periods') }} as periods
        on periods.platform = team_days.platform
        and periods.league_id = team_days.league_id
        and periods.season = team_days.season
        and periods.scoring_date = team_days.scoring_date
    left join {{ ref('int_fantasy__start_limits') }} as limits
        on limits.platform = periods.platform
        and limits.league_id = periods.league_id
        and limits.season = periods.season
        and limits.matchup_period = periods.matchup_period
{% endmacro %}
