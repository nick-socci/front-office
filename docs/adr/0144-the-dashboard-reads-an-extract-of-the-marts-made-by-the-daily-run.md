# 0144. The dashboard reads an extract of the marts, made by the daily run

- Status: proposed
- Date: 2026-11-21
- Spec: [0232-dashboard](../specs/0232-dashboard/design.md) · Issue: #232

## Context

The dashboard (sub-project 5) runs on `mothership` (ADR 0126). ADR 0123's follow-up says it "reads
BigQuery", the warehouse built each day. The nine marts are about 20 MB there (spec C1), and
`tabledata.list` reads a table without billing a query (C10). Only the run's identity can reach
BigQuery from the host today, and it can write every model dataset (ADR 0135, C11). CI has no
BigQuery (ADR 0110), so pages that query BigQuery could not be tested in CI as they run in production.

## Decision drivers

- No credential in a process that serves web pages.
- $0 a month, and nothing taken from the free terabyte the builds will need by 2028 (0216 C16).
- The pages run in CI on the same engine they run on in production.
- A failed build must not show a mix of new and old tables.

## Considered options

1. **An extract made by the run**: a `marts_extract` asset copies the exposure's marts into a DuckDB
   file by `tabledata.list`, published by one rename. The app reads only that file.
2. **BigQuery, queried by the app**, as a new read-only service account, with results cached.
3. **DuckDB built on `mothership` each day**, beside the BigQuery build.
4. **BigQuery through the run's own key**, mounted into the dashboard.

## Decision

Chosen by the owner on 2026-11-22, at the spec's walkthrough: **option 1**, as recommended. It needs no new credential, bills nothing, and leaves the app able to
reach only one read-only file. It makes the CI warehouse and the production data the same engine,
DuckDB. Option 2 needs a second key on the host and bills each uncached view. Option 3 rebuilds what
BigQuery already built and brings back the memory ADR 0123 avoided. Option 4 gives a web-facing
process write access to every dataset.


## Consequences

- Good: no Google identity or key for the dashboard. Page views are local reads of about 20 MB.
- Good: the extract is all of one green build or none of it, and carries its own age (`extract_info`).
- Bad / accepted cost: anything that fails the dbt step also holds the extract back, an unrelated
  reconciliation test included. The page then shows yesterday's data with a warning.
- Bad / accepted cost: the data is as fresh as the last run, once a day. Nothing is live.
- Follow-ups: ADR 0123's "sub-project 5 reads BigQuery" is met through the extract. Revisit if a
  page ever needs data fresher than the run.
