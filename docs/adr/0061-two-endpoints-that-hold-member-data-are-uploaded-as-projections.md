# 0061. Two endpoints that hold member data are uploaded as projections of allowlisted fields

- Status: proposed
- Date: 2026-10-12
- Spec: [0083-past-season-rosters](../specs/0083-past-season-rosters/design.md) · Issue: #83

Amends [0054](0054-only-endpoints-without-member-data-are-uploaded-and-whole.md), which
stays in force for the seven endpoints it lists.

## Context

ADR 0054 uploads whole captures of seven endpoints that carry no member data, and leaves
`espn/teams` and `espn/transactions` on the owner's machine. Spec 0083 then made two
models of the BigQuery slice read captures that 0054 does not allow up:

- `int_fantasy__league_seasons` reads `stg_espn__transaction_logs` for
  `has_transaction_log` (ADR 0056). That model reads a `transactions` capture's
  `partitions` and `fetched_at` and never its payload, whose topics carry `author` and
  account ids.
- `int_fantasy__matchup_periods` reads `stg_espn__matchup_days` (ADR 0055). A
  `matchup_days` capture holds `teams` and `settings` beside the schedule (spec 0083,
  C11). The model and its two tests read five things from it: `id`, `seasonId`,
  `scoringPeriodId`, each matchup's `matchupPeriodId`, and whether each side has the key
  `rosterForCurrentScoringPeriod`.

With neither on BigQuery the slice no longer builds there, and six of its tests fail on
#83's branch.

## Decision drivers

- Nothing that names a member or an account leaves the machine (rule 2, ADR 0054).
- A model is written once and reads the same JSON paths on both warehouses (ADR 0051).
- What goes up is built from a list of wanted fields, never by removing unwanted ones:
  the rule fixtures already follow.
- The slice of spec 0130 keeps building on BigQuery.

## Considered options

1. **Upload these two endpoints as projections**: a payload rebuilt from an allowlist of
   fields, the other columns unchanged.
2. **Grow the slice and leave the upload alone**: the gates pass, and the slice cannot be
   built on BigQuery until a later issue.
3. **Take the models that need them out of the slice.** They are parents of two of its
   three roots, so the slice would lose its marts.
4. **Upload the two endpoints whole.** ADR 0054's option 2, for two endpoints.

## Decision

Chosen by the owner on 2026-10-12: **option 1**.

The upload has a second list beside ADR 0054's allowlist: endpoints uploaded as a
projection, each with the function that builds its payload.

| Endpoint | Payload uploaded |
|---|---|
| `espn/transactions` | `{}`: nothing. The key columns, `partitions` and `file_path` go up as they are |
| `espn/matchup_days` | `id`, `seasonId`, `scoringPeriodId`, and `schedule`: for each matchup its `matchupPeriodId`, and for each of `home` and `away` that has the key, `rosterForCurrentScoringPeriod` as an empty object |

The projection is made before the privacy check of ADR 0054, which then runs on what
would be sent, exactly as for the seven: a forbidden key or an account id anywhere in a
projected row, its request or its path stops the upload. The read-back that proves the
rows arrived whole compares against the projected rows.

Option 4 was not chosen for the reason 0054 gave. Option 3 undoes the spike. Option 2 is
quicker and leaves BigQuery broken for an unknown time.

## Consequences

- Good: the slice builds on BigQuery with the same SQL, and no member data goes up.
- Good: the marker's presence, the only thing read from a roster there, survives as an
  empty object; `fo_json_exists` gives the same answer on both warehouses.
- Bad / accepted cost: for these two endpoints the raw rows differ between the warehouses
  by design. A model that came to read another field of either would be right on DuckDB
  and empty on BigQuery. `stg_espn__transactions`, outside the slice, is such a model:
  it must stay outside until `transactions` is decided whole, which is 0054's follow-up
  and is not settled here.
- Bad / accepted cost: a second definition of wanted fields, for two payloads.
- Follow-ups: a field added to what `stg_espn__matchup_days` or its tests read is added
  to the projection in the same change; the comparison of the slice with DuckDB is what
  shows a field was missed.
