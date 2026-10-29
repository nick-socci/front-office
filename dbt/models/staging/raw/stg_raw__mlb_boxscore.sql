-- One row per committed boxscore capture (one game) that the loader has listed, parsed as
-- it is read (spec 0150, ADRs 0066 and 0068).
--
-- A boxscore is up to 0.3 MB, and there are 24,385 of them for eight seasons. Most of it,
-- a player's season stats and fielding, is dropped while reading: kept as one JSON value
-- per player, the batting model needed 4 GB for eight seasons; the declared shape reads
-- them under 1 GB (spec 0150, Amendments).
--
-- The structure, and what each side and player keeps, is in the macro
-- fo_capture_structure (macros/capture_structures.sql, spec 0138, ADR 0111).

{{ fo_captures('mlb', 'boxscore', fo_capture_structure('mlb', 'boxscore')) }}
