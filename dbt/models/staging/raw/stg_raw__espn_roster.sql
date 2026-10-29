-- One row per committed roster capture (one scoring period of one league-season) that the
-- loader has listed, parsed as it is read into the fields the roster models use (spec
-- 0150, ADRs 0066 and 0068).
--
-- A roster payload is up to 2.5 MB, nearly all of it every rostered player's season
-- stats. Parsed from the file with this structure, the rest of each document is dropped
-- while reading, and no megabyte value ever passes through a query: eight seasons of
-- game lines read in 3 s and 0.18 GB, where the same parse over a JSON column needed
-- 12 GB for one season (spec 0150, C6 and C19).
--
-- The structure, and which reader takes which field, is in the macro
-- fo_capture_structure (macros/capture_structures.sql, spec 0138, ADR 0111).

{{ fo_captures('espn', 'roster', fo_capture_structure('espn', 'roster')) }}
