# 0093. Teams and transactions go up as projections of the fields their staging models read

- Status: proposed
- Date: 2026-10-22
- Spec: [0136-member-endpoints-to-bigquery](../specs/0136-member-endpoints-to-bigquery/design.md) · Issue: #136
- Amends: [0054](0054-only-endpoints-without-member-data-are-uploaded-and-whole.md), [0061](0061-two-endpoints-that-hold-member-data-are-uploaded-as-projections.md)

## Context

ADR 0054 uploads whole captures of seven endpoints that carry no member data. ADR 0061
adds two endpoints as projections: `matchup_days` as the fields its models read, and
`transactions` as `{}`, since `stg_espn__transaction_logs` reads only the capture's
partitions. Neither record uploads `espn/teams`, or anything of a transaction log that
`stg_espn__transactions` could read. So 18 models cannot build on BigQuery: the two
staging models and the 16 downstream of them, among them every lineup-decision and
player-value mart (spec 0136, C1).

The member data in these two endpoints sits in fields no model reads (spec 0136, C2 to C5):

| Endpoint | Captures | Whole | Member data | Read by staging |
|---|---|---|---|---|
| `espn/teams` | 13 | 0.52 MB | `members[]` (names, `id`), `teams[].owners`, `teams[].primaryOwner` | `id`, `seasonId`, per team `id`, `name`, `abbrev`, `playoffSeed`, `eliminated`, `record.overall.{wins, losses, ties, streakLength, streakType}` |
| `espn/transactions` | 7 | 17.05 MB | `topics[].author`, `messages[].author` | per topic `id`, `date`; per message `id`, `date`, `messageTypeId`, `targetId`, `to`, `from`, `for` |

The fixtures are already rebuilt from these field lists (`ESPN_TEAM_FIELDS` and
`ESPN_TRANSACTION_MESSAGE_FIELDS` in `scripts/make_fixtures.py`). Projected the same way,
the two endpoints hold no forbidden key (C6). Team names are already on BigQuery:
`espn/matchups`, uploaded whole under 0054, carries `teams[].name` (C7).

## Decision drivers

- Members did not agree to their names or account ids being put anywhere (rule 2,
  ADR 0054).
- A model is written once and reads the same JSON on both warehouses (ADR 0051).
- What goes up is built from a list of wanted fields, never by removing unwanted ones.
- Each definition of "the fields a model reads" is a place the definitions can disagree,
  so there should be as few as possible.

## Considered options

1. **Projections of the fields staging reads.** Built with the fixtures' own field lists,
   imported rather than copied, and checked by the same privacy check as every other row.
2. **Upload both endpoints whole.** The project is private to the owner's account.
3. **Build the two staging models locally and upload their tables.** BigQuery then reads
   no raw capture of either endpoint.
4. **Leave both off BigQuery.** The 18 models that need them stay DuckDB-only.

## Decision

Chosen by the owner on 2026-10-22, at the spec's walkthrough: **option 1**.

`espn/teams` uploads `id`, `seasonId` and `teams[]`, each team rebuilt from
`ESPN_TEAM_FIELDS`. `espn/transactions` uploads `topics[]`, each topic its `id`, its `date`
and its `messages[]`, each message its `id` and `ESPN_TRANSACTION_MESSAGE_FIELDS`. This
replaces 0061's `{}` for transactions: `stg_espn__transaction_logs` still reads only the
partitions, and `stg_espn__transactions` now finds what it reads. The ids of a topic and of
a message are GUID-shaped; how the check treats them is ADR 0094. `matchup_days` is
unchanged.

Option 2 puts other people's names and account ids in a cloud project, which 0054 declined
to do by default and nothing since has asked for. Option 3 gives the two staging models a
second definition on BigQuery (a `source()` there, a capture view here), against ADR 0051,
and puts them outside the slice comparison for good. Option 4 keeps 18 models, most of
the marts among them, off BigQuery, which defeats the migration.

## Consequences

- Good: every endpoint a model reads can now go up, and nothing that names a member or an
  account does.
- Good: the fixtures and the upload share one list per endpoint. A field added to
  `stg_espn__teams` or `stg_espn__transactions` is added to that list for the fixture to
  carry it, and the upload follows.
- Bad / accepted cost: for these two endpoints the raw rows differ between warehouses by
  design, as 0061 accepted for its two. A field read without being added to the list is
  null on BigQuery. The fixtures would miss it too, so CI is no help, and only the slice
  comparison would show it. That comparison covers these two models once #135 ports them.
- Bad / accepted cost: the fixture script becomes a module the upload imports. Its field
  lists stop being the fixtures' private business.
- Follow-ups: #135 ports `stg_espn__teams`, `stg_espn__transactions` and their downstream
  models into the slice. #140's production loader takes over these projections.
