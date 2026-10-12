-- A game whose boxscore captures are filed under more than one season.
--
-- The boxscore game logs keep each game's newest capture, and are built a season at a
-- time (spec 0143): each batch sees one season's captures and picks the newest among
-- those. That is the newest capture of the game only while all of a game's captures sit
-- under one season. Were a game recaptured under another, each batch would keep its own
-- copy: the unique key (game, player) would catch a player in both, and nothing would
-- catch a player a correction removed from the newer one.
--
-- Ingestion files a boxscore under the season of the schedule it was listed in, so this
-- holds by construction; the test is here so that it cannot stop holding quietly.
-- Rosters need no such test: fo_espn_latest already picks per league and partition season.
--
-- A capture with no season is not counted here (count distinct passes over a null); it is
-- in no batch, and stg__batched_models_hold_every_season_with_captures fails on it.
--
-- Reads the request key and season_start of the view only, never the payload.

select
    {{ fo_request_param('request_key', 'gamePk') }} as game_pk,
    count(distinct season_start) as seasons
from {{ ref('stg_raw__season_responses') }}
where
    source = 'mlb'
    and endpoint = 'boxscore'
group by 1
having count(distinct season_start) > 1
