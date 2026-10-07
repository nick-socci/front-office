"""ESPN rosters, one snapshot per scoring period.

A scoring period is one day of fantasy scoring. Its roster is settled once the period
ends, and ESPN keeps serving historical periods -- verified by spike before this design
was chosen.

"Settled" is decided against the league's own status, not against the period number:
latestScoringPeriod is the period currently in progress, so only periods strictly before
it are final. Treating `period <= latest` as settled would freeze a day whose lineup can
still change.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from front_office.espn.client import league_url
from front_office.http_client import AuthExpired, HttpClient
from front_office.landing import LandingCollision, LandingZone

logger = logging.getLogger(__name__)

SOURCE = "espn"
ENDPOINT = "roster"
VIEWS = ("mRoster",)
# A closed period is fetched again on each run until the league is this many periods past it.
RECHECK_PERIODS = 7


@dataclass
class RosterBackfillSummary:
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    failed_periods: list[int] = field(default_factory=list)
    unproven: list[int] = field(default_factory=list)


def last_period(status: dict[str, Any]) -> int:
    """The highest scoring period that exists: the season's final period, or today's."""
    latest = int(status.get("latestScoringPeriod", 0))
    final = int(status.get("finalScoringPeriod", latest))
    return min(latest, final)


def settled_through(
    roster_metas: Iterable[Mapping[str, Any]],
    settings_latest_by_run: Mapping[str, int],
) -> dict[int, int]:
    """For each scoring period, the highest latest-period any of its captures is evidence of.

    A sidecar with a `source_status` key is evidence by its own counter alone: any other
    shape is no evidence and does not fall back to the settings. A legacy sidecar (no such
    key) is evidence by the settings captured in the same run. Periods with no evidence
    are absent. The caller passes the sidecars of one league-season only.
    """
    evidence: dict[int, int] = {}
    for meta in roster_metas:
        if "source_status" in meta:
            status = meta["source_status"]
            latest = (
                _integer(status.get("latest_scoring_period"))
                if isinstance(status, Mapping)
                else None
            )
        else:
            latest = _integer(settings_latest_by_run.get(meta["fetched_at"]))
        if latest is None:
            continue
        period = int(meta["partitions"]["scoring_period"])
        evidence[period] = max(latest, evidence.get(period, 0))
    return evidence


def is_closed(period: int, evidence: Mapping[int, int]) -> bool:
    """True when some capture was taken after the league had moved past `period`."""
    return evidence.get(period, 0) > period


def is_settled(period: int, evidence: Mapping[int, int]) -> bool:
    """True when the league is more than RECHECK_PERIODS past `period`: stop re-checking."""
    return evidence.get(period, 0) > period + RECHECK_PERIODS


def roster_evidence(zone: LandingZone, *, season: int, league_id: str) -> dict[int, int]:
    """The evidence of every roster period of one league-season, from sidecars alone.

    No roster payload is read. The one payload read is a settings capture whose stamp a
    legacy roster capture carries: that is how a legacy capture is judged (ADR 0017).
    """
    metas = [
        capture.meta
        for capture in zone.committed(source=SOURCE, endpoint=ENDPOINT)
        if _of_league_season(capture.meta, season, league_id)
    ]
    legacy_stamps = {meta["fetched_at"] for meta in metas if "source_status" not in meta}
    settings_latest_by_run: dict[str, int] = {}
    if legacy_stamps:
        for capture in zone.committed(source=SOURCE, endpoint="settings"):
            stamp = str(capture.meta.get("fetched_at"))
            if stamp not in legacy_stamps or not _of_league_season(capture.meta, season, league_id):
                continue
            payload = capture.payload
            status = payload.get("status") if isinstance(payload, dict) else None
            latest = (
                _integer(status.get("latestScoringPeriod")) if isinstance(status, dict) else None
            )
            if latest is not None:
                settings_latest_by_run[stamp] = latest
    return settled_through(metas, settings_latest_by_run)


def needs_fetch(period: int, *, evidence: Mapping[int, int], refresh: bool = False) -> bool:
    """True when `refresh` is asked for or no capture has settled `period`."""
    return refresh or not is_settled(period, evidence)


def backfill_rosters(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    league_id: str,
    status: dict[str, Any],
    fetched_at: str,
    refresh: bool = False,
) -> RosterBackfillSummary:
    """Land rosters for every scoring period up to the latest that exists."""
    summary = RosterBackfillSummary()
    evidence = roster_evidence(zone, season=season, league_id=league_id)
    final_period = last_period(status)
    for period in range(1, final_period + 1):
        if not needs_fetch(period, evidence=evidence, refresh=refresh):
            summary.skipped += 1
            continue
        try:
            recorded = _fetch_one(
                zone=zone,
                client=client,
                season=season,
                league_id=league_id,
                period=period,
                fetched_at=fetched_at,
            )
        except (AuthExpired, LandingCollision):
            # Every remaining period would be rejected too: stop, don't log 180 failures.
            # A collision likewise stops the run; it is not one failed period.
            raise
        except Exception:
            logger.exception("roster fetch failed for scoring period %s", period)
            summary.failed += 1
            summary.failed_periods.append(period)
        else:
            summary.fetched += 1
            latest = recorded["latest_scoring_period"]
            if latest is not None:
                evidence[period] = max(latest, evidence.get(period, 0))
    run_latest = int(status.get("latestScoringPeriod", 0))
    summary.unproven = [
        period
        for period in range(1, final_period + 1)
        if period < run_latest and not is_closed(period, evidence)
    ]
    return summary


def _of_league_season(meta: Mapping[str, Any], season: int, league_id: str) -> bool:
    partitions = meta.get("partitions", {})
    return str(partitions.get("season")) == str(season) and str(partitions.get("league_id")) == str(
        league_id
    )


def _fetch_one(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    league_id: str,
    period: int,
    fetched_at: str,
) -> dict[str, int | None]:
    """Land one period's roster; return the status its response recorded."""
    params: list[tuple[str, str | int]] = [("view", view) for view in VIEWS]
    params.append(("scoringPeriodId", period))
    response = client.get(league_url(season, league_id), params=params)
    payload = response.json()
    source_status = _source_status(payload, period)
    zone.write(
        source=SOURCE,
        endpoint=ENDPOINT,
        partitions={"season": season, "league_id": league_id, "scoring_period": period},
        name=f"fetched_at={fetched_at}",
        payload=payload,
        request={
            "url": str(response.request.url),
            "params": {"view": ",".join(VIEWS), "scoringPeriodId": period},
        },
        fetched_at=fetched_at,
        source_status=source_status,
    )
    return source_status


def _integer(value: Any) -> int | None:
    """`value` when it is an integer (a bool is not one here), else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _source_status(payload: Any, period: int) -> dict[str, int | None]:
    """The two league counters this roster response carries, for its sidecar.

    A response without a usable latestScoringPeriod still lands: the capture is kept and
    proves nothing, and the warning says which period.
    """
    status = payload.get("status") if isinstance(payload, dict) else None
    if not isinstance(status, dict):
        status = {}
    latest = _integer(status.get("latestScoringPeriod"))
    if latest is None:
        logger.warning(
            "roster response for scoring period %s has no usable status.latestScoringPeriod",
            period,
        )
    return {
        "latest_scoring_period": latest,
        "final_scoring_period": _integer(status.get("finalScoringPeriod")),
    }
