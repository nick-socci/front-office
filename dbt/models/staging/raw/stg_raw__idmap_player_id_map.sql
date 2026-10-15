-- One row per committed capture of idmap/player_id_map that the loader has listed, with the whole
-- response as `payload` (spec 0150, ADR 0068).
--
-- The capture views are the only readers of payload files and of raw.captures. This
-- endpoint's responses are small, so its models read them as one JSON value each, as they
-- read the raw table before; only the three heavy endpoints are parsed with a declared
-- structure. A view, so the read happens inside each model's own query.

{{ fo_captures('idmap', 'player_id_map') }}
