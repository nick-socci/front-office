# 0094. A transaction's own ids go up, at their two paths, if none is a known account id

- Status: proposed
- Date: 2026-10-22
- Spec: [0136-member-endpoints-to-bigquery](../specs/0136-member-endpoints-to-bigquery/design.md) · Issue: #136
- Amends: [0054](0054-only-endpoints-without-member-data-are-uploaded-and-whole.md)

## Context

ADR 0054's check stops the upload on any GUID-shaped string in an ESPN row. An ESPN account
id is such a string, and so are the ids ESPN gives a transaction's topics and messages. In
the 7 transaction captures (spec 0136, C8 and C9):

- `topics[].id` (9,779 occurrences) and `messages[].id` (25,103) are GUID-shaped. Of the
  11,220 distinct ids, none equals any of the 17 account ids the landing zone knows: the
  members of `espn/teams`, among whom are every team's owners and every GUID-shaped author
  of `espn/transactions`.
- Today the two are written differently: the ids bare and lower case, every account id
  braced and upper case. Nothing documents that they must be.

`stg_espn__transactions` reads both ids: `topic_id` is a tie-break of its dedup, and
`transaction_id` is the message's id, part of the transaction's key. So ADR 0093's projection
holds them, and a projected row of `espn/transactions` fails 0054's check as it stands.
The fixtures avoid this by inventing ids (`topic-001`, `message-001-01`), which is right for a
public repo and would make the two warehouses' `transaction_id`s differ.

## Decision drivers

- No account id may go up, by any path (rule 2, ADR 0054).
- The two warehouses read the same values, so the slice comparison can hold them equal.
- An exemption from the check must be as narrow as the thing it exempts.
- Do not rest privacy on how ESPN happens to write a GUID today.

## Considered options

1. **Exempt the two paths, and cross-check their values.** A GUID is allowed only as the
   value at `$.topics[i].id` or `$.topics[i].messages[j].id` of an `espn/transactions` row.
   Each such value is compared, ignoring braces and case, with every account id found in
   the committed captures of `espn/teams` and `espn/transactions`. One equal value stops
   the upload.
2. **Exempt the two paths, with no cross-check.**
3. **Replace the ids in the upload only**, with a keyed hash of each. Ids stay distinct, so
   the dedup holds, but `transaction_id` differs between the warehouses.
4. **Replace the ids on both warehouses**: `stg_espn__transactions` selects a hash of each
   id instead of the id. Changes a column of the real warehouse.
5. **Tell the ids apart by their written form**: allow bare lower-case GUIDs.

## Decision

Chosen by the owner on 2026-10-22, at the spec's walkthrough: **option 1**.

The account ids are gathered from the raw captures, before projection, at these paths:
`members[].id`, `teams[].owners[]`, `teams[].primaryOwner` of `espn/teams`, and
`topics[].author`, `topics[].messages[].author` of `espn/transactions`, each kept when it is
one GUID whole (some authors are other strings, spec 0136 C8). If transaction rows
are to go up and that set is empty, the upload stops: a cross-check against nothing checks
nothing. A hit names the row and the path, never the value, as every hit does (spec 0130,
R3.3). Anywhere else in any ESPN row, including these rows' partitions, request and file
path, a GUID still stops the upload.

Option 2 trusts that ESPN never reuses an account id as a message id. The data agrees today,
and the cross-check costs one pass over 20 captures (13 teams, 7 transactions). Option 3 makes `transaction_id` a column
the slice comparison has to leave out. Option 4 changes the real warehouse for the sake of an
upload, which spec 0136 rules out. Option 5 rests on a convention ESPN never stated: it holds
today, and a change of case on either side would let an account id through.

## Consequences

- Good: the transaction log goes up with the ids its model reads, and an account id is
  still stopped wherever it appears, even at one of the two exempt paths.
- Bad / accepted cost: a message id that happens to equal an account the landing zone has
  never seen is not caught. An account that never owned a team or made a move has left no
  trace in the league to be caught by.
- Bad / accepted cost: the check now reads two endpoints' raw captures, not only the rows it
  checks.
- Follow-ups: #140's production loader carries the exemption and the cross-check over, or
  answers the ids another way.
