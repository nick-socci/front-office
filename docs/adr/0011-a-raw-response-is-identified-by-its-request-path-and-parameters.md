# 0011. A raw response is identified by its request path and parameters

- Status: proposed
- Date: 2026-10-04
- Spec: [0028-league-season-identity](../specs/0028-league-season-identity/design.md) · Issue: #28

## Context

`raw.api_responses` is keyed by (source, endpoint, `request_key`, `fetched_at`), and
`request_key` is the request's query parameters. ESPN puts the season and league in the
URL path (`…/seasons/2026/segments/0/leagues/<id>`), so two leagues, or two seasons,
asked the same question in the same second have the same key. The loader keeps the first
and drops the rest: four landed settings responses load as one row.

Every sidecar already records the full URL and the landing partitions (2,688 of 2,688).
The review and the owner agreed the direction in #28; this records it with the
alternatives.

## Decision drivers

- No capture may be dropped silently.
- Equivalent requests must have equal identities: the URL's query string varies in order
  and form (`view=a&view=b` against params `view=a,b`).
- Old sidecars must rebuild without being rewritten.
- One rule for every source, not an ESPN special case.

## Considered options

1. **Request path in the key, partitions as a column** — the key gains the URL's path;
   the landing partitions are stored beside it for staging to read.
2. **Partitions in the key** — a canonical string of the landing partitions replaces the
   path.
3. **The full URL in the key** — as first proposed in the review response.
4. **Fold the path into `request_key`** — one identity string, no new key column.

## Decision

Chosen: **option 1**. The key is (source, endpoint, `request_path`, `request_key`,
`fetched_at`). `request_path` is the sidecar URL's path with no scheme, host or query
string and no trailing slash, derived at load by one function, for old and new sidecars
alike. `partitions` is stored as JSON and is what staging reads league and season from.
A second capture with the same key fails the load.

Partitions are a choice the extractor made about folders, not the request: the
transaction pages carry an `offset` partition on two captures of three. They are the
right thing to *read* identity from and the wrong thing to *define* it by. The full URL
includes the query string, so reordered parameters would be different requests. Folding
the path into `request_key` changes the meaning of a column that `fo_request_param`
parses and the audit compares.

The host is left out: ESPN has moved this API between hosts, and `source` already says
whose API it is.

## Consequences

- Good: on the real landing zone the new key gives 2,688 distinct keys from 2,688
  captures; the four-capture collision loads as four rows.
- Good: no landed file or sidecar changes.
- Bad / accepted cost: the raw table's shape changes, so an existing warehouse cannot be
  loaded into; it is rebuilt into a new file and compared.
- Bad / accepted cost: identity is derived at load, not recorded at landing. A sidecar
  with no URL has no identity and is skipped with a warning, as one with no metadata is
  today.
- Bad / accepted cost: one colliding pair blocks the whole load until a person removes or
  fixes a file. There is no rule for choosing which to keep; the owner wants to see
  collisions in live operation before designing one (2026-10-04).
- Follow-ups: #57 can land earlier seasons once this is in. A way to resolve a collision
  is a later decision.
