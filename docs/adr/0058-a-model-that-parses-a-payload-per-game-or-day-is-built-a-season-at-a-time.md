# 0058. A staging model that parses one payload per game or per scoring period is built a season at a time, by dbt's microbatch

- Status: superseded by [0069](0069-staging-models-are-built-whole-not-a-season-at-a-time.md)
- Date: 2026-10-12
- Spec: [0143-staging-by-season](../specs/0143-staging-by-season/design.md) · Issue: #143

## Context

Five staging models each parse a large JSON payload per game or per scoring period:
the two MLB game logs and the three ESPN roster models. DuckDB holds a run's parsed
payloads at once, and the step does not spill to disk. With two seasons loaded the three
roster models fail under a 12 GB memory limit on one thread and need 16 (spec 0143, C7);
the whole run passes on `main` at the default limit with a peak of 23.1 GB on a 29 GB
machine (C2). #83 lands five more seasons, about four times the captures.

A prototype on 2026-10-12 built `stg_espn__roster_entries` with dbt's microbatch
strategy, a season a batch: the same 113,059 rows as the table built in one piece, none
differing, at a peak of 7.2 to 7.4 GB (C8).

## Decision drivers

- Peak memory must not grow with the seasons loaded.
- No row may change.
- One `dbt build`; nothing for a person to remember.
- dbt should still run, document and test the SQL it shows.
- Ingestion does not interpret payloads.

## Considered options

1. **dbt's microbatch, one batch per season**, through a view that gives each capture
   its season as a date.
2. **One DuckDB thread and a memory limit** in the profile.
3. **A season loop of our own**, in a macro or a script before dbt.
4. **Parse payloads when they are loaded**, in `load.py`.
5. **Build the heavy step elsewhere**: a bigger machine, or BigQuery.

## Decision

Chosen by the owner on 2026-10-12, going through the spec's decisions: **option 1**, for exactly these five models and for any later model of the
same kind (#83's `stg_espn__matchup_days` is the sixth).

Each becomes an incremental model with `incremental_strategy='microbatch'`,
`batch_size='year'`, and a `season_start` date column as its event time. It reads its
captures through `stg_raw__season_responses`, a view over the raw table that declares
the same column as its event time, so dbt hands each batch one season's captures.

Option 2 does not hold: the roster models do not spill, and two seasons already exceed
12 GB on one thread. Option 3 gives the same memory and takes the SQL out of dbt's sight.
Option 4 has ingestion decide what a payload means. Option 5 makes a local build depend
on a machine the project does not have, or on a warehouse 26 models are not ported to.

## Consequences

- Good: memory is set by the largest season, about 8 GB for a roster model today.
- Good: the build is still one command, and CI runs the batched path.
- Bad / accepted cost: three dbt concepts to carry (incremental, microbatch, event time)
  and a column, `season_start`, on five models that exists for the batching.
- Bad / accepted cost: a column added to one of these models needs `--full-refresh`.
- Bad / accepted cost: a batched model that reads an input with no event time inserts
  every season's rows in every batch. A test in the gates guards it; dbt does not.
- Bad / accepted cost: the batch is a calendar year because the raw table records a
  capture's season and not its date. A season that outgrows one batch has no smaller
  unit without a change to what is landed.
- Follow-ups: #83 resumes on this; if one season of rosters nears the limit, revisit the
  unit of a batch.
