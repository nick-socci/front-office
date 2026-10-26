# 0100. The development build runs one node at a time, on four DuckDB threads

- Status: proposed
- Date: 2026-10-25
- Spec: [0156-build-memory-flat-across-seasons](../specs/0156-build-memory-flat-across-seasons/design.md) · Issue: #156

## Context

ADR 0065's bar asks that the full build's smallest DuckDB memory limit (1, 2, 4, 8 GB) be
the same for one season as for eight, with the committed profile. With today's profile
(4 dbt threads, DuckDB's default of 16 threads) it is 2 GB for 2026 and 4 GB for eight
seasons (spec 0156, C3).

dbt-duckdb builds every node on one DuckDB instance (C12), so `memory_limit` and DuckDB's
`threads` are shared by all the nodes dbt runs at once. A node that streams its parse
still needs about 1.5 GB at 16 DuckDB threads and 0.5 GB at 4 (C8). The two game-log
models need 3 GB alone at 16 threads for eight seasons, and every growth-free rewrite of
them found costs more (C15). Fewer DuckDB threads alone makes the build worse (2 / 8 GB,
C16): each node runs longer, so more of them overlap under the one limit.

Spec 0150 had a no-go on any thread count in the committed profile. ADR 0065 asks only
that the committed profile work as committed, with no override.

## Decision drivers

- The bar can be met: 2026 and eight seasons reach the same rung.
- The committed profile works as committed; no one sets a variable to build.
- The real-season build stays usable on the development machine (minutes, not hours).

## Considered options

1. **One dbt thread, four DuckDB threads** in the `dev` target.
2. **Today's profile, plan shapes fixed only.**
3. **One dbt thread, DuckDB's default threads.**
4. **Four dbt threads, four DuckDB threads.**

## Decision

Chosen by the owner on 2026-10-25: **option 1**. In `dbt/profiles.yml`, the `dev` target
sets `threads: 1` (dbt) and `settings: {threads: 4}` (DuckDB). The `ci` and `bq` targets
are unchanged.

It is the only profile measured to bring both roots toward 1 GB: `main` as it is reaches
1 GB for 2026 and 2 GB for eight seasons (C20). With matchup days' plan fixed, eight
seasons at 1 GB fails only on two tests that read the MLB schedule (C21). Option 2 is not
shown to meet the bar: at 16 threads the game logs alone need 3 GB, more than 2026's whole
build. Option 3 failed eight seasons at 2 GB on the game logs (C23). Option 4 measured
2 / 8 GB on `main` and 2 / 4 GB with matchup days fixed (C16, C17).

## Consequences

- Good: no two heavy nodes share the memory limit, so a node's need alone is the build's
  need; a per-node measurement predicts the ladder.
- Good: the floor of a streaming node drops from about 1.5 GB to 0.5 GB.
- Bad / accepted cost: the real-season build is slower: 2026 72 s instead of 57 s, eight
  seasons about 300 s instead of 226 s (C3, C20).
- Bad / accepted cost: the `dev` and `ci` targets differ in concurrency, so a race between
  concurrently built nodes could show in CI and not locally (none is known; nodes share
  no writes).
- Follow-ups: the lineup solver is 136 s of the eight-season build in one Python thread
  (C14); parallelizing it is a separate question, outside this spec.
