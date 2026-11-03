# 0120. An upload appends what each table lacks, and a changed structure rebuilds one table

- Status: accepted
- Date: 2026-11-02
- Spec: [0140-production-raw-loader](../specs/0140-production-raw-loader/design.md) · Issue: #140

## Context

The spike replaces its table on every run, against the append-only record ADR 0011 describes. A
production upload runs often, can stop partway, and each endpoint's table is a separate load job, so
no single atomic step covers a run. DML would bill bytes and adds nothing a load job lacks. A declared
structure also changes from time to time: AGENTS.md's way to read a new field is to add it there,
and then every stored row lacks it.

## Decision drivers

- A rerun is always safe: no duplicate, and no flag to remember.
- No capture is dropped silently (ADR 0011).
- No billed query in the routine path.
- A daily run does not re-read gigabytes.

## Considered options

For staying correct:

1. **Each table compared with the landing zone, on every run.** Read keys by the free table read API,
   send what each lacks, append the manifest after its table.
2. **The manifest as the only record of what went up**, read once. Cheaper by a few reads, and a stop
   between a table and the manifest duplicates that table's rows on the next run.
3. **Replace every table each run.** Free and simple; no record of history, and rereads 44,426
   captures a day.

For a changed structure:

4. **Refuse to append, and rebuild that one table by one load job** from the landing zone, on the
   owner's command.
5. **Add the column by a schema update and leave old rows null.** A new field's value would be wrong on
   old rows without saying so.

For checking:

6. **Each run: job row counts, and each table's `file_path`s equal to the zone's; `--verify` compares
   whole rows** when a table is first filled or rebuilt.
7. **Compare every row on every run**, as the spike does: minutes and gigabytes, daily.

## Decision

Chosen by the owner on 2026-11-02, at the spec's walkthrough: **options 1, 4 and 6**.

A key already stored with a different `file_path` stops the upload, as `front-office load` does:
ADR 0011's refusal, with no rule yet for resolving one. A row is never replaced in normal running; the
rebuild is the one exception, and it is by command, atomic per table, and free.

## Consequences

- Good: a stopped run needs nothing but another run, and leaves the manifest behind its tables, never
  ahead.
- Good: nothing in the routine path bills.
- Bad / accepted cost: a rebuild can leave a build failing until it is run, loudly. A new field means
  dbt and the upload change together.
- Bad / accepted cost: a value altered in place between load and read would pass a daily run; `--verify`
  is by hand. Nothing writes to these tables but the loader.
- Bad / accepted cost: a local lock stops two runs on one machine; two machines are not guarded. Their
  duplicate keys fail the run's check afterwards, and a rebuild clears them.
