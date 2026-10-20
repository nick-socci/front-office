# 0087. A data test CI cannot exercise is shown to fail on a planted row

- Status: proposed
- Date: 2026-10-20
- Spec: [0174-planted-test-failures](../specs/0174-planted-test-failures/design.md) · Issue: #174

## Context

No row of the CI fixture warehouse is verified. A fixture date is complete only when all
its games have boxscores, and the fixtures hold 3 of 38 (spec 0174, C1 and C2). So every
data test restricted to verified rows passes on zero rows in CI. So do the seed test of
#159 and both ESPN reconciliation tests (C3, C4). On #172 and #173 such tests were shown
to fail by hand, on CI-warehouse copies with a row planted (C5). Nothing repeats that.

Making the fixtures hold verified rows honestly needs a complete real matchup period: the
fixture's ESPN scores come from another period than its rosters (C10). One playoff period
would roughly quadruple the fixtures (C9). Even then no 2026 side is below the pitching
minimum, so that case could not come from it (C11).

## Decision drivers

- A test that guards a rule must be seen to fail on the case it exists for, every run, not
  once at review.
- Cases no real fixture holds (a side below the minimum, a missing seed) need covering too.
- The test must be judged exactly as the gate judges it: its `where`, severity and count.
- Keep the committed fixtures small and real; no rewritten ESPN data.

## Considered options

1. **A planting harness.** Per plant: copy the CI warehouse, change rows, run the real
   `dbt test`, and compare the result with the expected status and failure count.
2. **A real matchup period in the fixtures**: one complete playoff period of 2026.
3. **Complete the three fixture dates**: all 38 boxscores.

For running a plant: dbt in-process (`dbtRunner`), the compiled SQL run directly, or dbt
unit tests.

## Decision

Chosen by the owner on 2026-10-20: **option 1**, run in the gates after the fixture build.
In a second answer the same day, the owner chose the real `dbt test`, invoked in-process
(`dbtRunner`) on each copy.

The harness shows that each covered test fails on the row it exists for, and, where a
plant marks the edge of a rule, that it passes on a row it must let through. A plant whose
statements change no row fails, so a plant can't go quietly empty when the fixtures move.

Option 2 runs the models end to end on verified rows but quadruples the fixtures and still
lacks the below-minimum case. Option 3 makes both reconciliation tests fail on a period
mismatch, unless ESPN's scores are rewritten, which would reconcile the models against
themselves. Running compiled SQL would re-implement dbt's test wrapping and could drift
from the gate. dbt applies no data test to a unit test's mocked rows (#173, round 3).

## Consequences

- Good: the hand plants of #172 and #173 become permanent checks; the edge cases no fixture
  holds are covered; no fixture data changes.
- Good: about 1.3 s a plant (C6).
- Bad / accepted cost: a plant shows the test fails on a row shaped like the model's
  output, not that the model could produce that row. The models' behaviour on verified
  data is still checked only by unit tests and the real-season build.
- Bad / accepted cost: plants name fixture rows (matchup 1, team 6), so regenerating the
  fixtures can mean rewriting plants. The harness names each one that stops planting.
- Follow-ups: #178 (the missing `matchup_days` fixture endpoint). A real-matchup fixture
  stays possible later, and nothing here prevents it.
