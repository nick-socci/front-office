"""ESPN's pro schedule: every pro game, with its start time and scoring period.

This is ESPN's game-level season resource, not a league's: it needs no league and no
credentials, and it is the first ESPN capture with no `league_id` partition (ADR 0024).
A snapshot endpoint -- games are postponed and rescheduled -- so each run lands a new copy.
"""

from __future__ import annotations

from pathlib import Path

from front_office.espn.client import game_url
from front_office.http_client import HttpClient
from front_office.landing import LandingZone

SOURCE = "espn"
ENDPOINT = "pro_schedule"
VIEW = "proTeamSchedules_wl"


class ProScheduleMalformed(ValueError):
    """The response is not a pro schedule (an error page, say), so nothing was landed."""


def backfill_pro_schedule(
    *, zone: LandingZone, client: HttpClient, season: int, fetched_at: str
) -> Path:
    """Land the season's pro schedule unchanged. Returns the capture path."""
    response = client.get(game_url(season), params={"view": VIEW})
    try:
        payload = response.json()
    except ValueError:
        raise ProScheduleMalformed("the response is not JSON; nothing landed") from None
    # The only look inside the payload: enough to refuse an error page (R1.6), not to
    # interpret it. Ingestion otherwise lands what ESPN sent.
    if not isinstance(payload, dict):
        raise ProScheduleMalformed(
            f"the response is a {type(payload).__name__}, not an object; nothing landed"
        )
    settings = payload.get("settings")
    if not isinstance(settings, dict):
        raise ProScheduleMalformed("the response has no 'settings' object; nothing landed")
    if not isinstance(settings.get("proTeams"), list):
        raise ProScheduleMalformed("the response has no 'settings.proTeams' list; nothing landed")
    return zone.write(
        source=SOURCE,
        endpoint=ENDPOINT,
        partitions={"season": season},
        name=f"fetched_at={fetched_at}",
        payload=payload,
        request={"url": str(response.request.url), "params": {"view": VIEW}},
        fetched_at=fetched_at,
    )
