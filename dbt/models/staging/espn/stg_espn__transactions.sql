-- One row per player movement: an add, drop, waiver claim or trade.
--
-- ESPN nests these as topics (one per transaction event) containing messages (one per
-- player moved), so a trade of two players is one topic with two messages. The message
-- is the grain here, because that is what moves a player.
--
-- The payload also identifies the ESPN MEMBER behind each move via an account GUID
-- (topic.author / message.author). Those fields are never selected: they identify a
-- real person, and this repo is public.

with latest as (

    {{ fo_espn_latest('transactions') }}

),

header as (

    select
        fetched_at,
        {{ fo_json_array('payload', '$.topics[*]') }} as topics
    from latest

),

topics as (

    select
        fetched_at,
        unnest(topics) as topic
    from header

),

messages as (

    select
        fetched_at,
        {{ fo_json_text('topic', '$.id') }} as topic_id,
        {{ fo_json_int('topic', '$.date') }} as topic_date_ms,
        unnest({{ fo_json_array('topic', '$.messages[*]') }}) as message
    from topics

)

select
    topic_id,
    {{ fo_json_text('message', '$.id') }} as transaction_id,
    to_timestamp({{ fo_json_int('message', '$.date') }} / 1000) as transacted_at,
    {{ fo_eastern_date("to_timestamp(try_cast(message ->> '$.date' as bigint) / 1000)::timestamp") }}
        as transaction_date,
    {{ fo_json_int('message', '$.messageTypeId') }} as message_type_id,
    activities.activity,
    {{ fo_json_int('message', '$.targetId') }} as espn_player_id,
    {{ fo_json_int('message', '$.to') }} as to_team_id,
    {{ fo_json_int('message', '$.from') }} as from_team_id,
    {{ fo_parse_fetched_at() }} as fetched_at
from messages
left join {{ ref('espn_activity_types') }} as activities
    on activities.message_type_id = {{ fo_json_int('message', '$.messageTypeId') }}
{{ fo_latest_by_entity(["message ->> '$.id'"]) }}
