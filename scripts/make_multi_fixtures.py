"""Build the combined fixture landing zone: two leagues by two seasons.

Generated from the committed fixture (fixtures/landing/) ALONE, never from data/raw/, so
nothing new can reach a public repo from the real league. The extra tenants are relabelled
copies: they prove isolation (spec 0028, R5), not baseball.

    111111, 2026   the existing ESPN fixture, copied byte for byte
    222222, 2026   the same, league id changed, same fetch stamps, one player respelled
    111111, 2027   the same, a ONE-scoring-period season on a calendar shifted 364 days
    222222, 2027   the 2027 one, league id changed

Usage:  uv run python scripts/make_multi_fixtures.py
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_ROOT = REPO_ROOT / "fixtures/landing"
OUTPUT_ROOT = REPO_ROOT / "fixtures/landing_multi"

BASE_LEAGUE = "111111"
OTHER_LEAGUE = "222222"
BASE_SEASON = 2026
NEW_SEASON = 2027

# Exactly 52 weeks: the weekday is preserved, and the year changes.
SHIFT = timedelta(days=364)
GAME_PK_OFFSET = 1_000_000

# Appended to one rostered player's name in league 222222, 2026. No rostered name in the
# fixture has a non-ASCII letter to unaccent, so a suffix it is.
RESPELLED_SUFFIX = " Jr."

ESPN_HOST = "https://lm-api-reads.fantasy.espn.com"
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
EASTERN = ZoneInfo("America/New_York")

Capture = tuple[dict[str, Any], Any]  # (sidecar, payload)


def read_captures(root: Path, *folders: str) -> list[Capture]:
    out: list[Capture] = []
    for sidecar in sorted((root.joinpath(*folders)).rglob("meta.json")):
        payload_path = sidecar.with_name("payload.json")
        out.append((json.loads(sidecar.read_text()), json.loads(payload_path.read_text())))
    return out


def write_capture(root: Path, meta: dict[str, Any], payload: Any) -> None:
    """Write a capture directory the way scripts/make_fixtures.py::write_fixture does."""
    path = root / meta["source"] / meta["endpoint"]
    for key, value in meta["partitions"].items():
        path = path / f"{key}={value}"
    path = path / f"fetched_at={meta['fetched_at']}"
    path.mkdir(parents=True, exist_ok=True)
    (path / "payload.json").write_text(json.dumps(payload, indent=1) + "\n")
    (path / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")


def request_key(params: dict[str, Any]) -> str:
    return "&".join(f"{k}={params[k]}" for k in sorted(params))


def copy_tree(source: Path, target: Path) -> None:
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        dest = target / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())


def espn_url(endpoint: str, season: int, league: str) -> str:
    """The URL the ESPN client builds. The base fixture's bare host is kept only for the
    byte-for-byte copy; the other tenants need a path, or their request paths collide."""
    path = f"/apis/v3/games/flb/seasons/{season}/segments/0/leagues/{league}"
    if endpoint == "transactions":
        path += "/communication"
    return ESPN_HOST + path


def relabel(
    meta: dict[str, Any], payload: Any, *, league: str, season: int, stamp_shift: timedelta
) -> Capture:
    meta = json.loads(json.dumps(meta))
    payload = json.loads(json.dumps(payload))
    meta["partitions"]["league_id"] = league
    meta["partitions"]["season"] = season
    meta["url"] = espn_url(meta["endpoint"], season, league)
    stamp = datetime.strptime(meta["fetched_at"], STAMP_FORMAT) + stamp_shift
    meta["fetched_at"] = stamp.strftime(STAMP_FORMAT)
    if isinstance(payload, dict):
        if "id" in payload:
            payload["id"] = league
        if "seasonId" in payload:
            payload["seasonId"] = season
    return meta, payload


def respell_one_player(captures: list[Capture]) -> tuple[int, str]:
    """Respell the lowest player id present on a roster of every period."""
    rosters = [p for m, p in captures if m["endpoint"] == "roster"]

    def names(payload: Any) -> dict[int, str]:
        return {
            e["playerId"]: e["playerPoolEntry"]["player"]["fullName"]
            for t in payload["teams"]
            for e in t["roster"]["entries"]
        }

    common = set.intersection(*(set(names(p)) for p in rosters))
    player = min(common)
    original = names(rosters[0])[player]
    for payload in rosters:
        for team in payload["teams"]:
            for entry in team["roster"]["entries"]:
                if entry["playerId"] == player:
                    entry["playerPoolEntry"]["player"]["fullName"] += RESPELLED_SUFFIX
    return player, original


def shift_epoch_ms(value: int) -> int:
    return value + int(SHIFT.total_seconds() * 1000)


def eastern_date(epoch_ms: int) -> date:
    return datetime.fromtimestamp(epoch_ms / 1000, UTC).astimezone(EASTERN).date()


def one_period_season(meta: dict[str, Any], payload: Any, target_day: date) -> Any:
    """Cut a relabelled 2027 capture down to a season of one scoring period."""
    endpoint = meta["endpoint"]
    if endpoint == "settings":
        payload["scoringPeriodId"] = 1
        payload["status"]["latestScoringPeriod"] = 1
        payload["status"]["finalScoringPeriod"] = 1
    elif endpoint == "matchups":
        for matchup in payload["schedule"]:
            for side in ("home", "away"):
                points = matchup.get(side, {}).get("pointsByScoringPeriod")
                if points:
                    matchup[side]["pointsByScoringPeriod"] = {
                        k: v for k, v in points.items() if k == "1"
                    }
    elif endpoint == "transactions":
        kept = []
        for topic in payload["topics"]:
            topic["date"] = shift_epoch_ms(topic["date"])
            for message in topic["messages"]:
                message["date"] = shift_epoch_ms(message["date"])
            if eastern_date(topic["date"]) == target_day:
                kept.append(topic)
        payload["topics"] = kept
    return payload


def build_2027_espn(base: list[Capture], target_day: date, stamp_shift: timedelta) -> list[Capture]:
    out: list[Capture] = []
    for meta, payload in base:
        if meta["endpoint"] == "roster" and meta["partitions"]["scoring_period"] != 1:
            continue
        new_meta, new_payload = relabel(
            meta, payload, league=BASE_LEAGUE, season=NEW_SEASON, stamp_shift=stamp_shift
        )
        out.append((new_meta, one_period_season(new_meta, new_payload, target_day)))
    return out


def shift_day(text: str, fmt: str) -> str:
    return (datetime.strptime(text, fmt) + SHIFT).strftime(fmt)


def build_2027_mlb(mlb: list[Capture]) -> list[Capture]:
    """The first fixture date's games, copied to the shifted date with new game ids."""
    schedule_meta, schedule = next((m, p) for m, p in mlb if m["endpoint"] == "schedule")
    first = schedule["dates"][0]
    # Entries of the first calendar day only. The postponed games the schedule files under
    # that day with a later officialDate belong to the next day and are left out.
    games = [g for g in first["games"] if g["officialDate"] == first["date"]]
    pks = {g["gamePk"] for g in games}
    day = shift_day(first["date"], "%Y-%m-%d")

    new_games = []
    for game in games:
        g = json.loads(json.dumps(game))
        g["gamePk"] += GAME_PK_OFFSET
        g["season"] = str(NEW_SEASON)
        g["officialDate"] = day
        g["gameDate"] = shift_day(g["gameDate"], "%Y-%m-%dT%H:%M:%SZ")
        new_games.append(g)
    meta = json.loads(json.dumps(schedule_meta))
    meta["partitions"]["season"] = NEW_SEASON
    meta["params"].update(season=NEW_SEASON, startDate=day, endDate=day)
    meta["request_key"] = request_key(meta["params"])
    meta["fetched_at"] = shift_day(meta["fetched_at"], STAMP_FORMAT)
    out: list[Capture] = [(meta, {"dates": [{"date": day, "games": new_games}]})]

    for box_meta, box in mlb:
        if box_meta["endpoint"] != "boxscore" or box_meta["partitions"]["game_pk"] not in pks:
            continue
        m = json.loads(json.dumps(box_meta))
        pk = m["partitions"]["game_pk"] + GAME_PK_OFFSET
        m["partitions"] = {"season": NEW_SEASON, "game_pk": pk}
        m["url"] = f"https://statsapi.mlb.com/api/v1/game/{pk}/boxscore"
        m["params"] = {"gamePk": pk}
        m["request_key"] = request_key(m["params"])
        m["fetched_at"] = shift_day(m["fetched_at"], STAMP_FORMAT)
        out.append((m, box))
    return out


def generate(input_root: Path, output_root: Path) -> dict[str, Any]:
    """Rewrite output_root from input_root. Returns a summary for the caller to print."""
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    copy_tree(input_root, output_root)  # 111111/2026, MLB 2026 and the id map, untouched

    base = read_captures(input_root, "espn")
    mlb = read_captures(input_root, "mlb")
    schedule = next(p for m, p in mlb if m["endpoint"] == "schedule")
    first_day = date.fromisoformat(schedule["dates"][0]["date"])
    target_day = first_day + SHIFT

    # The settings stamp's Eastern date is period 1's date in 2027 (latest period = 1), so
    # the stamps move by whatever puts that date on first_day + 364.
    settings_meta = next(m for m, _ in base if m["endpoint"] == "settings")
    settings_day = datetime.strptime(settings_meta["fetched_at"], STAMP_FORMAT).date()
    espn_2027_shift = SHIFT - (settings_day - first_day)

    # 222222, 2026: same stamps, new league id, one player respelled.
    other = [
        relabel(m, p, league=OTHER_LEAGUE, season=BASE_SEASON, stamp_shift=timedelta(0))
        for m, p in base
    ]
    player, original = respell_one_player(other)
    for meta, payload in other:
        write_capture(output_root, meta, payload)

    # 111111 and 222222, 2027.
    base_2027 = build_2027_espn(base, target_day, espn_2027_shift)
    for meta, payload in base_2027:
        write_capture(output_root, meta, payload)
    for meta, payload in base_2027:
        new_meta, new_payload = relabel(
            meta, payload, league=OTHER_LEAGUE, season=NEW_SEASON, stamp_shift=timedelta(0)
        )
        write_capture(output_root, new_meta, new_payload)

    for meta, payload in build_2027_mlb(mlb):
        write_capture(output_root, meta, payload)

    transactions_2027 = next(p for m, p in base_2027 if m["endpoint"] == "transactions")
    return {
        "respelled_player": player,
        "respelled_from": original,
        "transactions_2027": sum(len(t["messages"]) for t in transactions_2027["topics"]),
        "period_1_2027": target_day.isoformat(),
    }


def main() -> None:
    info = generate(INPUT_ROOT, OUTPUT_ROOT)
    print(f"respelled player {info['respelled_player']}: {info['respelled_from']!r} + suffix")
    print(f"2027 transaction messages kept per league: {info['transactions_2027']}")
    print(f"2027 scoring period 1 date: {info['period_1_2027']}")
    files = sum(1 for _ in OUTPUT_ROOT.rglob("*.json"))
    print(f"wrote {files} json files under {OUTPUT_ROOT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
