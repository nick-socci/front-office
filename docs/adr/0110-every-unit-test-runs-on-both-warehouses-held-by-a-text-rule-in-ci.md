# 0110. Every unit test runs on both warehouses, held by a text rule in CI

- Status: accepted
- Date: 2026-10-29
- Spec: [0138-unit-tests-on-bigquery](../specs/0138-unit-tests-on-bigquery/design.md) · Issue: #138

## Context

Every model is written once for both warehouses (ADRs 0051, 0105). The unit tests are
not: 45 of 223 cannot run on BigQuery because of their fixtures (spec 0138, C3, C4). The
list has grown with almost every PR since the spike. So the BigQuery forms of the JSON
macros and of the capture views' parses are checked only by comparing whole builds.

CI has no BigQuery credentials. A BigQuery run of the unit tests bills nothing (C5), but
it needs a complete build of the branch to run against (C2, C3).

## Decision drivers

- One definition per test, run on both warehouses.
- A fixture only DuckDB can run is caught when it is written, not at the next by-hand
  BigQuery run.
- Credentials stay where they are: in the owner's hands, outside CI.

## Considered options

1. **Every test portable. A text rule in pytest holds the fixtures, and a by-hand
   BigQuery run, recorded on the issue, checks them.** The rule is the existing
   portable-SQL rule, extended to fixtures.
2. **Every test portable, with the BigQuery unit tests in CI.** CI gets a service account
   that can create datasets, builds a suffixed `--empty` copy, and runs the unit tests on
   each PR.
3. **The staging tests stay DuckDB-only**, tagged and left out of BigQuery runs. Only the
   DuckDB-SQL fixtures outside staging are rewritten.
4. **All 45 stay DuckDB-only**, tagged and left out.

## Decision

Chosen by the owner on 2026-10-29: the goal (options 1 and 2 over 3 and 4), and then,
as recommended, **option 1**.

Option 2 would catch what a text rule cannot see, such as a BigQuery form that is wrong
on a test's case. It would also put a key that can create and delete BigQuery datasets
into CI, for a public repository. It needs about five minutes of BigQuery per PR, and a
function image built on each run. That is a credentials decision, and it fits better
with the orchestration work of sub-project 4. Options 3 and 4 leave #138's concern where
it is.

## Consequences

- Good: a new DuckDB-only fixture fails the gates with the test named, in seconds.
- Good: the rule's two new constructs (comma join, WHERE with no FROM) hold models too.
- Bad / accepted cost: between by-hand runs, a fixture can still go wrong on BigQuery in
  a way the text rule cannot see (a type, a JSON path). The next run finds it.
- Follow-ups: revisit option 2 when the orchestration of sub-project 4 decides where
  BigQuery credentials live.
