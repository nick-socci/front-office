# 0096. Every SQL model is written for both warehouses, and BigQuery builds all but the solver and its readers

- Status: accepted
- Date: 2026-10-23
- Spec: [0135-port-remaining-models](../specs/0135-port-remaining-models/design.md) · Issue: #135

## Context

ADR 0051 says how a model is written for two warehouses. The spike applied it to a slice,
`bigquery_slice`, defined as three models and everything upstream of them, and the rule
test scans only what that selector selects. The slice has grown to 48 models. The project
has 75: 74 SQL models and the lineup solver, a Python model (ADR 0039) whose place on
BigQuery is #137 (spec 0135, C1).

Three SQL models read the solver's output: `int_fantasy__lineup_category_totals`,
`fct_lineup_decisions` and `fct_lineup_decision_categories` (C2). They can be written to
the rule now, but cannot be built on BigQuery until the solver runs there. The other 23
can be built now, because #136 put every endpoint they read on BigQuery.

The selector is named in seven files: AGENTS.md, README, `dbt/selectors.yml`, three tests
and `scripts/compare_bigquery_slice.py` (C10).

## Decision drivers

- A model added later must be held to the rule without anyone remembering to add it.
- What runs on BigQuery is named in one place, and a test fails if it reads what is not
  there.
- #137 should have to decide only where Python runs, not port SQL as well.
- Little churn in files that nothing about this decision changes.

## Considered options

1. **Hold every SQL model to the rule; the selector becomes "every model except the solver
   and its descendants", keeping its name.** The rule test scans every SQL model and
   singular test from the manifest. BigQuery builds the selector.
2. **The same, renaming the selector to `bigquery`** (and the comparison script with it).
3. **Port and build only the 23.** The three solver readers stay DuckDB-only and go to #137.
   The selector keeps listing what it includes.
4. **Keep the inclusion-style selector**, adding the 23 as new members of its union.

## Decision

**Option 1**, chosen by the owner on 2026-10-23 going through the spec's decisions, with
the rename (option 2) left to #137. Accepted with the spec (PR #189).

Option 3 leaves #137 a port and a decision instead of a decision, and leaves three models
that drift from the rule with nothing to check them. Option 4 means every new model has to
be added to the union by hand, and `cautious` is applied to each union member separately,
so a test whose parents lie in two members falls out (the pytest written for spec 0147 is
there for that). Option 2 names the thing better but touches seven files and every later
spec's command for no change in behaviour. "Slice" stays true until #137 brings in the
last four models, and the rename can be made then, when the exclusion is gone.

## Consequences

- Good: a new SQL model is held to the rule and built on BigQuery by default. A new model
  that reads the solver is left out by the same exclusion.
- Good: AGENTS.md's rule reads "every SQL model", which is simpler to follow.
- Bad / accepted cost: the three solver readers are not built from real rows on BigQuery
  until #137. Until then their SQL is run there only over no rows, against an empty
  stand-in for the solver (spec 0135, R5.2).
- Bad / accepted cost: "slice" names something that is nearly the whole project.
- Follow-ups: #137 removes the exclusion. The rename (option 2) can be done then.
