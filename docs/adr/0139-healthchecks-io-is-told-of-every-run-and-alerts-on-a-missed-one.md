# 0139. healthchecks.io is told of every run, and alerts on a missed one

- Status: accepted
- Date: 2026-11-20
- Spec: [0219-alert-on-the-daily-run](../specs/0219-alert-on-the-daily-run/design.md) · Issue: #219

## Context

The daily run tells nobody how it went. Spec 0216 accepted a home host's outages because a missed
run would be alerted (R1.3), and nothing on the host can say that the host is down. A failed fetch
leaves the run `SUCCESS` (ADR 0129; spec C6), so an alert on failed runs alone would miss the
most common failure, expired cookies. The issue asks for $0 if possible, and the repository is
public.

## Decision drivers

- A run that never happens is reported, whatever stopped it.
- $0, and a secret on the host that can do as little harm as possible.
- No alert is published.
- A good run after a bad one says so.

## Considered options

1. **healthchecks.io**: one check per job, with the job's cron, New York time and a grace time. A
   Dagster sensor pings at the end of each run, with a report as the body (`/fail` on failure).
   Its email is sent on DOWN, on UP, and when no ping arrives by the grace (spec C1 to C4).
2. **Email from Dagster over SMTP** (`make_email_on_run_failure_sensor`), with a Gmail app
   password on the host.
3. **ntfy.sh push**: on the free server, a topic name is the only protection (C5).
4. **A GitHub issue per failure**, opened with a token.

## Decision

Chosen by the owner on 2026-11-20: **option 1**, as recommended. It is the only option that
reports a missed run. Its key can only mark two checks up or down. Its UP email is the recovery
message, with nothing to build.

## Consequences

- Good: a missed run is known by 08:30 ET (tick plus 2 h 30 min), before 0216 R1.2's 09:00. Any
  breakage of the alerting itself (the sensor, the key, the network) shows up as a missed run.
- Bad / accepted cost: healthchecks.io emails on a change of state only, so a second failure while
  a check is down sends no email. Each report stays in the check's log (100 entries). The reports
  go to a third party, which is why ADR 0141 limits what they hold.
- Follow-ups: the owner creates the account, the checks and the key (runbook). A push to a phone
  is a healthchecks.io integration (ntfy, Pushover) if ever wanted.
