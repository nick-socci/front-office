# 0017. A roster capture with no recorded status is judged by its run's settings capture

- Status: accepted
- Date: 2026-10-06
- Spec: [0027-settled-roster-captures](../specs/0027-settled-roster-captures/design.md) · Issue: #27

## Context

[ADR 0016](0016-a-roster-period-is-settled-by-the-status-in-its-own-response.md) settles
a period from a status recorded in the capture's sidecar. The 180 roster captures of
2026, and the committed fixtures, were written before that field existed, and landed
sidecars are never rewritten. Something has to say whether they are final. The reviewer's
follow-up rules out today's date and `latest == final`, and asks that captures which
cannot be shown final stay visible.

Measured on 2026: all 180 captures come from one run, whose settings capture records
latest period 186. Each roster payload's own `status` says 186 as well. The roster
payloads total 436 MB; a settings payload is 6 KB.

## Decision drivers

- The 2026 season must not be refetched or reinterpreted without cause.
- The fetch decision must stay cheap and must not read roster payloads (spec 0029).
- The audit and the fetch logic must agree.
- No dates.

## Considered options

1. **The settings capture of the same run** (same season, league and `fetched_at`).
2. **The capture's own payload**, read for its `status` block.
3. **Refetch every legacy period once** with `--refresh`, and have no legacy rule.
4. **`fetched_at` later than the season's end date.**

## Decision

Chosen: **option 1**, by the owner on 2026-10-06.

A roster sidecar with no `source_status` key takes as its evidence the
`status.latestScoringPeriod` of a committed settings capture with the same season, league
and `fetched_at`. If there is none, the capture is evidence of nothing and its period is
fetched again. A sidecar that has the key but an unusable value does not fall back to
this rule.

It is conservative because every run fetches settings before rosters and the counter
only moves forward, so the settings status is never ahead of a roster fetched later in
the same run. It is the rule the audit already applies, moved into the function both
share. Option 2 is the stronger evidence and agrees on all 180, but would parse 436 MB on
every run; it is used once, as a cross-check during verification. Option 3 needs a
credentialed run, adds 436 MB, and still leaves the fixtures and any restored capture
without a rule. Option 4 rests on a calendar anchor and on a run stamp that is not the
request's time.

## Consequences

- Good: 180 of 180 periods of 2026 are shown closed with no request to ESPN.
- Good: one 6 KB payload is read per legacy run; no roster payload is read.
- Bad / accepted cost: the rule depends on settings having been fetched before rosters in
  the legacy runs. That is how every run has worked, and the payload cross-check confirms
  it for 2026.
- Bad / accepted cost: two rules exist for as long as legacy captures do.
- Follow-ups: the owner can run `--refresh` on 2026 at any time before the 2027 rollover
  to give every period a capture with its own recorded status.
