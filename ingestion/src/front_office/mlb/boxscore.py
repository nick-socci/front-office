"""MLB Stats API: per-game boxscores.

Work items come from the landed schedule, so a boxscore backfill never needs the network
to decide what to fetch. Two rules govern re-fetching:

* A game is only worth fetching once it has been played.
* A played game is NOT immutable immediately. MLB's official scorers revise hits, errors
  and occasionally earned runs for days afterwards, and ESPN applies those corrections to
  fantasy results. So a game stays refetchable until it is settled: some capture is at
  least the settle window (7 days) later than the game's first capture taken after its
  last scheduled start.

The settle window runs from that first capture, not from the game's date. A boxscore is
only fetched for a game the schedule shows as played, so the first capture after the last
scheduled start is itself evidence the game was over by then; a capture from before that
start cannot have seen a suspended game finish. Everything is a comparison of `fetched_at`
stamps, so the decision needs no dates, timezones or clock, and the audit calls the same
functions (`first_final`, `is_settled`). Why: ADRs 0019 and 0020.

The payload itself carries no gamePk -- the identifier lives in the URL path -- so the
game_pk is recorded in the request metadata, which is what staging reads it from.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from front_office.http_client import AuthExpired, HttpClient
from front_office.landing import LandingCollision, LandingZone

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
    # Latest gameDate over every entry of this game in the newest schedule, as a UTC
    # instant; None when any entry's gameDate is unreadable (see games_from_landed_schedule).
    last_start: dt.datetime | None = None


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

    Each game also gets `last_start`: the latest `gameDate` over ALL its entries, played
    or not, since a session that is only scheduled still means the game is not over. If
    any entry's `gameDate` is missing or unreadable it might be the latest, so the game
    gets no `last_start` (and a warning): it is still fetched, but never settles.
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
    starts: dict[int, dt.datetime] = {}
    unreadable: set[int] = set()
    for day in newest.payload.get("dates", []):
        for raw in day.get("games", []):
            _note_start(raw, starts, unreadable)
            scheduled = _to_scheduled_game(raw)
            if scheduled is None:
                continue
            incumbent = best.get(scheduled.game_pk)
            if incumbent is None or (
                incumbent.detailed_state in NOT_PLAYED
                and scheduled.detailed_state not in NOT_PLAYED
            ):
                best[scheduled.game_pk] = scheduled
    games = []
    for pk in sorted(best):
        if best[pk].detailed_state in NOT_PLAYED:
            continue
        if pk in unreadable:
            logger.warning("game_pk=%s has an unreadable gameDate; it will never settle", pk)
            games.append(best[pk])
        else:
            games.append(replace(best[pk], last_start=starts.get(pk)))
    return games


def _note_start(raw: dict[str, Any], starts: dict[int, dt.datetime], unreadable: set[int]) -> None:
    """Fold one schedule entry's gameDate into the latest start seen for its game."""
    try:
        pk = int(raw["gamePk"])
    except (KeyError, TypeError, ValueError):
        return
    try:
        start = dt.datetime.fromisoformat(raw["gameDate"])
        if start.utcoffset() is None:
            raise ValueError("gameDate has no offset")
    except (KeyError, TypeError, ValueError):
        unreadable.add(pk)
        return
    start = start.astimezone(dt.UTC)
    if pk not in starts or start > starts[pk]:
        starts[pk] = start


def parse_stamp(fetched_at: str) -> dt.datetime:
    """A capture's compact UTC stamp (20260926T162307Z) as an aware instant."""
    return dt.datetime.strptime(fetched_at, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)


def first_final(
    stamps: Iterable[dt.datetime], last_start: dt.datetime | None
) -> dt.datetime | None:
    """The earliest capture taken after the game's last scheduled start, or None.

    A boxscore is only fetched for a game the schedule shows as played, so a capture
    later than the game's last session start is the first one that can have seen it
    finished. Strictly later: a capture at the start instant has seen nothing.
    """
    if last_start is None:
        return None
    later = [stamp for stamp in list(stamps) if stamp > last_start]
    return min(later) if later else None


def is_settled(
    stamps: Iterable[dt.datetime],
    last_start: dt.datetime | None,
    settle_window: dt.timedelta = SETTLE_WINDOW,
) -> bool:
    """True when some capture is at least `settle_window` later than the first-final one.

    Inclusive: a capture exactly `settle_window` later settles the game.
    """
    captured = list(stamps)
    first = first_final(captured, last_start)
    if first is None:
        return False
    return any(stamp >= first + settle_window for stamp in captured)


def capture_stamps(zone: LandingZone, *, season: int) -> dict[int, list[dt.datetime]]:
    """When each game's committed boxscore captures were taken, by game_pk.

    Sidecars only: no payload is read. Only captures under this season's partition count,
    and `committed` already leaves out debris. A stamp that does not parse is ignored.
    """
    stamps: dict[int, list[dt.datetime]] = {}
    for capture in zone.committed(source=SOURCE, endpoint=ENDPOINT):
        partitions = capture.meta.get("partitions", {})
        if str(partitions.get("season")) != str(season):
            continue
        try:
            game_pk = int(partitions["game_pk"])
            stamp = parse_stamp(str(capture.meta["fetched_at"]))
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "ignoring boxscore capture with an unreadable sidecar: %s", capture.directory
            )
            continue
        stamps.setdefault(game_pk, []).append(stamp)
    return stamps


def needs_fetch(
    scheduled: ScheduledGame, stamps: Iterable[dt.datetime], *, refresh: bool = False
) -> bool:
    """True when this game's boxscore should be fetched (again): unless it is settled.

    A game with no captures is simply not settled, so "never landed" needs no branch.
    """
    return refresh or not is_settled(stamps, scheduled.last_start)


def backfill_boxscores(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    fetched_at: str,
    limit: int | None = None,
    refresh: bool = False,
) -> BackfillSummary:
    """Fetch and land boxscores for a season. One game's failure never stops the run;
    rejected credentials and a landing collision do."""
    stamps = capture_stamps(zone, season=season)
    summary = BackfillSummary()
    for scheduled in games_from_landed_schedule(zone, season=season):
        if limit is not None and summary.fetched >= limit:
            break
        if not needs_fetch(scheduled, stamps.get(scheduled.game_pk, []), refresh=refresh):
            summary.skipped += 1
            continue
        try:
            _fetch_one(zone=zone, client=client, scheduled=scheduled, fetched_at=fetched_at)
        except (AuthExpired, LandingCollision):
            # Rejected credentials fail every later request; a collision means two
            # writers or a clock fault. Either way, stop rather than count one failure.
            raise
        except Exception:
            logger.exception("boxscore fetch failed for game_pk=%s", scheduled.game_pk)
            summary.failed += 1
            summary.failed_game_pks.append(scheduled.game_pk)
        else:
            # Within this run each game is visited once, so this changes no decision; it
            # keeps `stamps` a faithful picture of what is landed.
            stamps.setdefault(scheduled.game_pk, []).append(parse_stamp(fetched_at))
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
