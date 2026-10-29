# 0107. A ranking checks its own window, and a tie across its cut stops the build

- Status: accepted
- Date: 2026-10-28
- Spec: [0141-total-tie-breaks](../specs/0141-total-tie-breaks/design.md) · Issue: #141

## Context

AGENTS.md rule 5 asks every keep-one-row step for a deterministic tie-break, and nothing
checks it. The BigQuery spike found two steps whose order tied, broken one way by DuckDB in
every build and the other way by BigQuery (spec 0141, C13). One more tie is in the real
season today: the id map gives ESPN id 5214984 to two MLB players (C2, C3). The CI fixtures
hold no tie at all (C6), so nothing that runs only in CI can see one.

Eight of the steps rank a CTE over parsed captures, not a relation (C1). A tie only matters
where a ranking cuts: a tie inside the kept rows, or inside the dropped ones, changes
nothing.

## Decision drivers

- The check runs on the data that has the ties: the real season, on both warehouses.
- It covers steps whose input is not a relation, without parsing a heavy endpoint twice
  (ADR 0102).
- It costs nothing a build can measure.
- It fails on a tie both warehouses happen to break alike, not only on one they break
  differently.

## Considered options

1. **The macro checks its own window.** `fo_keep_first` computes `rank()` over the window it
   already computes `row_number()` over. When the row just past the cut ranks within it, the
   row's `CASE` branch calls `error()`. The build stops, naming the node, the place and the
   partition.
2. **A generic data test on each step's input**, as the issue proposed. The input has to be
   a relation.
3. **A gate script** that rewrites each compiled `qualify` into a probe and runs it against a
   warehouse.
4. **Comparing DuckDB with BigQuery**, as the spike did.

## Decision

Chosen by the owner on 2026-10-28, as recommended: **option 1**.

The check sits where the cut is made, so it sees whatever rows reach it, in every build,
on DuckDB and BigQuery alike (C8, C10). `row_number()` and `rank()` over one window are one
WINDOW operator, and on the heaviest step the time and peak memory are within run-to-run
noise (C9). The same SQL text raises on both warehouses, because both have
`error(string)`.

Option 2 needs a relation per input. For the eight steps over parsed captures, that means
parsing them twice, which ADR 0102 forbids. Option 3 finds nothing on the fixtures (C6),
and on the real season it is a check someone has to remember to run. Option 4 sees only the
ties the two warehouses break differently, after the fact, and bills a build each time.

## Consequences

- Good: rule 5 holds on the real season in every build, and the error says where to look.
- Good: no new relation, test or plant. The macros' behavior is proved over literal rows
  by a pytest (R4.1), since the fixtures cannot hold a tie.
- Bad / accepted cost: a tie stops the whole build, not one test. There is no warn mode.
  Once runs are scheduled (sub-project 4), a new listing quirk in MLB's or the id map's
  data will stop a daily run until someone states a tie-break. That is preferred to a
  silently different row.
- Bad / accepted cost: a tie between rows that are identical in every kept column also
  stops the build. Such rows are made distinct before the ranking (spec 0141, R3.3).
- Follow-ups: the order of nulls differs between the warehouses, which is a separate
  source of difference this check does not see (spec 0141, task 10).
