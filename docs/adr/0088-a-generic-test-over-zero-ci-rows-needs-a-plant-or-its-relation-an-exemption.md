# 0088. A generic test over zero CI rows needs a plant, or its relation an exemption

- Status: accepted
- Date: 2026-10-20
- Spec: [0174-planted-test-failures](../specs/0174-planted-test-failures/design.md) · Issue: #174

## Context

The issue names a handful of tests, but counting shows more. 35 of 412 generic tests read
zero rows of the CI warehouse (spec 0174, C3):
- **4** because their `where` admits no CI row. They carry this project's logic: verified
  rows, the input-status rule.
- **31** because their whole relation is empty in CI: 7 relations, under 22 `not_null`, 6
  `unique_combination_of_columns` and 3 `accepted_values` tests (C8).

A singular test's input can't be measured from the manifest. Both builds where review found
a vacuous test (#172, #173) had to notice it by hand.

## Decision drivers

- A new vacuous test should be found by the gate, not by a reviewer.
- A plant should prove something about this project's tests, not that dbt's built-in
  `not_null` fires.
- An empty relation in CI is a fixture fact worth seeing, and is decided once per
  relation, not once per test.
- Little upkeep when the fixtures change.

## Considered options

1. **Detect generic tests; exempt empty relations.** A generic test whose relation has CI
   rows but whose `where` admits none must have a plant. A relation with no CI rows must
   have one exemption, with a reason and an issue or ADR link.
2. **Detect generic tests; plant all of them.** The same detection, and a plant for each
   of the 35, inserting a null or duplicate row into each empty relation.
3. **Exempt by kind.** `not_null`, `unique`, `unique_combination_of_columns` and
   `accepted_values` never need a plant; other generic tests over zero rows do.
4. **Named tests only.** Register the tests the issue names and rely on convention.
5. **Plant every singular and conditional test**, about 80 now.

## Decision

Chosen by the owner on 2026-10-20: **option 1** (the owner first chose detection over
options 4 and 5, then relation-level exemptions over options 2 and 3).

Singular tests are not detected. They get plants by convention: `AGENTS.md` says that a
test whose failing case the fixtures can't hold gets one, and that the plants proving a
new test can fail are committed rather than run by hand.

Option 2's 31 plants into empty relations would each show only that dbt's built-in test
fires on a planted row; the relation being empty is the fact worth seeing. Option 3 lets a
new empty relation pass unremarked. Option 4 is how #172 and #173 went. Option 5 is the
widest, but costs about 80 plants now and upkeep at every fixture change, for tests most
of which already see CI rows.

## Consequences

- Good: a new generic test with a `where` that CI never satisfies fails the gate until it
  has a plant. A relation that becomes empty in CI fails it until someone writes down why.
- Good: the 7 empty relations are listed with their causes; two are a fixture gap (#178).
- Bad / accepted cost: a singular test can still be vacuous unnoticed if its author skips
  the convention.
- Bad / accepted cost: a generic test whose `where` admits a few CI rows, none of which
  could fail it, is not caught. Detection proves that rows reach the test, not that they
  test anything.
