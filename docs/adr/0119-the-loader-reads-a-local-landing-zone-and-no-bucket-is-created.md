# 0119. The loader reads a local landing zone by free load jobs, and no bucket is created

- Status: accepted
- Date: 2026-11-02
- Spec: [0140-production-raw-loader](../specs/0140-production-raw-loader/design.md) · Issue: #140

## Context

#140's text says "a bucket is where captures would land". That came from the spike's external-table
measurement: read models from a native table, not from a bucket (C13). It does not show a loader
needs a bucket. A load job takes a local file, and is free (C12).

A bucket holding what the landing zone holds would put whole captures, with members' names and
account ids, in the cloud for the first time: ADR 0054's question, which went the other way. And no
sub-project 4 issue yet says where ingestion runs. The roadmap names Cloud Scheduler and Cloud Run.

## Decision drivers

- No billed service without a need; a bucket's price is small but not nothing.
- Nothing that names a member leaves the machine (rule 2, ADR 0054).
- Do not decide sub-project 4 here, and do not block it.

## Considered options

1. **Local landing zone, direct load jobs, no bucket.** Free. The owner's machine runs the upload,
   by hand until sub-project 4.
2. **A private bucket of the uploaded rows**, projected and checked, loaded from there. About 0.02
   USD/GiB-month past 5 GiB in a free-tier region: pennies. Keeps rows nobody needs twice.
3. **A private bucket of whole captures**, the production landing zone. 12 GB: about 0.14 USD a
   month. Needs ADR 0054 reversed for member data, and `LandingZone` ported from a filesystem.

## Decision

Chosen by the owner on 2026-11-02, at the spec's walkthrough: **option 1**.

Option 2 buys nothing today: its rows are rebuilt from the landing zone for free. Option 3 is the
decision sub-project 4 has to make along with where capture runs, and needs that answer first. The
loader's boundary is `LandingZone`, so if captures move the loader reads them at that seam.

## Consequences

- Good: zero new cost, no new service, no new place member data could be.
- Bad / accepted cost: the upload runs where the landing zone is, so this does not yet make the
  pipeline run without the owner's machine. Cloud Run has no durable disk, so sub-project 4 must
  answer where captures live.
- Follow-ups: sub-project 4 decides that, and whether whole captures may be in the cloud.
