-- One row per (league, season) whose transaction log has been landed, and when.
--
-- ESPN serves the transaction log of the current season only (ADR 0056): a past season
-- covered for its rosters has no log to fetch. "No log landed" has to be told apart from
-- "a log landed with no transaction in it", and stg_espn__transactions cannot say so: it
-- has one row per transaction, so an empty log leaves nothing behind. This model has a row
-- for every league-season with at least one `transactions` response loaded, whatever the
-- responses hold. int_fantasy__league_seasons reads it as has_transaction_log.
--
-- Only identifiers are read: league_id and season from the capture's `partitions`, as in
-- stg_espn__transactions, and the capture time. The topics are never touched, so nothing
-- here can reach the member data they carry (topic.author / message.author), and there is
-- no unnest to drop a league-season whose log is empty.
--
-- fetched_at is the newest capture of the league-season. The pages of one run share it
-- (#26), so the maximum is the run's.
with responses as (

    select
        fetched_at,
        {{ fo_json_text('partitions', '$.league_id') }} as league_id,
        cast({{ fo_json_int('partitions', '$.season') }} as integer) as season
    from {{ ref('stg_raw__espn_transactions') }}

)

select
    league_id,
    season,
    {{ fo_parse_fetched_at('max(fetched_at)') }} as fetched_at
from responses
group by league_id, season
