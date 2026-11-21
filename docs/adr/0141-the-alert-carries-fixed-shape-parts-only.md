# 0141. The alert carries fixed-shape parts only

- Status: accepted
- Date: 2026-11-20
- Spec: [0219-alert-on-the-daily-run](../specs/0219-alert-on-the-daily-run/design.md) · Issue: #219

## Context

The report goes to healthchecks.io and to the owner's email (ADR 0139), outside the host. The 0217
filter (`cli.ALLOWLIST` plus `front_office.privacy`) decides what may enter Dagster's log on the
host. It keeps `landed … -> <path>` lines, and a real ESPN path names the private league's id
(C16). It also keeps `no settings captured for season N, league <id>`. dbt's error for a tie
carries the partition keys' values (C15), and any exception's message can hold anything. The
issue asks for the step, the error's first line, and where to look, never a credential or a
member's data.

## Decision drivers

- Nothing private leaves the host: no credential, no member's data, no league id, no path.
- The report still says enough to act on without opening the UI for the common failures.

## Considered options

1. **Fixed-shape parts only.** Names, keys, statuses, exit codes, ages, dbt unique ids, exception
   class names, and stderr lines that fully match a narrower alert allowlist with no path and no
   league in it; the HTTP give-up line is rewritten without its URL. No message text.
2. **The 0217-filtered tail and the exception's first line**, as Dagster's log shows them.
3. **No detail**: "daily failed, see the UI".

## Decision

Chosen by the owner on 2026-11-20: **option 1**, as recommended. Option 2 sends the league's id in every `landed` line, and a tie's key
values. Option 3 hides even the expired-cookie line, which says the remedy itself.

## Consequences

- Good: what can leave the host is a closed list, and a test can hold it.
- Bad / accepted cost: a failure whose explanation is only in a message (a new exception, dbt's
  compile error) shows as its step and class. The UI link is the way in.
- Follow-ups: a new CLI line wanted in alerts is added to the alert patterns, with its test.
