"""Tests for the sweep, its limit, the layout interlock and the writer lock (ADR 0015)."""

import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from front_office.landing import (
    LandingLocked,
    LandingZone,
    NotMigrated,
    SweepTooLarge,
)

STAMP = "20260926T000000Z"
SRC = str(Path(__file__).resolve().parents[1] / "src")


@pytest.fixture
def zone(tmp_path):
    return LandingZone(root=tmp_path / "raw")


def land(zone, game_pk=1, stamp=STAMP):
    return zone.write(
        source="mlb",
        endpoint="boxscore",
        partitions={"season": 2026, "game_pk": game_pk},
        name=f"fetched_at={stamp}",
        payload={"teams": {}},
        request={"url": "https://example.test/box", "params": {"gamePk": game_pk}},
        fetched_at=stamp,
    )


def temp_dir(zone, game_pk, files=0):
    folder = zone.root / f"mlb/boxscore/season=2026/game_pk={game_pk}/fetched_at={STAMP}.tmp-77"
    folder.mkdir(parents=True)
    for name in ("payload.json", "meta.json")[:files]:
        (folder / name).write_text("{}")
    return folder


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def quarantined(zone):
    return sorted(
        str(p.relative_to(zone.quarantine_root))
        for p in zone.quarantine_root.rglob("*")
        if p.name != ".gitignore"
    )


def test_siblings_of_the_root(zone, tmp_path):
    """Catches the quarantine, lock or migration directory inside the scanned tree (R4.4)."""
    assert zone.quarantine_root == tmp_path / "raw_quarantine"
    assert zone.lock_path == tmp_path / "raw.lock"
    assert zone.migration_dir == tmp_path / "raw_migration"


# -- what moves ----------------------------------------------------------------------------


def _make_debris(zone):
    """One of each kind, all beside a committed capture so each moves as itself."""
    kept = land(zone, 1)
    folder = kept.parent
    temp = folder / "fetched_at=20260926T030000Z.tmp-77"
    temp.mkdir()
    (temp / "payload.json").write_text("{}")
    (temp / "meta.json").write_text("{}")
    invalid = folder / "fetched_at=20260926T010000Z"
    invalid.mkdir()
    (invalid / "payload.json").write_text("{}")
    loose = folder / "stray.json"
    loose.write_text("{}")
    empty = folder / "nothing_here"
    empty.mkdir()
    return kept, {"temp": temp, "invalid": invalid, "loose": loose, "empty": empty}


def test_each_kind_moves_whole_to_the_quarantine_and_committed_never_moves(zone):
    """Catches a kind left behind, a path flattened, or a committed capture moved."""
    kept, debris = _make_debris(zone)
    plan = zone.sweep(STAMP)
    assert {kind for kind, _ in plan} == set(debris)
    for kind, path in debris.items():
        relative = path.relative_to(zone.root)
        assert (kind, relative) in plan
        assert not path.exists()
        assert (zone.quarantine_root / STAMP / relative).exists()
    assert (zone.quarantine_root / STAMP / debris["temp"].relative_to(zone.root)).is_dir()
    assert sorted(
        p.name
        for p in (zone.quarantine_root / STAMP / debris["temp"].relative_to(zone.root)).iterdir()
    ) == ["meta.json", "payload.json"]
    assert kept.is_dir() and zone.check(kept) is None


def test_sweeping_twice_with_one_stamp_overwrites_nothing(zone):
    """Catches a second sweep replacing what an earlier one quarantined (R3.3)."""
    temp_dir(zone, 1, files=1)
    zone.sweep(STAMP)
    temp_dir(zone, 1, files=2)
    zone.sweep(STAMP)
    first = zone.quarantine_root / STAMP / "mlb/boxscore/season=2026/game_pk=1"
    second = zone.quarantine_root / f"{STAMP}-2" / "mlb/boxscore/season=2026/game_pk=1"
    assert len(list(first.rglob("payload.json"))) == 1
    assert len(list(first.rglob("meta.json"))) == 0
    assert len(list(second.rglob("meta.json"))) == 1


def test_a_dry_run_moves_nothing_and_returns_the_plan_the_real_sweep_executes(zone):
    """Catches a dry run that differs from, or does, the real thing (R3.5)."""
    _make_debris(zone)
    before = tree(zone.root)
    dry = zone.sweep(STAMP, dry_run=True)
    assert tree(zone.root) == before
    assert not zone.quarantine_root.exists()
    real = zone.sweep(STAMP)
    assert real == dry
    assert tree(zone.root) != before


def test_deep_moves_a_corrupt_capture_and_shallow_leaves_it(zone):
    """Catches deep corruption ignored by repair --deep, or moved without it."""
    land(zone, 1, stamp="20260927T000000Z")  # a committed sibling keeps the folder
    capture = land(zone)
    # Same size, different bytes, still JSON: only the checksum notices.
    (capture / "payload.json").write_text('{"teams": 1}'.ljust(len('{"teams": {}}')))
    assert zone.check(capture) is None
    assert zone.sweep(STAMP) == []
    assert capture.is_dir()
    plan = zone.sweep(STAMP, deep=True)
    assert plan == [("corrupt", capture.relative_to(zone.root))]
    assert not capture.exists()
    assert (zone.quarantine_root / STAMP / capture.relative_to(zone.root) / "meta.json").exists()


def test_49_temp_dirs_each_alone_in_a_folder_plan_the_49_folders(zone):
    """Catches counting a folder and its only content separately: 98 items, not 49, which
    would trip the limit and make the dry run print what is not moved."""
    land(zone, 1000)  # a committed sibling keeps the shared ancestors out of the plan
    for pk in range(49):
        temp_dir(zone, pk, files=1)
    dry = zone.sweep(STAMP, dry_run=True)
    assert len(dry) == 49
    assert {path.parts[-1] for _, path in dry} == {f"game_pk={pk}" for pk in range(49)}
    real = zone.sweep(STAMP)
    assert real == dry
    assert quarantined(zone).count(f"{STAMP}/mlb/boxscore/season=2026/game_pk=0") == 1
    assert [p.name for p in (zone.root / "mlb/boxscore/season=2026").iterdir()] == ["game_pk=1000"]


def test_51_stray_files_in_a_tree_of_100_captures_refuse_and_force_moves(zone):
    """Catches a mass move caused by a bug (R3.6): the limit is 1% of files or 50."""
    for pk in range(100):
        land(zone, pk)
    strays = [zone.root / f"stray{n}.txt" for n in range(51)]
    for stray in strays:
        stray.write_text("x")
    before = tree(zone.root)
    assert zone.sweep_limit() == 50, "1% of 251 files is 3; the floor is 50"
    with pytest.raises(SweepTooLarge) as excinfo:
        zone.sweep(STAMP)
    assert "51" in str(excinfo.value)
    assert tree(zone.root) == before
    assert not zone.quarantine_root.exists()
    assert len(zone.sweep(STAMP, dry_run=True)) == 51, "a dry run reports, it does not raise"
    assert len(zone.sweep(STAMP, force=True)) == 51
    assert not any(stray.exists() for stray in strays)


def test_three_temp_dirs_move_without_force(zone):
    """Catches a limit so tight that an ordinary killed run needs --force."""
    land(zone, 1000)
    for pk in range(3):
        temp_dir(zone, pk, files=2)
    assert len(zone.sweep(STAMP)) == 3


def test_the_quarantine_ignores_itself_even_inside_a_git_work_tree(tmp_path):
    """Catches private data quarantined to a path git would pick up, for a root that is
    not the default (R3.2)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    zone = LandingZone(root=repo / "anywhere" / "landing")
    temp_dir(zone, 1, files=2)
    zone.sweep(STAMP)
    assert (zone.quarantine_root / ".gitignore").read_text() == "*\n"
    nested = next((zone.quarantine_root / STAMP).rglob("payload.json"))
    result = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", str(nested)])
    assert result.returncode == 0


def test_an_empty_capture_directory_is_invalid_and_an_empty_folder_is_empty(zone):
    """Catches debris that holds no file and so is never seen."""
    capture = land(zone, 1).parent / "fetched_at=20260926T020000Z"
    capture.mkdir()
    folder = zone.root / "espn/settings/season=2026"
    folder.mkdir(parents=True)
    plan = dict((str(path), kind) for kind, path in zone.sweep(STAMP, dry_run=True))
    assert plan["mlb/boxscore/season=2026/game_pk=1/fetched_at=20260926T020000Z"] == "invalid"
    assert plan["espn"] == "empty", "the whole empty chain moves as its top folder"
    zone.sweep(STAMP)
    assert not capture.exists() and not folder.exists()


def test_a_folder_that_becomes_empty_only_because_its_last_entry_goes_is_in_the_plan(zone):
    """Catches a plan that leaves behind the folders its own moves empty (and so needs a
    second sweep to finish)."""
    land(zone, 1)
    loose = zone.root / "mlb/schedule/season=2026/stray.json"
    loose.parent.mkdir(parents=True)
    loose.write_text("{}")
    plan = zone.sweep(STAMP)
    assert plan == [("empty", Path("mlb/schedule"))]
    assert not (zone.root / "mlb/schedule").exists()
    assert zone.sweep("20260927T000000Z") == []


# -- the layout interlock ----------------------------------------------------------------------


def journal(zone, *records):
    zone.migration_dir.mkdir(exist_ok=True)
    (zone.migration_dir / "journal.tsv").write_text("".join(f"{r}\n" for r in records))


def old_pair(zone, n=0):
    folder = zone.root / "mlb/boxscore/season=2026/game_pk=1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"fetched_at=2026092{n}T000000Z.json").write_text("{}")
    (folder / f"fetched_at=2026092{n}T000000Z.meta.json").write_text("{}")


PROBLEM_STATES = {
    "in_progress": lambda zone: journal(zone, "start", "begin\ta\tb"),
    "reversed": lambda zone: journal(zone, "start", "finished", "reversed"),
    "in_progress_after_reversal": lambda zone: journal(zone, "start", "reversed", "start"),
    "old_pairs_no_journal": lambda zone: [old_pair(zone, n) for n in range(3)],
    "old_pairs_with_finished_journal": lambda zone: (
        journal(zone, "start", "finished"),
        old_pair(zone),
    ),
}


@pytest.mark.parametrize("state", PROBLEM_STATES)
def test_layout_problem_and_sweep_refusal(zone, state):
    """Catches a backfill sweeping historical captures of an unmigrated tree into
    quarantine (R6.7)."""
    land(zone, 9)
    PROBLEM_STATES[state](zone)
    stray = zone.root / "stray.txt"
    stray.write_text("x")
    before = tree(zone.root)
    problem = zone.layout_problem()
    assert problem is not None and "migrate_landing_layout.py" in problem
    for dry_run in (False, True):
        with pytest.raises(NotMigrated):
            zone.sweep(STAMP, dry_run=dry_run)
    assert tree(zone.root) == before
    assert not zone.quarantine_root.exists()


def test_no_layout_problem_when_finished_or_with_no_journal(zone):
    """Catches the interlock refusing a tree that is wholly in the directory layout."""
    land(zone)
    assert zone.layout_problem() is None
    journal(zone, "start", "begin\ta\tb", "done\ta", "finished")
    assert zone.layout_problem() is None
    journal(zone, "start", "finished", "reversed", "start", "finished")
    assert zone.layout_problem() is None


def test_a_lone_payload_or_lone_sidecar_is_not_an_old_layout_pair(zone):
    """Catches the pair test firing on a spike payload, which is merely loose."""
    folder = zone.root / "a"
    folder.mkdir(parents=True)
    (folder / "x.json").write_text("{}")
    (folder / "y.meta.json").write_text("{}")
    assert zone.layout_problem() is None


# -- the writer lock ----------------------------------------------------------------------------

HOLDER = """
import sys, time
sys.path.insert(0, {src!r})
from pathlib import Path
from front_office.landing import LandingZone
zone = LandingZone(Path({root!r}))
with zone.writer_lock():
    print("held", flush=True)
    time.sleep(60)
"""

PROBER = """
import sys, time
sys.path.insert(0, {src!r})
from pathlib import Path
from front_office.landing import LandingZone
zone = LandingZone(Path({root!r}))
print("probing", flush=True)
end = time.time() + 1.5
while time.time() < end:
    zone.writer_active()
"""


def start(script, zone):
    proc = subprocess.Popen(
        [sys.executable, "-c", script.format(src=SRC, root=str(zone.root))],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    proc.stdout.readline()
    return proc


def test_a_second_writer_is_refused_while_the_first_holds_the_lock(zone, monkeypatch):
    """Catches two writers at once (R4.1, R4.2) and a refusal that does not name the lock."""
    holder = start(HOLDER, zone)
    try:
        started = time.monotonic()
        with pytest.raises(LandingLocked) as excinfo, zone.writer_lock():
            pytest.fail("the lock was not held")
        assert str(zone.lock_path) in str(excinfo.value)
        assert 1.5 < time.monotonic() - started < 10
        assert zone.writer_active() is True
    finally:
        holder.kill()
        holder.wait()


def test_the_lock_is_free_after_the_holder_is_killed(zone):
    """Catches a stale lock after SIGKILL (R4.3)."""
    holder = start(HOLDER, zone)
    holder.send_signal(signal.SIGKILL)
    holder.wait()
    assert zone.writer_active() is False
    with zone.writer_lock():
        assert zone.writer_active() is True


def test_a_writer_still_gets_the_lock_while_a_reader_probes(zone):
    """Catches a reader's momentary shared probe starving a writer (R4.5)."""
    zone.lock_path.write_text("")
    prober = start(PROBER, zone)
    try:
        with zone.writer_lock():
            pass
    finally:
        prober.wait()


def test_the_lock_file_is_beside_the_root_and_the_scan_never_sees_it(zone):
    """Catches a lock file inside the scanned tree (R4.4)."""
    land(zone)
    with zone.writer_lock():
        assert zone.lock_path.parent == zone.root.parent
        assert not (zone.root / zone.lock_path.name).exists()
    assert all(s.kind == "committed" for s in zone.scan())


def test_writer_active_is_false_with_no_lock_file_and_when_free(zone):
    """Catches the probe creating the lock file or reporting a writer that is not there."""
    assert zone.writer_active() is False
    assert not zone.lock_path.exists()
    with zone.writer_lock():
        assert zone.writer_active() is True
    assert zone.writer_active() is False
