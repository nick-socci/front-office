# 0147. A page shows mart columns and computes nothing; a new number is a new mart

- Status: accepted
- Date: 2026-11-21
- Spec: [0232-dashboard](../specs/0232-dashboard/design.md) · Issue: #232

## Context

Every number in the marts is held by dbt tests, built identically on two warehouses (ADR 0116) and,
where ESPN reports it, reconciled against ESPN. A number worked out in a page has none of that. The
first pages already need two numbers no mart holds: team names and standings (C3, C6). ADR 0045 made
the marts "the dashboard's interface".

## Decision drivers

- Every number the owner reads is tested where the project tests numbers.
- Pages stay small, and reviewable as queries.
- Adding a page should not mean re-deriving a number another page derives differently.

## Considered options

1. **Pages select, filter, sort and join on keys; they never aggregate or do arithmetic across
   columns.** A gate parses every page query (sqlglot) and fails on `group by`, an aggregate, a
   window, or arithmetic over two columns. A new number is a new mart. Formatting is Python, for
   display only.
2. **Pages may aggregate in SQL**, tested by pytest over the fixtures.
3. **Pages compute in pandas** after reading whole marts.

## Decision

Chosen by the owner on 2026-11-22, at the spec's walkthrough: **option 1**, as recommended. Option 2 tests a page's number on the fixtures only, never on the
real season or against ESPN, and never on BigQuery. Option 3 is that, and harder to read. The cost
of option 1 is a mart for every new number. That cost is deliberate: the number is then tested
once and is the same on every page that shows it.

## Consequences

- Good: the dashboard cannot be wrong where the marts are right. The exposure is exactly what the
  pages read (spec R4.3).
- Bad / accepted cost: some views wait for a mart. This spec adds two (`dim_fantasy_teams`,
  `fct_team_standings`).
- Follow-ups: projections and waiver targets (roadmap item 2) arrive as marts first, then pages.
