-- One row per player movement: an add, drop, waiver claim or trade.
--
-- ESPN nests these as topics (one per transaction event) containing messages (one per
-- player moved), so a trade of two players is one topic with two messages. The message
-- is the grain here, because that is what moves a player.
--
-- message_to, message_from and message_for are ESPN's `to`, `from` and `for` fields, kept
-- as sent. They are not all team ids: which one names the acting team depends on the
-- message type, and for type 239 `from` is a lineup slot id. Staging does not choose;
-- int_fantasy__transactions applies the rule (ADR 0004).
--
-- The payload also identifies the ESPN MEMBER behind each move via an account GUID
-- (topic.author / message.author). Those fields are never selected: they identify a
-- real person, and this repo is public.

-- league_id and season come from the capture's `partitions`: the communication payload
-- names neither. They are the first two columns, and a transaction is identified by
-- (league_id, season, transaction_id), because message ids are only unique inside one
-- league.
--
-- The log is landed as pages sharing one fetched_at (#26), so "latest" is every page of
-- the newest run, not the single newest response -- and the newest run of EACH league and
-- season, so one league fetched later cannot hide another's log. A topic can repeat
-- across pages when activity lands between two page requests; the dedupe on
-- (league, season, message id) below absorbs it.
with responses as (

    select
        payload,
        request_key,
        fetched_at,
        {{ fo_json_text('partitions', '$.league_id') }} as league_id,
        {{ fo_json_int('partitions', '$.season') }}::integer as season
    from {{ source('raw', 'api_responses') }}
    where source = 'espn'
      and endpoint = 'transactions'

),

newest_run as (

    select
        league_id,
        season,
        max(fetched_at) as fetched_at
    from responses
    group by league_id, season

),

latest as (

    select
        responses.payload,
        responses.request_key,
        responses.fetched_at,
        responses.league_id,
        responses.season
    from responses
    inner join newest_run
        on newest_run.league_id = responses.league_id
        and newest_run.season = responses.season
        and newest_run.fetched_at = responses.fetched_at

),

header as (

    select
        league_id,
        season,
        fetched_at,
        request_key,
        {{ fo_json_array('payload', '$.topics[*]') }} as topics
    from latest

),

topics as (

    select
        league_id,
        season,
        fetched_at,
        request_key,
        unnest(topics) as topic
    from header

),

messages as (

    select
        league_id,
        season,
        fetched_at,
        request_key,
        {{ fo_json_text('topic', '$.id') }} as topic_id,
        {{ fo_json_int('topic', '$.date') }} as topic_date_ms,
        unnest({{ fo_json_array('topic', '$.messages[*]') }}) as message
    from topics

)

select
    league_id,
    season,
    topic_id,
    {{ fo_json_text('message', '$.id') }} as transaction_id,
    to_timestamp({{ fo_json_int('message', '$.date') }} / 1000) as transacted_at,
    {{ fo_eastern_date('to_timestamp(' ~ fo_json_int('message', '$.date') | trim ~ ' / 1000)::timestamp') }}
        as transaction_date,
    {{ fo_json_int('message', '$.messageTypeId') }} as message_type_id,
    activities.activity,
    {{ fo_json_int('message', '$.targetId') }} as espn_player_id,
    {{ fo_json_int('message', '$.to') }} as message_to,
    {{ fo_json_int('message', '$.from') }} as message_from,
    {{ fo_json_int('message', '$.for') }} as message_for,
    {{ fo_parse_fetched_at() }} as fetched_at
from messages
left join {{ ref('espn_activity_types') }} as activities
    on activities.message_type_id = {{ fo_json_int('message', '$.messageTypeId') }}
-- `is distinct from`, so an unknown type (null) is kept and fails the activity test.
where activities.is_transaction is distinct from false
-- Every page of a run shares one fetched_at, so recency cannot choose between two copies
-- of a message that straddles a page boundary: the page (request_key) and topic do.
{{ fo_latest_by_entity(
    ['league_id', 'season', fo_json_string('message', '$.id') | trim],
    order_by='fetched_at desc, request_key, topic_id'
) }}
