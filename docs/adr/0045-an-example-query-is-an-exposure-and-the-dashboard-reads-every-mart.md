# 0045. An example query is an exposure the gates check, and the planned dashboard reads every mart

- Status: proposed
- Date: 2026-10-09
- Spec: [0013-docs-lint-exposures](../specs/0013-docs-lint-exposures/design.md) · Issue: #13

## Context

An exposure declares a consumer of dbt models that dbt does not build. dbt checks that
the models it names exist; it does not check that the consumer reads them, or anything
else about it. So an exposure is only as true as whoever wrote it.

Two consumers are in the issue. The dashboard does not exist (`dashboard/` is empty;
the README's roadmap gives it four pages in a sentence). The example queries are one
file, `docs/examples/roster_day_query.sql`, which reads seven staging models and no
mart, and which nothing runs: it works today (18 rows on the real season, 0 on the
fixtures, where team names are aliased) only because nobody has renamed what it reads.

Checked on 2026-10-09 in dbt 1.12.5: `--select +exposure:<name>` selects an exposure's
upstream models, and the exposure appears in the generated site.

## Decision drivers

- A declared dependency that nothing checks goes stale silently.
- The dashboard's real dependencies are unknown, and guessing them is a column-set
  decision made before the thing exists.
- The lineage should end somewhere a reader recognises.

## Considered options

For the examples:

1. **One exposure per example file, and a gate that reads the file**: it fails if the
   relations the file names differ from the exposure's, and it runs the file on the
   fixture warehouse.
2. **One exposure per example file, written by hand and trusted.**
3. **Move the examples into dbt as `analyses/`**, which dbt compiles but does not run.

For the dashboard:

- A. **Depends on every mart**, with a gate that fails when a mart is added and not
  listed.
- B. **Depends on a chosen subset**, page by page.
- C. **Not declared until it exists.**

## Decision

Recommended, for the owner to decide: **option 1 with A**.

`scripts/check_examples.py` is the gate. Each `docs/examples/*.sql` has an exposure of
type `analysis` named for the file. `front_office_dashboard` is type `dashboard`,
maturity `low`, with a description that says it is planned. Owners carry a name and no
email: the site is public.

Option 2 is the failure the driver names. Option 3 would have the examples use
`ref()`, so they could no longer be pasted into a DuckDB prompt, which is what they are
for; and dbt would still not run them. B is a guess about pages nobody has designed. C
leaves the lineage ending at the marts and the issue's item undone.

## Consequences

- Good: an example cannot rot unnoticed, and its exposure cannot lie.
- Good: "everything the dashboard needs" is one selector, before the dashboard exists.
- Bad / accepted cost: A says less than it appears to. It records "the marts are the
  dashboard's interface", not what any page reads. When the dashboard is built, its
  exposure is rewritten from what it actually queries.
- Bad / accepted cost: the gate finds relations by matching `schema.model` names in
  the file's text. An example that built a name dynamically would escape it; none
  does, and the gate fails on a file in which it finds no relation at all.
- Bad / accepted cost: on the fixtures an example is only proved to run, not to return
  rows.
- Follow-ups: the dashboard's exposure at sub-project 3.
