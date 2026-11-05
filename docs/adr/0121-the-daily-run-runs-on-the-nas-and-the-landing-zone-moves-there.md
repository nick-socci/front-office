# 0121. The daily run runs on the NAS in a container, and the landing zone moves there

- Status: proposed
- Date: 2026-11-04
- Spec: [0216-where-the-daily-run-runs](../specs/0216-where-the-daily-run-runs/design.md) · Issue: #216
- Amends: [0119](0119-the-loader-reads-a-local-landing-zone-and-no-bucket-is-created.md)

## Context

Nothing runs the pipeline on a schedule, and the 2027 season needs a run every morning by 09:00
Eastern (owner, 2026-11-04). The landing zone and every run live on the owner's laptop, which is
"on the majority of time but it is a laptop" (owner) and suspends when idle (spec C11). ADR 0119
left "where captures live" to this sub-project. Captures hold members' data, which ADR 0054 keeps
on the owner's machine and the NAS. The owner's Synology NAS runs containers and has 4 to 6 GB of
memory (C15).

## Decision drivers

- A run every morning whatever the laptop is doing.
- Whole captures stay in the home (ADR 0054).
- Room for Dagster's daemon and UI (0.85 GB idle, C8) plus a run.
- GCP cost near zero (the project's 5 USD a month budget).

## Considered options

1. **The NAS, in a container**: always on, in the home, 0 USD, 4 to 6 GB.
2. **The laptop on a systemd timer**: 0 USD, nothing to build; misses when closed or away.
3. **Cloud Scheduler and a Cloud Run job, with a private bucket as the landing zone**: about
   0.95 USD a month (C2, C3); reverses ADR 0054; ports `LandingZone` to object storage, which has
   no rename for ADR 0014's publish.
4. **A free e2-micro VM**: 0 USD in 2027 (C1); 1 GB of memory, which the daemon and a run do not
   fit (C5, C7, C8); reverses ADR 0054.

## Decision

Chosen by the owner on 2026-11-05, at the spec's walkthrough: **option 1**, as recommended,
with the writer moving to the NAS during this spec's build (task 3).

It is the only option that meets the morning deadline without the laptop and without reversing
ADR 0054, and it has the memory for Dagster as a real deployment. Option 3 is the roadmap's, and
would redesign the capture protocol for hosting that costs about a dollar a month. Option 4
answers the owner's question about a free VM: measured, it does not fit Dagster.

The NAS becomes the one writer of the production landing zone. The laptop keeps a copy pulled
from it, for development. The owner asked whether the laptop needs a copy at all, since it can
reach the NAS's files. Reading them over NFS, mounted read-only, would need no copy and could
never write to production. But every full DuckDB build would read the 12 GB of captures over
Wi-Fi, there would be no build away from home, and the backup would lose its second device (ADR
0125). The owner chose the pulled copy (2026-11-05). The loader still reads a local landing zone (ADR 0119), local now to
the NAS.

## Consequences

- Good: 0 USD; no member data in the cloud beyond what ADR 0054 and its amendments send; no change
  to the capture protocol.
- Good: the laptop is free to sleep, travel and run development builds.
- Bad / accepted cost: the run depends on the home's power and internet, as the laptop does. A
  missed morning catches up on the next run (ADRs 0018, 0019).
- Bad / accepted cost: the NAS, today the backup target, holds the primary copy (ADR 0125).
- Bad / accepted cost: the BigQuery credential is a key file, since a NAS has no workload identity
  (ADR 0124).
- Follow-ups: spec 0216's task 4 measures the NAS before #217. If its memory falls short (R6.2),
  this returns to the owner. ADR 0119's status gains "amended by 0121" when this is accepted.
