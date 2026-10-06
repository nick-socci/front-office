"""CLI wiring for the landing zone: lock, sweep, stop on collision, repair, warnings.

The fault-injection matrix from the design is run end to end: a settled boxscore, one
failure at each boundary of a write, then a second backfill, which must leave the entity
committed exactly once and the landing root holding only captures.
"""

import datetime as dt
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from front_office.cli import app
from front_office.http_client import HttpClient, SourceLimits
from front_office.landing import LandingZone

FIRST = "20260927T000000Z"
SECOND = "20260928T000000Z"
runner = CliRunner()


def game(pk, date="2026-04-14"):
    return {
        "gamePk": pk,
        "season": "2026",
        "officialDate": date,
        "gameType": "R",
        "status": {"abstractGameState": "Final", "detailedState": "Final"},
    }


@pytest.fixture
def zone(tmp_path):
    zone = LandingZone(root=tmp_path / "raw")
    zone.write(
        source="mlb",
        endpoint="schedule",
        partitions={"season": 2026, "game_type": "R"},
        name="fetched_at=20260926T000000Z",
        payload={"dates": [{"date": "2026-04-14", "games": [game(11)]}]},
        request={"url": "https://statsapi.mlb.com/api/v1/schedule", "params": {"season": 2026}},
        fetched_at="20260926T000000Z",
    )
    return zone


@pytest.fixture
def requested(monkeypatch):
    """Patch the CLI's HTTP client to a mock; the list records each request path."""
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"teams": {}})

    def make(source):
        return HttpClient(
            source,
            limits=SourceLimits(min_interval_s=0.0, max_attempts=1, backoff_base_s=0.0),
            transport=httpx.MockTransport(handler),
            sleep=lambda _seconds: None,
        )

    monkeypatch.setattr("front_office.cli.HttpClient", make)
    return seen


def stamps(monkeypatch, *values):
    queue = list(values)
    monkeypatch.setattr("front_office.cli.utc_stamp", lambda: queue.pop(0))


def backfill(zone):
    return runner.invoke(
        app,
        ["backfill", "mlb", "--season", "2026", "--only", "boxscore", "--raw-root", str(zone.root)],
    )


def boxscores(zone):
    return [c for c in zone.committed(source="mlb", endpoint="boxscore")]


def only_captures(zone):
    return all(s.kind == "committed" for s in zone.scan())


def quarantine_entries(zone):
    if not zone.quarantine_root.exists():
        return []
    return [p for p in zone.quarantine_root.rglob("*") if p.name != ".gitignore"]


# -- the fault-injection matrix ------------------------------------------------------------------


def _fail_mkdir_of_temp(monkeypatch):
    real = Path.mkdir

    def mkdir(self, *args, **kwargs):
        if ".tmp-" in self.name:
            raise OSError("no space for the temporary directory")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)


def _fail_write_of(method, filename):
    def inject(monkeypatch):
        real = getattr(Path, method)

        def failing(self, *args, **kwargs):
            if self.name == filename:
                raise OSError(f"disk full writing {filename}")
            return real(self, *args, **kwargs)

        monkeypatch.setattr(Path, method, failing)

    return inject


def _fail_rename(monkeypatch):
    def failing(src, dst):
        raise OSError(5, "input/output error")

    monkeypatch.setattr("front_office.landing.os.rename", failing)


@pytest.mark.parametrize(
    "inject",
    [
        _fail_mkdir_of_temp,
        _fail_write_of("write_bytes", "payload.json"),
        _fail_write_of("write_text", "meta.json"),
        _fail_rename,
    ],
    ids=["create_temp_dir", "write_payload", "write_meta", "rename"],
)
def test_a_failed_write_leaves_nothing_and_the_second_run_fetches(
    zone, requested, monkeypatch, inject
):
    """Catches a failure at any boundary of a write leaving something a reader or the next
    run could mistake for a capture, or an entity that is never fetched again."""
    stamps(monkeypatch, FIRST, SECOND)
    before = sorted(str(p) for p in zone.root.rglob("*"))
    with monkeypatch.context() as faulty:
        inject(faulty)
        first = backfill(zone)
    assert first.exit_code == 1, first.output
    assert sorted(str(p) for p in zone.root.rglob("*")) == before
    assert boxscores(zone) == []

    second = backfill(zone)
    assert second.exit_code == 0, second.output
    assert len(boxscores(zone)) == 1
    assert only_captures(zone)
    assert quarantine_entries(zone) == []


@pytest.mark.parametrize("files", [0, 1, 2])
def test_a_process_killed_before_the_rename_is_swept_and_refetched(
    zone, requested, monkeypatch, files
):
    """Catches a leftover temporary directory blocking its entity, or being left in the
    landing root, or being deleted instead of quarantined (R3.1, R3.4)."""
    stamps(monkeypatch, SECOND)
    folder = zone.root / "mlb/boxscore/season=2026/game_pk=11"
    temp = folder / f"fetched_at={FIRST}.tmp-4242"
    temp.mkdir(parents=True)
    for name in ("payload.json", "meta.json")[:files]:
        (temp / name).write_text("{}")

    result = backfill(zone)
    assert result.exit_code == 0, result.output
    assert "quarantined" in result.output or "moved" in result.output
    assert requested == ["/api/v1/game/11/boxscore"]
    assert len(boxscores(zone)) == 1
    assert only_captures(zone)
    moved = [p for p in quarantine_entries(zone) if p.name.startswith("fetched_at=")]
    assert [p.name for p in moved] == [temp.name]
    assert len(list(moved[0].iterdir())) == files


def test_a_process_killed_after_the_rename_is_not_fetched_again(zone, requested, monkeypatch):
    """Catches a committed capture fetched again, or quarantined, on the next run."""
    stamps(monkeypatch, SECOND)
    zone.write(
        source="mlb",
        endpoint="boxscore",
        partitions={"season": 2026, "game_pk": 11},
        name=f"fetched_at={FIRST}",
        payload={"teams": {}},
        request={"url": "https://example.test", "params": {"gamePk": 11}},
        fetched_at=FIRST,
    )
    result = backfill(zone)
    assert result.exit_code == 0, result.output
    assert requested == []
    assert len(boxscores(zone)) == 1
    assert quarantine_entries(zone) == []


# -- refusals ------------------------------------------------------------------------------------


def test_a_sweep_over_the_limit_stops_the_backfill_before_any_fetch(zone, requested, monkeypatch):
    """Catches a backfill that fetches (or moves) after a sweep it refused (R3.6)."""
    stamps(monkeypatch, SECOND)
    for n in range(51):
        (zone.root / f"stray{n}.txt").write_text("x")
    result = backfill(zone)
    assert result.exit_code != 0
    assert "51" in result.output
    assert requested == []
    assert len(list(zone.root.glob("stray*.txt"))) == 51
    assert not zone.quarantine_root.exists()


def test_a_tree_of_old_layout_pairs_stops_the_backfill_naming_the_migration(
    zone, requested, monkeypatch
):
    """Catches a backfill sweeping an unmigrated tree and fetching it all again (R6.7)."""
    stamps(monkeypatch, SECOND)
    (zone.root / "old.json").write_text("{}")
    (zone.root / "old.meta.json").write_text("{}")
    result = backfill(zone)
    assert result.exit_code != 0
    assert "migrate_landing_layout.py" in result.output
    assert requested == []
    assert (zone.root / "old.json").exists()
    assert not zone.quarantine_root.exists()


def test_a_second_backfill_while_the_lock_is_held_changes_nothing(zone, requested, monkeypatch):
    """Catches two writers at once (R4.2)."""
    stamps(monkeypatch, SECOND)
    (zone.root / "stray.txt").write_text("x")
    before = sorted(str(p) for p in zone.root.rglob("*"))
    with zone.writer_lock():
        result = backfill(zone)
    assert result.exit_code != 0
    assert str(zone.lock_path) in result.output
    assert requested == []
    assert sorted(str(p) for p in zone.root.rglob("*")) == before


def test_a_collision_exits_non_zero_and_fetches_no_later_game(zone, requested, monkeypatch):
    """Catches a LandingCollision escaping as a traceback or counted as one failed game
    while the run carries on (R1.4)."""
    stamps(monkeypatch, SECOND)
    recent = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).date().isoformat()
    zone.write(
        source="mlb",
        endpoint="schedule",
        partitions={"season": 2026, "game_type": "R"},
        name="fetched_at=20260927T120000Z",
        payload={"dates": [{"date": recent, "games": [game(n, recent) for n in (11, 12, 13)]}]},
        request={"url": "https://statsapi.mlb.com/api/v1/schedule", "params": {"season": 2026}},
        fetched_at="20260927T120000Z",
    )
    # Game 12 already has a capture at the stamp this run will use: its write collides.
    zone.write(
        source="mlb",
        endpoint="boxscore",
        partitions={"season": 2026, "game_pk": 12},
        name=f"fetched_at={SECOND}",
        payload={"teams": {}},
        request={"url": "https://example.test", "params": {"gamePk": 12}},
        fetched_at=SECOND,
    )
    result = backfill(zone)
    assert result.exit_code == 1
    assert "already exists" in result.output
    assert "Traceback" not in result.output
    assert requested == ["/api/v1/game/11/boxscore", "/api/v1/game/12/boxscore"]


# -- repair --------------------------------------------------------------------------------------


def _debris(zone):
    folder = zone.root / "mlb/schedule/season=2026/game_type=R"
    (folder / "fetched_at=20260926T010000Z.tmp-9").mkdir()
    (folder / "stray.json").write_text("{}")


def repair(zone, *flags):
    return runner.invoke(app, ["repair", "--raw-root", str(zone.root), *flags])


def test_repair_dry_run_lists_and_changes_nothing(zone):
    """Catches a dry run that moves, or one that does not say what would move (R3.5)."""
    _debris(zone)
    before = sorted(str(p) for p in zone.root.rglob("*"))
    result = repair(zone, "--dry-run")
    assert result.exit_code == 0, result.output
    assert "temp" in result.output and "loose" in result.output
    assert "2" in result.output
    assert sorted(str(p) for p in zone.root.rglob("*")) == before
    assert not zone.quarantine_root.exists()
    assert not zone.lock_path.exists(), "a dry run takes no lock"


def test_repair_dry_run_says_when_the_plan_exceeds_the_limit(zone):
    """Catches a dry run that hides that the real run would refuse (R3.6)."""
    for n in range(51):
        (zone.root / f"stray{n}.txt").write_text("x")
    result = repair(zone, "--dry-run")
    assert result.exit_code == 0, result.output
    assert "limit" in result.output and "--force" in result.output
    assert len(list(zone.root.glob("stray*.txt"))) == 51


def test_repair_moves_and_counts(zone):
    """Catches a repair that reports but does not move."""
    _debris(zone)
    result = repair(zone)
    assert result.exit_code == 0, result.output
    assert "temp" in result.output and "loose" in result.output
    assert only_captures(zone)
    assert "moved 2 item(s)" in result.output


def test_repair_over_the_limit_needs_force(zone):
    """Catches a mass move without --force, and --force that does not allow it."""
    for n in range(51):
        (zone.root / f"stray{n}.txt").write_text("x")
    refused = repair(zone)
    assert refused.exit_code == 1 and "limit" in refused.output
    assert len(list(zone.root.glob("stray*.txt"))) == 51
    assert repair(zone, "--force").exit_code == 0
    assert list(zone.root.glob("stray*.txt")) == []


def test_repair_deep_moves_a_corrupt_capture(zone):
    """Catches --deep not reaching the checksum check."""
    capture = next(iter(zone.committed())).directory
    # A committed sibling keeps the folder out of the plan, so the capture moves as itself.
    zone.write(
        source="mlb",
        endpoint="schedule",
        partitions={"season": 2026, "game_type": "R"},
        name="fetched_at=20260929T000000Z",
        payload={"dates": []},
        request={"url": "https://statsapi.mlb.com/api/v1/schedule", "params": {"season": 2026}},
        fetched_at="20260929T000000Z",
    )
    body = (capture / "payload.json").read_text()
    (capture / "payload.json").write_text(body.replace("dates", "datez"))
    assert repair(zone).exit_code == 0 and capture.exists()
    result = repair(zone, "--deep")
    assert result.exit_code == 0, result.output
    assert "corrupt" in result.output
    assert not capture.exists()


@pytest.mark.parametrize("flags", [[], ["--dry-run"]])
def test_repair_on_an_unmigrated_tree_exits_non_zero(zone, flags):
    """Catches the interlock skipped by repair, or by its dry run (R6.7)."""
    (zone.root / "old.json").write_text("{}")
    (zone.root / "old.meta.json").write_text("{}")
    result = repair(zone, *flags)
    assert result.exit_code == 1
    assert "migrate_landing_layout.py" in result.output
    assert (zone.root / "old.json").exists()


# -- readers warn --------------------------------------------------------------------------------

WARNING = "a backfill is in progress"


def load(zone, tmp_path):
    return runner.invoke(
        app, ["load", "--raw-root", str(zone.root), "--db", str(tmp_path / "w.db")]
    )


def audit(zone, tmp_path):
    return runner.invoke(
        app,
        ["audit", "--season", "2026", "--raw-root", str(zone.root), "--db", str(tmp_path / "w.db")],
    )


def test_load_warns_while_a_writer_holds_the_lock_and_not_otherwise(zone, tmp_path):
    """Catches a silently incomplete load (R4.6), or a warning when nothing is running."""
    assert WARNING not in load(zone, tmp_path).output
    with zone.writer_lock():
        result = load(zone, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.output.count(WARNING) == 1


def test_audit_warns_while_a_writer_holds_the_lock_and_not_otherwise(zone, tmp_path):
    """Catches an audit read as complete during a backfill (R4.6)."""
    assert WARNING not in audit(zone, tmp_path).output
    with zone.writer_lock():
        result = audit(zone, tmp_path)
    assert result.output.count(WARNING) == 1
