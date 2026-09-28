"""MLB Stats API: per-game boxscores.

Work items come from the landed schedule, so a boxscore backfill never needs the network
to decide what to fetch. Two rules govern re-fetching:

* A game is only worth fetching once it has been played.
* A played game is NOT immutable immediately. MLB's official scorers revise hits, errors
  and occasionally earned runs for days afterwards, and ESPN applies those corrections to
  fantasy results. So a game stays refetchable for a settle window (7 days) and is
  treated as final after that.

The payload itself carries no gamePk -- the identifier lives in the URL path -- so the
game_pk is recorded in the request metadata, which is what staging reads it from.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from front_office.http_client import HttpClient
from front_office.landing import LandingZone

logger = logging.getLogger(__name__)

BASE_URL = "https://statsapi.mlb.com/api/v1"
SOURCE = "mlb"
ENDPOINT = "boxscore"
SCHEDULE_ENDPOINT = "schedule"
SETTLE_WINDOW = dt.timedelta(days=7)
PLAYED_STATE = "Final"
POSTPONED = "Postponed"
# MLB files these under abstractGameState "Final" too: the game is over, but was never
# played. A cancelled game still has a boxscore (rosters, no stats); it is not wanted.
NOT_PLAYED = frozenset({POSTPONED, "Cancelled"})


@dataclass(frozen=True)
class ScheduledGame:
    """A game worth fetching a boxscore for."""

    game_pk: int
    season: int
    official_date: dt.date
    state: str
    detailed_state: str


@dataclass
class BackfillSummary:
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    failed_game_pks: list[int] = field(default_factory=list)


def games_from_landed_schedule(zone: LandingZone, *, season: int) -> list[ScheduledGame]:
    """Played regular-season games from the newest landed schedule for a season.

    Postponed entries are dropped in favour of the game that was actually played: the
    two share a game_pk and only the played one has a boxscore. This mirrors the
    tie-break in stg_mlb__games. A postponed game with no makeup, or a cancelled game,
    was never played, so it is dropped too rather than fetched on every run.
    """
    responses = [
        landed
        for landed in zone.iter_landed(source=SOURCE, endpoint=SCHEDULE_ENDPOINT)
        if str(landed.meta.get("partitions", {}).get("season")) == str(season)
    ]
    if not responses:
        raise FileNotFoundError(
            f"no landed {SOURCE}/{SCHEDULE_ENDPOINT} response for {season}; "
            "run `front-office backfill mlb --only schedule` first"
        )
    newest = max(responses, key=lambda landed: str(landed.meta.get("fetched_at", "")))

    best: dict[int, ScheduledGame] = {}
    for day in newest.payload.get("dates", []):
        for raw in day.get("games", []):
            scheduled = _to_scheduled_game(raw)
            if scheduled is None:
                continue
            incumbent = best.get(scheduled.game_pk)
            if incumbent is None or (
                incumbent.detailed_state in NOT_PLAYED
                and scheduled.detailed_state not in NOT_PLAYED
            ):
                best[scheduled.game_pk] = scheduled
    return [best[pk] for pk in sorted(best) if best[pk].detailed_state not in NOT_PLAYED]


def needs_fetch(
    scheduled: ScheduledGame,
    zone: LandingZone,
    *,
    today: dt.date,
    settle_window: dt.timedelta = SETTLE_WINDOW,
    refresh: bool = False,
) -> bool:
    """True when this game's boxscore should be fetched (again)."""
    if refresh:
        return True
    if not _has_landed(zone, scheduled):
        return True
    # Inclusive: a game exactly `settle_window` old is still refetched. One extra
    # fetch is cheaper than freezing a late stat correction out of the warehouse.
    return today - scheduled.official_date <= settle_window


def backfill_boxscores(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    fetched_at: str,
    today: dt.date | None = None,
    limit: int | None = None,
    refresh: bool = False,
) -> BackfillSummary:
    """Fetch and land boxscores for a season. One game's failure never stops the run."""
    today = today or dt.datetime.now(dt.UTC).date()
    summary = BackfillSummary()
    for scheduled in games_from_landed_schedule(zone, season=season):
        if limit is not None and summary.fetched >= limit:
            break
        if not needs_fetch(scheduled, zone, today=today, refresh=refresh):
            summary.skipped += 1
            continue
        try:
            _fetch_one(zone=zone, client=client, scheduled=scheduled, fetched_at=fetched_at)
        except Exception:
            logger.exception("boxscore fetch failed for game_pk=%s", scheduled.game_pk)
            summary.failed += 1
            summary.failed_game_pks.append(scheduled.game_pk)
        else:
            summary.fetched += 1
    return summary


def _fetch_one(
    *, zone: LandingZone, client: HttpClient, scheduled: ScheduledGame, fetched_at: str
) -> None:
    response = client.get(f"{BASE_URL}/game/{scheduled.game_pk}/boxscore")
    zone.write(
        source=SOURCE,
        endpoint=ENDPOINT,
        partitions={"season": scheduled.season, "game_pk": scheduled.game_pk},
        name=f"fetched_at={fetched_at}",
        payload=response.json(),
        # gamePk is a path segment, not a query param, but it is what identifies this
        # response: recording it here is how staging recovers the game_pk.
        request={"url": str(response.request.url), "params": {"gamePk": scheduled.game_pk}},
        fetched_at=fetched_at,
    )


def _has_landed(zone: LandingZone, scheduled: ScheduledGame) -> bool:
    directory = zone.path_for(
        source=SOURCE,
        endpoint=ENDPOINT,
        partitions={"season": scheduled.season, "game_pk": scheduled.game_pk},
        name="unused",
    ).parent
    if not directory.exists():
        return False
    return any(not path.name.endswith(".meta.json") for path in directory.glob("*.json"))


def _to_scheduled_game(raw: dict[str, Any]) -> ScheduledGame | None:
    status = raw.get("status", {})
    if status.get("abstractGameState") != PLAYED_STATE:
        return None
    try:
        return ScheduledGame(
            game_pk=int(raw["gamePk"]),
            season=int(raw["season"]),
            official_date=dt.date.fromisoformat(raw["officialDate"]),
            state=status["abstractGameState"],
            detailed_state=status.get("detailedState", ""),
        )
    except (KeyError, TypeError, ValueError):
        logger.warning("skipping unparseable schedule entry: %s", raw.get("gamePk"))
        return None
