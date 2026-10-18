-- One row per (scoring period, matchup period): which matchup period ESPN marked in the
-- response it gave for that scoring period.
--
-- A past season's matchups carry no `pointsByScoringPeriod` (the mapping that
-- stg_espn__matchup_periods reads), so its days cannot be assigned to matchups from the
-- matchups capture. ADR 0055 found another signal: asked for one scoring period with
-- views mMatchupScore and mScoreboard, ESPN puts `rosterForCurrentScoringPeriod` on the
-- sides of the matchups of exactly one matchup period, the one that day belongs to, and
-- on no others. One request per scoring period (`backfill espn --only matchup-days`)
-- therefore maps every day.
--
-- Only the EXISTENCE of that key is read. The roster inside it is never selected: these
-- responses also hold `teams` and `settings`, which carry member data. A side is a
-- declared structure (spec 0147) and the key is its member `rosterForCurrentScoringPeriod`:
-- a side has the day when that member is not null, as a side had it when the key was there.
-- (A side is a struct of nulls, not an absent object, so asking the side itself whether
-- the key exists would now always say yes.)
--
-- The scoring period comes from the request (`scoringPeriodId`), not from the payload:
-- the marker only means something relative to the day that was asked for, and a test
-- checks that ESPN answered that day.
--
-- Rule 1: the roster inside a side is never a value of this query. The capture view
-- (stg_raw__espn_matchup_days, spec 0150) keeps each matchup's period id and its two
-- sides as declared structures, whose marker member is asked only whether it is there;
-- the unnest runs beside the small identifier columns only, one constant-path branch per
-- side, as in stg_espn__matchup_periods. A playoff bye has an empty `away`, whose marker
-- member is null.
-- `select distinct` gives one row however many sides and matchups carry the marker.
--
-- A plain table: it reads every capture at once, as the view streams them (spec 0150).
--
-- In CI there are no matchup_days captures, so this model is empty there; its logic is
-- covered by unit tests.

{{ config(materialized='table') }}

with latest as (

    {{ fo_espn_latest('matchup_days', extra_partition='scoringPeriodId') }}

),

header as (

    select
        id as league_id,
        seasonId as season,
        {{ fo_request_param('request_key', 'scoringPeriodId') }} as scoring_period,
        fetched_at,
        schedule
    from latest

),

matchups as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        matchup
    from header
    {{ fo_unnest('header.schedule', 'matchup') }}

),

marked as (

    -- A matchup marks the scoring period if either side carries the roster for it. One pass
    -- over the matchups, not one branch per side: two branches read the matchups twice,
    -- and DuckDB then held every matchup of every season, both rosters included (spec
    -- 0150, Amendments). The `distinct` below keeps one row however many matchups mark it.
    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        matchup.matchupPeriodId as matchup_period
    from matchups
    where
        matchup.home.rosterForCurrentScoringPeriod is not null
        or matchup.away.rosterForCurrentScoringPeriod is not null

)

select distinct
    league_id,
    season,
    scoring_period,
    matchup_period,
    {{ fo_parse_fetched_at() }} as fetched_at
from marked
