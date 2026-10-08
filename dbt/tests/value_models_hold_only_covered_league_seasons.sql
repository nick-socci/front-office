-- No model that computes a value from rosters holds a row for a league-season with no
-- rosters. Returns each (model, league-season) that does.
--
-- A past season can be loaded for its matchup totals alone (ADR 0026). The matchup models
-- are spined on matchups and categories, which such a season has, so without the
-- restriction in int_fantasy__matchup_side_totals they build a row per side with nothing
-- in it: a zero that reads as "this team produced nothing". Catches that restriction
-- being removed, and a later value model spined on something an uncovered season has
-- (spec 0085, R2.2 and R4.3).
--
-- Anti-joined to the covered league-seasons, so a league-season missing from
-- int_fantasy__league_seasons altogether is returned too.

{%- set value_models = [
    'int_fantasy__matchup_side_totals',
    'int_fantasy__matchup_stat_values',
    'int_fantasy__category_scales',
    'int_fantasy__replacement_levels',
    'fct_matchup_category_scores',
    'fct_matchup_results',
    'fct_player_category_value',
    'fct_player_season_value',
    'fct_transaction_impact',
] %}

with held as (

    {%- for model in value_models %}
    select distinct '{{ model }}' as model, platform, league_id, season
    from {{ ref(model) }}
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

covered as (

    select platform, league_id, season
    from {{ ref('int_fantasy__league_seasons') }}
    where has_rosters

)

select held.model, held.platform, held.league_id, held.season
from held
left join covered
    on covered.platform = held.platform
    and covered.league_id = held.league_id
    and covered.season = held.season
where covered.league_id is null
