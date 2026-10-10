"""ESPN rosters, one capture per scoring period and run.

A scoring period is one day of fantasy scoring. Its roster can change until the period
closes, so a capture taken while the period was current must not be the one kept.

A period is *closed* when some committed capture of it is evidence that the league had
moved past it: the response's own `status.latestScoringPeriod`, copied into the capture's
sidecar as `source_status`, is greater than the period (ADR 0016). The evidence comes
from the same response as the roster, so no boundary falls between them, and it is
read from sidecars: no roster payload is opened to decide what to fetch. The status the
run fetched at the start only decides which periods exist, never which are final.

A capture made before `source_status` existed is judged by the settings capture of the
same run, which is the rule the audit already applied (ADR 0017). With no such settings,
or no integer counter in it, it is no evidence.

A closed period is still fetched on every run until the league is `RECHECK_PERIODS`
past it, and only then *settled* and skipped (ADR 0018): a commissioner can correct a
recent day after it closes, and refetching costs nothing to interpret. An older edit
is picked up by `--refresh`. A period the league is past that no capture proves closed
is reported as unproven, which the command turns into a non-zero exit.

ESPN's counter is a calendar while the season runs and stops one past the last period with
a pro game, so the last seven periods before the stop could never be past it by 7 (ADR
0047, beside ADR 0018). A period's counter is therefore *extended*: when its greatest
counter is the greatest any capture of the league-season carries and is past the period,
one is added for every whole 24 hours between the period's first and last capture
carrying it. While the counter moves no two captures a day apart carry the same value, so
nothing changes; once it has stopped the extended counter rises a day at a time, as ESPN's
would have, and the period settles a week after it closed. A counter some other response
has exceeded is a lagging status and is never extended. Closure still reads the greatest
counter alone (ADR 0016), and only sidecars are read. The extension is `PeriodEvidence`.

The audit calls `settled_through`, `is_closed` and `is_settled` too, so the fetch
logic and the audit cannot disagree.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

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


class Sighting(NamedTuple):
    """One capture that carries a usable counter: when its run was stamped, what it read."""

    fetched_at: str
    counter: int


@dataclass(frozen=True)
class PeriodEvidence:
    """What the sidecars of one scoring period show about the league's counter (ADR 0047)."""

    latest: int  # greatest counter any capture of the period carries
    extended: int  # R1.1; equals `latest` unless a counter was seen unchanged
    unchanged: int | None = None  # the counter behind `extended` when extended > latest


def collect_sightings(
    roster_metas: Iterable[Mapping[str, Any]],
    settings_latest_by_run: Mapping[str, int],
) -> dict[int, list[Sighting]]:
    """For each scoring period, a sighting per capture that is evidence of a counter.

    A sidecar with a `source_status` key is evidence by its own counter alone: any other
    shape is no evidence and does not fall back to the settings. A legacy sidecar (no such
    key) is evidence by the settings captured in the same run. Periods with no evidence
    are absent. A sighting whose stamp is not a run stamp is kept, and named in a warning:
    it counts for its counter but cannot count for elapsed time.
    """
    sightings: dict[int, list[Sighting]] = {}
    for meta in roster_metas:
        if "source_status" in meta:
            status = meta["source_status"]
            counter = (
                _integer(status.get("latest_scoring_period"))
                if isinstance(status, Mapping)
                else None
            )
        else:
            counter = _integer(settings_latest_by_run.get(meta["fetched_at"]))
        if counter is None:
            continue
        period = int(meta["partitions"]["scoring_period"])
        stamp = str(meta.get("fetched_at"))
        if _parse_stamp(stamp) is None:
            logger.warning(
                "roster capture of scoring period %s has fetched_at %r, which is not a run "
                "stamp: its counter is kept, but it is left out of the days a counter stood",
                period,
                stamp,
            )
        sightings.setdefault(period, []).append(Sighting(stamp, counter))
    return sightings


def build_evidence(sightings: Mapping[int, Iterable[Sighting]]) -> dict[int, PeriodEvidence]:
    """The evidence of each period: its greatest counter, and that counter extended by the calendar.

    `top` is the greatest counter any sighting of the league-season carries. Only a period
    whose greatest counter is `top`, and past the period, is extended (R1.1, R1.9): by one
    per whole 24 hours between its first and last sighting of `top`.
    """
    held = {period: list(seen) for period, seen in sightings.items()}
    top = max((s.counter for seen in held.values() for s in seen), default=0)
    evidence: dict[int, PeriodEvidence] = {}
    for period, seen in held.items():
        latest = max(s.counter for s in seen)
        extended = latest
        if latest == top and top > period:
            times = [
                when
                for s in seen
                if s.counter == top and (when := _parse_stamp(s.fetched_at)) is not None
            ]
            if times:
                extended = top + (max(times) - min(times)) // timedelta(days=1)
        evidence[period] = PeriodEvidence(
            latest=latest, extended=extended, unchanged=top if extended > latest else None
        )
    return evidence


def settled_through(
    roster_metas: Iterable[Mapping[str, Any]],
    settings_latest_by_run: Mapping[str, int],
) -> dict[int, PeriodEvidence]:
    """For each scoring period, what its captures are evidence of (see `collect_sightings`).

    The caller passes the sidecars of one league-season only.
    """
    return build_evidence(collect_sightings(roster_metas, settings_latest_by_run))


def is_closed(period: int, evidence: Mapping[int, PeriodEvidence]) -> bool:
    """True when some capture was taken after the league had moved past `period`."""
    found = evidence.get(period)
    return found is not None and found.latest > period


def is_settled(period: int, evidence: Mapping[int, PeriodEvidence]) -> bool:
    """True when the league is more than RECHECK_PERIODS past `period`: stop re-checking."""
    found = evidence.get(period)
    return found is not None and found.extended > period + RECHECK_PERIODS


def roster_sightings(
    zone: LandingZone, *, season: int, league_id: str
) -> dict[int, list[Sighting]]:
    """The sightings of every roster period of one league-season, from sidecars alone.

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
    return collect_sightings(metas, settings_latest_by_run)


def roster_evidence(zone: LandingZone, *, season: int, league_id: str) -> dict[int, PeriodEvidence]:
    """The evidence of every roster period of one league-season, from sidecars alone."""
    return build_evidence(roster_sightings(zone, season=season, league_id=league_id))


def needs_fetch(
    period: int, *, evidence: Mapping[int, PeriodEvidence], refresh: bool = False
) -> bool:
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
    sightings = roster_sightings(zone, season=season, league_id=league_id)
    evidence = build_evidence(sightings)
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
                # The new capture is a sighting like any landed one, and a fetch can raise `top`,
                # so every period's evidence is rebuilt from the sightings (R1.7).
                sightings.setdefault(period, []).append(Sighting(fetched_at, latest))
                evidence = build_evidence(sightings)
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


def _parse_stamp(stamp: str) -> datetime | None:
    """A run stamp such as `20261007T011005Z` as a UTC time, or None when it is not one."""
    try:
        return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


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
