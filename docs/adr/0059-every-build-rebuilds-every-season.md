# 0059. Every build rebuilds every season of a batched model

- Status: accepted
- Date: 2026-10-12
- Spec: [0143-staging-by-season](../specs/0143-staging-by-season/design.md) · Issue: #143

## Context

ADR 0058 builds five staging models a season a batch. A microbatch model, run without
`--full-refresh`, redoes only the current batch and as many before it as its
`lookback` says. A capture of a past season can still arrive: #83 backfills past
seasons, a boxscore is refetched inside its settle window (ADR 0019), and a second
boxscore pass of a past season is owed. A batch not redone would keep rows made from a
capture since superseded, and nothing would say so.

Measured on the prototype: a season's batch of roster entries takes 1 to 4 seconds, and
an ordinary run redoing every batch left exactly the rows of a full refresh (spec 0143,
C8, C9).

## Decision drivers

- A table must never hold a row a newer capture has replaced.
- No flag to remember: a plain `dbt build` must be right.
- Build time.

## Considered options

1. **Redo every season on every build**: the lookback is computed to reach the first
   season.
2. **Redo the current season and the one before**, and rely on `--full-refresh` after a
   backfill.
3. **Redo only seasons that have a capture newer than the table's rows.**

## Decision

Chosen by the owner on 2026-10-12, going through the spec's decisions: **option 1**. The lookback is the number of years from the project's first
season to the year of the run, computed by a macro, so every batch is replaced on every
build.

Option 2 is faster and wrong the first time someone backfills and forgets the flag.
Option 3 is the efficient form of option 1, and needs the model to compare itself with
its input before it runs: more machinery than seconds are worth, and a second way to be
stale.

## Consequences

- Good: a batched table always equals what a build in one piece would give.
- Good: the reason for batching stays memory alone; nothing about freshness changes.
- Bad / accepted cost: build time grows with the seasons loaded, by a few seconds a
  season a model; about a minute more with eight seasons, estimated from two.
- Follow-ups: if that time matters, option 3.
