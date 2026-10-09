# 0036. The player list is a season-level snapshot, landed on every MLB run

- Status: proposed
- Date: 2026-10-09
- Spec: [0060-player-dimension-by-mlb-id](../specs/0060-player-dimension-by-mlb-id/design.md) · Issue: #60

## Context

ADR 0035 lands MLB's season player list. The list changes during a season: a call-up
appears in it, and a position or a name can be revised. It is one public request of
about 1.5 MB. `backfill mlb` lands the schedule on every run, as a snapshot, and
fetches boxscores until they settle; ADR 0024 lands ESPN's pro schedule on every run
and does not let its failure stop the league's captures.

## Decision drivers

- A player who debuts in June should be in the dimension without anyone acting.
- Ingestion fetches and saves; it never reads data to decide what to fetch.
- One policy for season-level captures.
- A failure of an optional capture must not cost the captures numbers depend on.

## Considered options

1. **A snapshot on every `backfill mlb` run**, between the schedule and the boxscores;
   `--only players` lands it alone.
2. **Once per season**, refetched only with `--refresh`.
3. **Only when a boxscore names a player the newest list lacks.**

For a failed request: (a) stop the run, as a failed schedule does; (b) report it, fetch
the boxscores, and exit 1 at the end.

## Decision

Chosen by the owner on 2026-10-09: **option 1, with (b)**.

The capture is `mlb/players/season=<year>/fetched_at=<stamp>/`, fetched with the public
MLB client. Staging keeps, per season and player, the newest capture that lists him.
`front-office audit` warns when a season has a schedule and no player list.

Option 2 is stale from the first call-up until someone remembers. Option 3 makes the
fetcher interpret boxscores. Stopping the run on a failed list would hold back
boxscores, which every number rests on, for a capture none rests on.

## Consequences

- Good: the same shape and policy as the schedule and the pro schedule; nothing new for
  the loader, and the isolation check already selects MLB folders by season.
- Good: a failed list is loud (exit 1, an audit warning) and costs no boxscore.
- Bad / accepted cost: about 1.5 MB a run, some 280 MB over a season of daily runs.
- Bad / accepted cost: a run that fetched every boxscore still exits 1 if the list
  failed, so a scheduler must tell the two apart from the output.
- Follow-ups: source freshness for it is declared with the others in #13.
