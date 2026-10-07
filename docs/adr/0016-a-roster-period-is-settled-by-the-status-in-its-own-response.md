# 0016. A roster period is settled by the status recorded from its own response

- Status: accepted
- Date: 2026-10-06
- Spec: [0027-settled-roster-captures](../specs/0027-settled-roster-captures/design.md) · Issue: #27

## Context

A scoring period's roster can change until the period closes. The fetch logic skips a
period once any capture exists and the league has moved past it, so a capture taken
while the period was current is kept as if it were final (review finding R1). The agreed
fix is to record the league's status with each capture and to call a period settled only
when a committed capture shows the league past it. The reviewer added one condition: the
status must be captured close enough to the roster request that a run crossing a period
boundary cannot misstate finality.

Measured on the 180 roster captures of 2026: every roster response carries a top-level
`status` block, and its `latestScoringPeriod` is the league's current period at the time
of the request (186 in every payload, whichever period was asked for). `fetched_at` is
the run's stamp, shared by all captures of a run, so it cannot say when one request was
made.

## Decision drivers

- A period must never be called final on evidence older than its roster.
- The evidence should be checkable later, from what was landed.
- No dependence on the order of steps within a run.
- No extra load on a private API with no published rate limit.

## Considered options

1. **The roster response's own `status` block**, copied into the sidecar.
2. **The status from the run's settings capture**, copied into each roster sidecar.
3. **A status request immediately before each roster request.**

## Decision

Chosen: **option 1**, by the owner on 2026-10-06.

The roster fetcher copies `latestScoringPeriod` and `finalScoringPeriod` from the response
it is landing into the sidecar, as `source_status: {latest_scoring_period,
final_scoring_period}`. Period P is closed if and only if some committed roster capture
of P records `latest_scoring_period > P`. How long a closed period goes on being fetched
is [ADR 0018](0018-a-closed-roster-period-is-rechecked-for-seven-periods.md). The
current run's status decides only which periods exist; it settles nothing. A response with no usable status lands with a null
value and is evidence of nothing.

The roster and the counter arrive in one response, so there is no interval between them
for a boundary to fall into, and the recorded value can always be compared with the
payload beside it. Option 2 can only err towards fetching again, which is safe, but its
evidence is about a different request and holds only while settings is fetched first.
Option 3 is as safe as option 2 and tighter, for twice the requests.

## Consequences

- Good: a run that crosses a period boundary judges each capture by its own response.
- Good: settled is decided from sidecars alone; no payload is read.
- Good: a stale or missing status delays settling by a run and is reported; it never
  freezes a period.
- Bad / accepted cost: it assumes ESPN does not serve a roster older than the status in
  the same response. Option 2 does not need that assumption.
- Bad / accepted cost: the ingestion package copies two fields out of a response it
  otherwise never interprets.
- Bad / accepted cost: each period is captured at least twice in daily operation, about
  0.9 GB a season before ADR 0018's re-check.
- Follow-ups: #66, an in-season check in 2027 that a closing capture equals a later one;
  #30 can record a boxscore's game state under the same sidecar key.
