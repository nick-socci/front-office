# The member-data endpoints on BigQuery: teams, transactions and MLB's player list — requirements

Issue: #136 · Tier: M · Status: draft

## Problem

The spike's upload (`scripts/spike_load_bigquery.py`, ADRs 0054 and 0061) sends nine
endpoints to BigQuery. It does not send `espn/teams`, `mlb/players` or the parts of
`espn/transactions` that a model reads: the first two carry member data, and the third
was outside the slice. So 19 models cannot build on BigQuery whatever #135 ports
(design C1). They include `dim_players` and every lineup-decision and player-value mart.
#135 is blocked on this decision for those models.

## Goals

- The three endpoints go up in a form the owner chose, and nothing that names a league
  member or an ESPN account goes with them.
- The upload stays checked by the patterns of `front_office/privacy.py`, with exceptions
  that name an endpoint and a place, never a whole source.
- It is shown, before #135 ports anything, that what goes up holds every field the staging
  models read.

## No-gos

- Porting `stg_espn__teams`, `stg_espn__transactions`, `stg_mlb__players` or any model to
  the two-warehouse rule, or adding a model to `bigquery_slice`. That is #135.
- The production loader: buckets, append-only tables, scheduling (#140).
- Changing `front_office/privacy.py`, the pre-commit guard, or the fixture privacy test.
  The upload's exceptions live in the upload.
- Changing what any model returns, or any fixture.
- Uploading any endpoint other than these three beyond the nine already uploaded.

## Rabbit holes

- Telling an account GUID from a transaction id by its written form → not done. The ids are
  checked against the known accounts instead (ADR 0094).
- Proving the projection on BigQuery, which needs the models ported → proved on DuckDB:
  the staging models built from the projected captures equal those built from the real
  ones (R4). BigQuery gets row counts only (R5.3).
- Keeping a third list of wanted fields → the upload imports the fixtures' lists
  (ADR 0093).

## Requirements

### R1. What goes up

The three endpoints join the upload in the form ADRs 0093 and 0095 choose.

- R1.1 THE SYSTEM SHALL read for upload `espn/teams` and `espn/transactions` as projections
  and `mlb/players` whole, beside the nine endpoints of ADRs 0054 and 0061, and no other
  endpoint.
- R1.2 WHEN a capture of `espn/teams` is read for upload THE SYSTEM SHALL build its payload
  from `id`, `seasonId`, and for each team only the fields of `ESPN_TEAM_FIELDS`.
- R1.3 WHEN a capture of `espn/transactions` is read for upload THE SYSTEM SHALL build its
  payload as `topics[]`, each topic only its `id`, its `date` and its `messages[]`, each
  message only its `id` and the fields of `ESPN_TRANSACTION_MESSAGE_FIELDS`.
- R1.4 THE SYSTEM SHALL take the field lists of R1.2 and R1.3 from `scripts/make_fixtures.py`
  by import, so that one list per endpoint serves the fixtures and the upload.
- R1.5 IF a value at a path of R1.2 or R1.3 is an object or an array THEN THE SYSTEM SHALL
  leave it out. Every field on those lists is a single value, so anything nested under one
  is not a field the model reads (`matchup_days`' projection guards its ids the same way).
- R1.6 THE SYSTEM SHALL keep the projection of `espn/matchup_days` unchanged.

### R2. The check

ADR 0054's check still runs on every row, as sent. Its exceptions are as narrow as
ADRs 0094 and 0095 allow.

- R2.1 IF any row holds a key of `privacy.FORBIDDEN_KEYS` THEN THE SYSTEM SHALL stop the
  upload, except `firstName` and `lastName` directly in an `espn` `playerPoolEntry.player`
  object (as now) or directly in an object of `$.people[]` of an `mlb/players` row.
- R2.2 IF a GUID-shaped string is anywhere in an `espn` row THEN THE SYSTEM SHALL stop the
  upload, except a value at `$.topics[i].id` or `$.topics[i].messages[j].id` of the payload
  of an `espn/transactions` row.
- R2.3 IF a value at one of R2.2's two paths equals, ignoring braces and case, a GUID-shaped
  value found in any committed capture of `espn/teams` (`members[].id`, `teams[].owners[]`,
  `teams[].primaryOwner`) or `espn/transactions` (`topics[].author`,
  `topics[].messages[].author`) THEN THE SYSTEM SHALL stop the upload.
- R2.4 IF `espn/transactions` rows are to be uploaded and no account id was found for R2.3
  THEN THE SYSTEM SHALL stop the upload.
- R2.5 IF a row of `espn/teams` or `espn/transactions` is not exactly what its projection
  would produce THEN THE SYSTEM SHALL stop the upload, as it does for the two endpoints of
  ADR 0061.
- R2.6 WHEN the check stops the upload THE SYSTEM SHALL name the endpoint, the request and
  the path of each hit, never the value, and write nothing (spec 0130, R3.3).
- R2.7 THE SYSTEM SHALL take the manifest's captures once per run. The known accounts, the
  check, the export and the landing root of R4.1 SHALL all be drawn from that one set, so a
  capture loaded while the upload runs is neither written unchecked nor missing from the
  accounts.

### R3. The check's tests fail on what they guard

- R3.1 THE SYSTEM SHALL have a test for each of R2.1 to R2.5 that plants the case it guards
  in a row and shows the upload stopped: a member key in an `mlb/players` row outside
  `people[]`, a GUID at a third path of a transaction row, a GUID at an exempt path of
  another endpoint, an exempt id that equals a known account with different braces and case,
  an empty account set, and a whole teams capture.

### R4. The projections hold what staging reads

Shown on DuckDB, before any model is ported.

- R4.1 THE SYSTEM SHALL be able to write the checked rows of the three projected endpoints
  (`teams`, `transactions`, `matchup_days`), as they would be uploaded, to a separate landing
  root through `LandingZone.write`, each with its original partitions, request, capture name
  and `fetched_at`. It SHALL write nothing there if the check stops the upload.
- R4.3 IF the root of R4.1 is not ignored by git (`git check-ignore`) THEN THE SYSTEM SHALL
  refuse it and write nothing.
- R4.2 WHEN `stg_espn__teams`, `stg_espn__transactions`, `stg_espn__transaction_logs`,
  `stg_espn__matchup_days` and `stg_espn__matchup_player_lines` are built from that root
  THE SYSTEM SHALL give relations equal, row for row and column for column, to the same
  models built from the real landing zone. (Those five read only their capture views and
  the `espn_activity_types` seed, design C13.)

### R5. The upload on BigQuery

Run on the real season, with the owner's go-ahead (credentials and billing).

- R5.1 WHEN the loader runs with `--dry-run` on the real season THE SYSTEM SHALL report no
  privacy hit, and row counts per endpoint as in *Expected values*.
- R5.2 WHEN the loader runs THE SYSTEM SHALL load every row, and the read-back of every row
  of all eleven endpoints SHALL be paired and equal (spec 0130, R3.4).
- R5.3 WHEN `stg_raw__espn_teams`, `stg_raw__espn_transactions` and `stg_raw__mlb_players`
  are built with `--target bq` THE SYSTEM SHALL hold as many rows as the same views on
  DuckDB.

### R6. Records

- R6.1 THE SYSTEM SHALL describe the eleven endpoints, the two exceptions and the
  cross-check in the loader's docstring.
- R6.2 THE SYSTEM SHALL state ADR 0061's amendment of 0054 on an `- Amends:` line in 0061's
  header, as the owner asked on #136 (2026-10-16). Once this spec is approved, it SHALL set
  0054's and 0061's `Status` to link the records that amend them.
- R6.3 THE SYSTEM SHALL ignore `/data/` in the tracked `.gitignore`. AGENTS.md says `data/`
  is local only and gitignored, but the tracked file ignores only parts of it: the
  upload's `data/bigquery_export/` and R4.1's root would be untracked files in a fresh
  clone (design review F1).

## Expected values

On the real landing zone and the manifest of `data/warehouse_main_ac0e2ac.duckdb`
(design C2 to C12).

| Check | Expected | How to verify |
|---|---|---|
| Rows read for upload, new endpoints | `espn/teams` 13, `espn/transactions` 7, `mlb/players` 9 | `--dry-run` output (R5.1) |
| Rows read for upload, existing endpoints | unchanged from a dry run of `main` on the same day | `--dry-run` on both branches |
| Privacy hits | 0 | `--dry-run` (R5.1) |
| Account ids found for the cross-check | 17 distinct | a count printed by the dry run |
| GUIDs allowed at the exempt paths | 34,882 (9,779 topic ids, 25,103 message ids), none equal to an account id | a count printed by the dry run |
| Projected sizes | teams ≈ 0.03 MB in all, transactions ≈ 4.2 MB, against 0.52 and 17.05 MB whole | export file sizes |
| Staging from projected captures | the 5 relations of R4.2 equal | `scripts/compare_warehouses.py --strict-columns --exclude staging.stg_raw__espn_matchup_days`, exit 0 (design, amendment of 2026-10-23) |
| Read-back | every row of 11 endpoints paired and equal | the loader's exit 0 (R5.2) |
| BigQuery capture views | `stg_raw__espn_teams` 13, `stg_raw__espn_transactions` 7, `stg_raw__mlb_players` 9 | `count(*)` on each warehouse (R5.3) |
