-- One row per committed matchup-days capture (one scoring period of one league-season)
-- that the loader has listed, parsed as it is read (spec 0150, ADRs 0066 and 0068).
--
-- A payload is up to 1.3 MB: the season's schedule, each matchup carrying both sides'
-- full rosters, and `teams` and `settings`, which carry member data. Parsed from the
-- file with a declared structure, everything not declared is dropped while reading.
--
-- The structure, and which reader takes which field, is in the macro
-- fo_capture_structure (macros/capture_structures.sql, spec 0138, ADR 0111).

{{ fo_captures('espn', 'matchup_days', fo_capture_structure('espn', 'matchup_days')) }}
