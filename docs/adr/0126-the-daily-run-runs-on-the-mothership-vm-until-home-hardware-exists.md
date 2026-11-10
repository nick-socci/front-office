# 0126. The daily run runs on the `mothership` VM until home hardware exists

- Status: proposed (the owner's decision: it reverses ADR 0054's premise for captures, and AGENTS.md puts credentials and the NAS backup outside an agent's choice)
- Date: 2026-11-10
- Spec: [0216-where-the-daily-run-runs](../specs/0216-where-the-daily-run-runs/design.md) · Issue: #216
- Amends: [0121](0121-the-daily-run-runs-on-the-nas-and-the-landing-zone-moves-there.md), [0054](0054-only-endpoints-without-member-data-are-uploaded-and-whole.md), [0124](0124-the-run-reads-its-credentials-from-files-on-the-nas.md), [0125](0125-the-landing-zone-joins-the-nas-backup-to-its-external-drive.md)

## Context

ADR 0121 chose the NAS as the host. Task 1 of the spec found a DS220+ with 1,753 MB usable and 497
MB available (spec C15 had assumed 4 to 6 GB), and Dagster's daemon and UI alone need 882 MB
(R6.2 fired, spec Amendments 2026-11-07). The owner intends to buy a home server before the 2027
season, which would also take over the NAS's services. That purchase is open, and the 2027 first
week cannot be redone (#66, #69).

The owner's second Always Free Ampere A1 VM, `mothership` (Oracle, `us-ashburn-1`, 2 OCPU, 12 GB,
arm64, 96 GB disk), is up and general purpose. The pre-spike on it (spec Amendments 2026-11-09 and
2026-11-10) measured and tested:

- A daily run with Dagster's daemon and UI, and a full `dbt build` into `_216`, peaks at 1,180 MB
  PSS on a host with about 11 GB free, with no swap. 574 passed, 16.16 GB billed, and all 80
  relations equal the laptop's DuckDB build, exactly.
- ESPN answered an authenticated league call (settings and matchups) from the VM's address.
  Teams and rosters, a full day's volume, repeated calls and in-season behaviour are untested.
- SSH is reachable only over Tailscale, the VM starts no connection on the tailnet, and the public
  address answers ICMP only. The serial-console path was tested.

Whole captures hold members' names and account ids. ADR 0054 rests on their having lived only on the
owner's machine and the NAS, and R2.3 requires an accepted ADR before any capture leaves the home.

## Decision drivers

- A host that runs the daily pipeline from opening day 2027, whatever the laptop is doing (R1.1,
  R1.2), without waiting on a purchase.
- Members' data: keep what leaves the home to the least, and say so (ADR 0054, R2.3).
- Captures on a second device (R5.3): ESPN data cannot be refetched after the league rolls over.
- No new cost (R1.4), and the least to undo when the home server arrives.

## Considered options

1. **`mothership` runs the daily run, holds the production landing zone on its local disk, and
   is replaced by the home server when it exists.**
2. **The laptop on a timer** (spec option a). Free, nothing to build, and captures stay home, but it
   runs only when the laptop is awake at the hour (C11), and those are the days that matter.
3. **Wait for the home server and run by hand until then.** Keeps captures home, but a missed first
   week cannot be fetched again.
4. **The NAS without the daemon**, a one-shot run (spec option c on the NAS). At 497 MB available
   it is at the limit, makes ADR 0122 moot, and swaps already.

## Decision

Chosen: **option 1**, as the owner decided. It is the only option that runs every day without
the laptop and without new hardware or cost, and the pre-spike shows it fits (1.2 GB of about 11 GB)
and that ESPN answers it. The home server then replaces it by a superseding ADR, which moves the
writer home and removes the Oracle copy. Until then:

- **Where things are.** The production landing zone is on `mothership`'s local disk, never on a
  network mount (ADR 0014 publishes a capture by one rename). Dagster's daemon, the CLI and the
  BigQuery build run there in containers (ADRs 0122, 0123 stand). The host is a general-purpose VM
  that also takes the owner's other services, so the run's containers carry their own memory limit.
- **Whole captures leave the home (amends ADR 0054).** Whole ESPN captures, with members' names and
  account ids, are stored on `mothership`, and nowhere else outside the home. The upload to BigQuery
  is unchanged (projections for teams and transactions, the rest whole). The controls: SSH only over
  the tailnet, no public port, no outbound connection on the tailnet from the VM, one unix user for
  the run, and its credential files readable by that user only. Oracle block volumes are encrypted at
  rest by default; confirming that for this boot volume is a follow-up.
- **Credentials (amends ADR 0124).** The ESPN `.env` and the BigQuery service account key are files
  on `mothership` instead of the NAS, read-only to the run, never in an image or a log line. Rule 3
  is worded accordingly (spec task 5).
- **Backup (amends ADR 0125).** The NAS's external-drive job no longer covers the primary copy. The
  second device in the home is a pull of the landing zone onto the NAS (and the laptop), started by
  the NAS or the laptop, since `mothership` starts nothing on the tailnet. R5.3's gap is then the
  pull's interval. The NAS's existing job carries the pulled copy to the external drive.

## Consequences

- Good: runs from opening day without a purchase, at no cost, with measured headroom, and Dagster
  runs as ADR 0122 decided.
- Good: nothing here is hard to undo. The home server replaces the host, and the landing zone moves
  by `rsync --archive`, then the Oracle copy goes.
- Bad / accepted cost: whole captures of league members' data are held on a third party's machine
  until then, under the controls above. The owner is the only one with access.
- Bad / accepted cost: ESPN may treat the address differently in season, after repeated calls or for
  rosters and teams. The first daily runs are watched, and if the address is refused, the run falls
  back to the laptop (option 2) until the home server is in place.
- Bad / accepted cost: `mothership` shares the tenancy's Always Free allowance with `hermes`, and
  the tenancy's five volume backups are mostly used (`hermes` holds three). A boot-volume backup of
  the production host needs a slot or a smaller retention on `hermes`.
- Follow-ups: #218 builds the pull to the NAS (a tailnet grant for the NAS to reach `mothership`'s
  SSH, with a read-only account), moves the writer here, and tests one restore. #218 also confirms
  teams and rosters from this address on its first run, and checks the boot volume's encryption.
  When the home server is chosen, a superseding ADR moves the writer home. Once this ADR is
  accepted, ADRs 0121, 0054, 0124 and 0125 link it in their Status lines.
