# 0135. The daily run has its own Google service account, and the spike account is retired

- Status: proposed (the owner's: credentials)
- Date: 2026-11-17
- Spec: [0218-schedule-the-daily-run](../specs/0218-schedule-the-daily-run/design.md) · Issue: #218

## Context

ADR 0124 starts the run's service account at BigQuery User on the project and adds what a refused
step proves. Spec 0216's spike created `fo-spike216`; its key is `fo-key-2026-11-10.json` in
`ubuntu`'s home. On 2026-11-17, at the owner's instruction, #217 gave it `WRITER` on `main`,
`staging`, `intermediate`, `marts` and `reconciliation`, beside BigQuery User and `WRITER` on `raw`,
after the build was refused creating tables and routines (C6). So the production run would use an
account named for a spike, whose roles were added in steps on the day. AGENTS.md leaves credentials to
the owner.

## Decision drivers

- No more access than the run uses (spec 0216 R5.2).
- The account and its key say what they are for, and the spike's can be removed.
- Little work for the owner.

## Considered options

1. **A new service account for the daily run**, with the grants of C6 written down once, a new key
   under `front-office`, and the spike account and key retired once the run no longer uses them.
2. **Keep `fo-spike216`**, move its key to `front-office`.
3. **The owner's own login** (ADR 0124's rejected option 2).

## Decision

Chosen by the owner on 2026-11-17, at the spec's walkthrough: **option 1**, as recommended. The grants are known and few: BigQuery User on the project, and `WRITER`
(data editor) on `raw` and the five model datasets, by dataset access entries (`add-iam-policy-binding`
needs an allowlist in this project: #217), and no other role and no access to another project or the
owner's other Google data. The owner creates the account and the key and places the key in
`front-office`'s `secrets/` (mode 0400); an agent does not create, copy, rotate or delete a credential.
The key is replaced each off-season (ADR 0124), by the runbook's steps. Retiring `fo-spike216` is the
owner's, once a `daily` has run on the new account.

## Consequences

- Good: a named account with written-down grants; the spike's key leaves `ubuntu`'s home.
- Bad / accepted cost: one more account and key for the owner, and a second key's lifetime to track.
- Follow-ups: spec task 5 (the owner creates the account, grants and key); task 6 shows the run
  using it and a scan showing no key field elsewhere. Revisit when the owner's secret manager exists
  (ADR 0124).
