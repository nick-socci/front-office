# 0097. A transaction is dated by the Eastern date of its instant, whatever the session's time zone

- Status: accepted
- Date: 2026-10-23
- Spec: [#188](https://github.com/nick-socci/front-office/issues/188) · Issue: #188

## Context

`fo_eastern_date` (`dbt/macros/eastern_date.sql`) holds the rule: a fantasy day rolls over
at midnight US/Eastern, and its DuckDB form reads a plain `timestamp` as UTC.
`stg_espn__transactions` gave it `to_timestamp(ms / 1000)::timestamp`. `to_timestamp` returns
a `timestamptz`, and DuckDB's cast from that to a plain `timestamp` gives the wall-clock time
in the session's time zone, which DuckDB takes from the process's `TZ`. So the date was
correct in a UTC session and wrong anywhere else.

Measured on 2026-10-23 against the real 2026 season (#188): in an America/New_York session,
28 of 737 transactions were dated a day early, all between 00:15 and 03:09 Eastern. Rosters
support the corrected date. `int_fantasy__transactions` has the same 28 rows, and at most 17
rows of `fct_transaction_impact` change. CI runs in UTC, and none of the fixtures' 11
transactions is affected, so no gate saw the bug.

`stg_espn__pro_games` reaches the same macro through `fo_timestamp_from_millis`, whose
DuckDB form `epoch_ms()` returns a UTC `timestamp` in any session, and is not affected.

## Decision drivers

- A warehouse built on the owner's machine must equal one built in CI.
- Don't change the rule. The Eastern date is already the project's meaning of a day.
- Stay inside the two-warehouse rule (ADR 0051), so the #135 port does not have to redo this.
- A test must fail under the bug in CI, which runs in UTC.

## Considered options

1. **Date the transaction from its milliseconds, through `fo_timestamp_from_millis`.**
   `fo_eastern_date(fo_timestamp_from_millis(ms))`, as `stg_espn__pro_games` already does.
   No new macro. Both dispatched forms already exist.
2. **Add an instant-typed macro and date `transacted_at`.** A dispatched
   `fo_instant_from_millis` for `transacted_at`, and `fo_eastern_date` fed from it. This also
   ports `transacted_at`, which is #135's work, and it changes what `fo_eastern_date`
   accepts, which `stg_espn__pro_games` relies on.
3. **Pin DuckDB's session TimeZone to UTC in `profiles.yml`.** Every local build would then
   behave like CI. This does not fix the model: it hides this bug and any like it, and it
   changes how every `timestamptz` displays for the owner.

## Decision

Option 1. `transaction_date` is computed as `fo_eastern_date(fo_timestamp_from_millis(ms))`
from the message's own milliseconds. `transacted_at` is unchanged. Porting it is #135's work.

The unit test `transactions_are_dated_by_the_eastern_date_of_their_instant` holds three
instants:
- just after Eastern midnight, which catches a date read through the session's clock;
- late Eastern evening, which catches the UTC date;
- a winter instant, which catches a fixed four-hour offset.

`ingestion/tests/test_transaction_date_time_zone.py` runs that unit test under
America/New_York, America/Los_Angeles and Asia/Tokyo. The gates' build runs it in UTC.

## Consequences

- Good: a New York build and a UTC build of the real season give the same
  `transaction_date` for all 737 transactions. The 28 rows, and what reads them downstream,
  take their Eastern date.
- Good: no new macro, and the expression is already in the two-warehouse form.
- Bad / accepted cost: the pytest runs dbt three times in subprocesses, which adds seconds
  to the test suite.
- Bad / accepted cost: only this model is held. Another model that casts an instant to a
  plain `timestamp` would have the same bug. Grepping `::timestamp\b|as timestamp\)` over
  models, macros and tests on 2026-10-23 found no other.
