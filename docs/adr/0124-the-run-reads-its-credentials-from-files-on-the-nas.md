# 0124. The run reads the ESPN cookies and a BigQuery service account key from files on the NAS

- Status: accepted (the owner decided at the 2026-11-05 walkthrough; AGENTS.md puts credentials outside an agent's choice)
- Date: 2026-11-04
- Spec: [0216-where-the-daily-run-runs](../specs/0216-where-the-daily-run-runs/design.md) · Issue: #216

## Context

Today the ESPN cookies are in the laptop's `.env`, and `espn/client.py` is the only module that
reads them. BigQuery is reached with the owner's own login, which Google's client finds in its
own credential store (`google.auth.default()` in `bigquery.py`), outside `.env`. AGENTS.md's rule
3 says "Credentials live only in `.env`". The BigQuery login has never been there, so the rule is
read today as the ESPN credentials. A key file on the NAS would make that reading permanent, and
the rule should say so (design review F1).

On the NAS (ADR 0121) there is no one logged in, and a NAS has no metadata server, so the
identity Cloud Run or a VM would get without a key is not available. Secret Manager's free tier
would hold both secrets (spec C3), but reading it needs a Google credential on the NAS first.

The run needs, from BigQuery: jobs in the project; `create_dataset` for `raw`, which runs even
when it exists (`bigquery.py`); the project's billing info, which the upload checks; and the
datasets dbt creates for a build or a suffixed one. A query alone does not show those (F4).

## Decision drivers

- Nothing in an image, a log line or the repository (rule 3's purpose).
- The BigQuery identity can do no more than the run does (spec R5.2).
- One place to replace a cookie when ESPN expires it.

## Considered options

1. **Files on a NAS volume mounted read-only**: `.env` as today; a key for a new service account,
   named by `GOOGLE_APPLICATION_CREDENTIALS`. Starting roles: BigQuery User on the project (jobs,
   and creating the datasets the upload and dbt need), and whatever the billing check needs. The
   spec's task 4 adds only what a refused step proves is missing.
2. **The owner's own login on the NAS** (a copied application-default refresh token): no new
   identity, but it carries everything the owner's account can do.
3. **Secret Manager**, read with option 1's key: the same key on the NAS, one more service.

## Decision

Chosen by the owner on 2026-11-05, at the spec's walkthrough: **option 1**, as recommended,
"for now". The owner intends to set up a secret manager for everything they work on, not this
project alone. When it exists, the run reads both secrets from it, and this record is superseded.

The key is replaced each off-season, and rule 3 is reworded in
AGENTS.md: "The ESPN credentials live only in `.env`, and `espn/client.py` is the only module that
reads them. Google credentials are found by Google's client (the owner's login, or a key file on
the NAS named by `GOOGLE_APPLICATION_CREDENTIALS`). No credential ever reaches the repository, an
image, a landing file, a sidecar, a log line or a test."

Option 2 puts a credential for the owner's whole Google account on a NAS. Option 3 still needs a
key on the NAS, so it adds a service without removing the file.

## Consequences

- Good: the BigQuery identity reaches only this project, with the roles a real run proved it needs.
- Good: rule 3 says what is true of the BigQuery login today.
- Bad / accepted cost: a long-lived key, which Google discourages. It is mitigated by its narrow
  roles and the yearly replacement, and it is never in the image.
- Bad / accepted cost: BigQuery User lets the account create datasets in the project. The build
  needs that for suffixed datasets.
- Follow-ups: the spec's task 3 creates the account; task 4 fixes its roles. #218 makes it
  permanent. #219 alerts on expired cookies. AGENTS.md's rule 3 is reworded when this is accepted.
- Revisit: when the owner's secret manager for all their projects exists.
