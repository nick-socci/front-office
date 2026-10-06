"""Tests for the layout migration (scripts/migrate_landing_layout.py) and its verifier.

The migration moves every capture of a real landing zone, so each test below is a way it
could lose, change, or half-move something. Old-layout trees are built by hand: a payload
`fetched_at=S.json` beside its sidecar `fetched_at=S.meta.json`, as the package wrote them
before ADR 0014.
"""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import duckdb
import httpx
import pytest
from typer.testing import CliRunner

import migrate_landing_layout as migrate
import verify_migration as verify
from front_office.cli import app
from front_office.http_client import HttpClient, SourceLimits
from front_office.landing import JOURNAL_FILE, LandingZone, NotMigrated
from front_office.load import CREATE_SQL, load_landing_zone

runner = CliRunner()


class Killed(BaseException):
    """Simulates the process dying: not an Exception, so nothing in the script catches it."""


def old_capture(root, source, endpoint, partitions, stamp, payload=None, params=None, url=None):
    """Write one capture in the old layout, with a consistent old-style sidecar."""
    params = params if params is not None else dict(partitions)  # distinct keys per entity
    folder = root / source / endpoint
    for key, value in partitions.items():
        folder = folder / f"{key}={value}"
    folder.mkdir(parents=True, exist_ok=True)
    stem = folder / f"fetched_at={stamp}"
    body = json.dumps(payload if payload is not None else {"stamp": stamp, "p": partitions})
    meta = {
        "source": source,
        "endpoint": endpoint,
        "partitions": partitions,
        "url": url or f"https://example.test/{endpoint}",
        "params": params or {},
        "request_key": LandingZone.request_key(params),
        "fetched_at": stamp,
    }
    Path(f"{stem}.json").write_text(body)
    Path(f"{stem}.meta.json").write_text(json.dumps(meta, indent=2))
    return stem


def build_old_tree(root):
    """Five captures across four sources/endpoints, two of them one entity's history."""
    root.mkdir(parents=True, exist_ok=True)
    old_capture(root, "mlb", "boxscore", {"season": 2026, "game_pk": 1}, "20260926T000000Z")
    old_capture(root, "mlb", "boxscore", {"season": 2026, "game_pk": 1}, "20260927T000000Z")
    old_capture(root, "mlb", "boxscore", {"season": 2026, "game_pk": 2}, "20260926T000000Z")
    old_capture(
        root,
        "espn",
        "roster",
        {"season": 2026, "league_id": 7, "scoring_period": 1},
        "20260926T000000Z",
    )
    old_capture(root, "idmap", "player_id_map", {"provider": "sfbb"}, "20260926T000000Z")
    return root


def files_of(root):
    return sorted(p for p in root.rglob("*") if p.is_file())


def hashes(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files_of(root)
    }


def dirs_of(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir())


def identities(root):
    """(inode, mtime, size) of every file: a rewrite or a touch changes one of them."""
    return sorted((s.st_ino, s.st_mtime_ns, s.st_size) for s in (p.stat() for p in files_of(root)))


def read_only(root):
    for path in files_of(root):
        path.chmod(0o444)


def records(zone):
    text = (zone.migration_dir / JOURNAL_FILE).read_text()
    return [line.split("\t") for line in text.splitlines()]


def run(root, *flags):
    return migrate.main([str(root), *flags])


@pytest.fixture
def root(tmp_path):
    return build_old_tree(tmp_path / "raw")


@pytest.fixture
def zone(root):
    return LandingZone(root)


def migrated_copy(tmp_path, root):
    """The reference: an uninterrupted migration of an identical tree."""
    reference = tmp_path / "reference" / "raw"
    shutil.copytree(root, reference)
    assert run(reference) == 0
    return reference


def first_new_dir(zone):
    return min(p for p in zone.root.rglob("fetched_at=*") if p.is_dir())


# -- moving ---------------------------------------------------------------------------------


def test_migrates_a_tree_by_rename_alone(root, zone):
    """Catches a migration that rewrites a file, loses one, or produces a directory the
    package would not accept: contents, inodes and mtimes are checked on read-only files."""
    before_hashes, before = hashes(root), identities(root)
    read_only(root)
    assert run(root) == 0
    captures = [p for p in root.rglob("fetched_at=*") if p.is_dir()]
    assert len(captures) == 5
    for capture in captures:
        assert zone.check(capture) is None, capture
        assert sorted(p.name for p in capture.iterdir()) == ["meta.json", "payload.json"]
    assert sorted(hashes(root).values()) == sorted(before_hashes.values())
    assert identities(root) == before
    assert zone.layout_problem() is None
    assert not list(root.rglob("*.migrating"))


def test_a_lone_payload_is_left_where_it_is_and_reported(root, capsys):
    """Catches a spike payload paired with the wrong sidecar, moved, or not reported (R6.3)."""
    lone = root / "espn/settings/season=2026/fetched_at=20260926T000000Z.json"
    lone.parent.mkdir(parents=True)
    lone.write_text('{"spike": true}')
    assert run(root) == 0
    assert lone.read_text() == '{"spike": true}'
    out = capsys.readouterr().out
    assert "left behind" in out and "fetched_at=20260926T000000Z.json" in out
    assert "1 " in out


def test_a_pair_whose_sidecar_describes_another_path_is_left_behind(root, capsys):
    """Catches moving a capture the package would not accept as committed: the sidecar
    must describe its own path (the old equivalent of the shallow check)."""
    stem = old_capture(root, "mlb", "boxscore", {"season": 2026, "game_pk": 9}, "20260930T000000Z")
    meta = Path(f"{stem}.meta.json")
    meta.write_text(meta.read_text().replace('"game_pk": 9', '"game_pk": 10'))
    assert run(root) == 0
    assert Path(f"{stem}.json").exists() and meta.exists()
    assert "left behind" in capsys.readouterr().out


def test_dry_run_moves_nothing_writes_no_journal_and_takes_no_lock(root, zone, capsys):
    """Catches a dry run that moves, journals or locks, or that hides the left-behind (R6.1)."""
    lone = root / "espn/settings/x.json"
    lone.parent.mkdir(parents=True)
    lone.write_text("{}")
    before = hashes(root)
    assert run(root, "--dry-run") == 0
    assert hashes(root) == before
    assert not zone.migration_dir.exists() and not zone.lock_path.exists()
    out = capsys.readouterr().out
    assert "5 captures" in out and "x.json" in out


def test_a_second_run_after_finished_does_nothing(root, zone):
    """Catches double nesting, or a journal that grows on a no-op run (R6.4)."""
    assert run(root) == 0
    tree, journal = hashes(root), (zone.migration_dir / JOURNAL_FILE).read_bytes()
    dirs = dirs_of(root)
    assert run(root) == 0
    assert hashes(root) == tree and dirs_of(root) == dirs
    assert (zone.migration_dir / JOURNAL_FILE).read_bytes() == journal


def test_an_existing_final_directory_stops_the_run_before_anything_moves(root, zone):
    """Catches overwriting or merging into a directory that is already there."""
    stem = old_capture(root, "mlb", "boxscore", {"season": 2026, "game_pk": 9}, "20260930T000000Z")
    Path(stem).mkdir()
    before = hashes(root)
    assert run(root) != 0
    assert hashes(root) == before
    assert not (zone.migration_dir / JOURNAL_FILE).exists()


# -- the journal -----------------------------------------------------------------------------


def test_the_journal_lives_beside_the_root_and_brackets_each_capture(root, zone):
    """Catches a journal inside the scanned tree, or records out of order (R6.2)."""
    assert run(root) == 0
    assert zone.migration_dir == root.parent / "raw_migration"
    assert (zone.migration_dir / ".gitignore").read_text() == "*\n"
    rows = records(zone)
    assert rows[0] == ["start"] and rows[-1] == ["finished"]
    body = rows[1:-1]
    assert len(body) == 10
    for begin, done in zip(body[0::2], body[1::2], strict=True):
        assert begin[0] == "begin" and done[0] == "done"
        assert begin[1] == done[1] and not begin[1].endswith(".json")
        assert begin[2] == begin[1] and not Path(begin[1]).is_absolute()
        assert (root / begin[2] / "payload.json").exists()


def test_the_journal_is_ignored_by_git_wherever_the_root_is(tmp_path):
    """Catches a list of private paths (the league id) left where git would commit it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    root = build_old_tree(repo / "anywhere" / "landing")
    assert run(root) == 0
    journal = LandingZone(root).migration_dir / JOURNAL_FILE
    assert (
        subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", str(journal)]).returncode == 0
    )


# -- resumption ------------------------------------------------------------------------------

KILL_AFTER_STEP = [0, 1, 2, 3]


def kill_after(monkeypatch, steps):
    """Die just before step `steps + 1` (mkdir, rename, rename, rename) of the whole run."""
    count = {"n": 0}

    def wrap(real):
        def inner(*args):
            if count["n"] >= steps:
                raise Killed
            count["n"] += 1
            return real(*args)

        return inner

    monkeypatch.setattr(migrate, "_mkdir", wrap(migrate._mkdir))
    monkeypatch.setattr(migrate, "_rename", wrap(migrate._rename))


def kill_before_done(monkeypatch):
    """Die with the final rename done and `done` not written: step four's own gap."""
    real = migrate.Journal.record

    def record(self, *fields):
        if fields[0] == "done":
            raise Killed
        return real(self, *fields)

    monkeypatch.setattr(migrate.Journal, "record", record)


def interrupt(monkeypatch, root, state):
    with monkeypatch.context() as killed:
        if state == "done_not_written":
            kill_before_done(killed)
        else:
            kill_after(killed, state)
        with pytest.raises(Killed):
            run(root)


STATES = [*KILL_AFTER_STEP, "done_not_written"]
STATE_IDS = [
    "nothing_moved",
    "migrating_dir_empty",
    "payload_moved",
    "both_moved",
    "final_rename_done",
]


@pytest.mark.parametrize("state", STATES, ids=STATE_IDS)
def test_a_killed_migration_is_completed_by_the_next_run(tmp_path, monkeypatch, root, zone, state):
    """Catches a capture left in pieces by a kill at any of its four steps, or a second run
    that does not finish it before going on, or one that leaves a different tree (R6.6)."""
    reference = migrated_copy(tmp_path, root)
    interrupt(monkeypatch, root, state)
    problem = zone.layout_problem()
    assert problem is not None and "in progress" in problem
    begun = [r for r in records(zone) if r[0] == "begin"]
    done = [r for r in records(zone) if r[0] == "done"]
    assert len(begun) == 1 and len(done) == 0

    assert run(root) == 0
    assert hashes(root) == hashes(reference)
    assert dirs_of(root) == dirs_of(reference)
    assert zone.layout_problem() is None
    rows = records(zone)
    assert [r[0] for r in rows].count("start") == 1, "a resumed run continues the bracket"
    assert rows[-1] == ["finished"]
    assert sorted(r[1] for r in rows if r[0] == "done") == sorted(
        r[1] for r in rows if r[0] == "begin"
    )
    assert len([r for r in rows if r[0] == "begin"]) == 5


def test_the_interrupted_capture_is_finished_before_a_new_one_begins(monkeypatch, root, zone):
    """Catches a resumed run that starts new captures before completing the begun one."""
    interrupt(monkeypatch, root, 2)
    assert run(root) == 0
    rows = [r for r in records(zone) if r[0] in ("begin", "done")]
    assert rows[0][0] == "begin" and rows[1][0] == "done" and rows[0][1] == rows[1][1]


# -- reversal --------------------------------------------------------------------------------


def test_reverse_restores_the_original_tree_byte_for_byte(root, zone):
    """Catches an irreversible move, a changed byte or a directory left behind (R6.2)."""
    before_hashes, before_dirs = hashes(root), dirs_of(root)
    assert run(root) == 0
    assert run(root, "--reverse") == 0
    assert hashes(root) == before_hashes
    assert dirs_of(root) == before_dirs
    assert records(zone)[-1] == ["reversed"]


@pytest.mark.parametrize("state", STATES, ids=STATE_IDS)
def test_reverse_from_an_interrupted_state(monkeypatch, root, zone, state):
    """Catches a reversal that only works from a finished migration."""
    before_hashes, before_dirs = hashes(root), dirs_of(root)
    interrupt(monkeypatch, root, state)
    assert run(root, "--reverse") == 0
    assert hashes(root) == before_hashes
    assert dirs_of(root) == before_dirs
    assert records(zone)[-1] == ["reversed"]


def test_migrating_again_after_a_reversal_gives_the_same_result(tmp_path, root, zone):
    """Catches a reversed tree that cannot be migrated again, or migrates differently."""
    reference = migrated_copy(tmp_path, root)
    assert run(root) == 0
    assert run(root, "--reverse") == 0
    assert run(root) == 0
    assert hashes(root) == hashes(reference)
    assert dirs_of(root) == dirs_of(reference)
    assert [r[0] for r in records(zone)].count("start") == 2
    assert records(zone)[-1] == ["finished"]
    assert run(root, "--reverse") == 0, "the second reversal undoes the second bracket"
    assert not any(p.is_dir() for p in root.rglob("fetched_at=*"))


def test_reverse_with_no_journal_is_an_error_that_changes_nothing(root):
    """Catches a reverse that guesses at what to undo."""
    before = hashes(root)
    assert run(root, "--reverse") != 0
    assert hashes(root) == before


# -- the interlock, end to end ---------------------------------------------------------------


@pytest.fixture
def requested(monkeypatch):
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


def cli_tree(root):
    """An old-layout tree whose schedule lists one final game that has not landed."""
    game = {
        "gamePk": 11,
        "season": "2026",
        "officialDate": "2026-04-14",
        "gameType": "R",
        "status": {"abstractGameState": "Final", "detailedState": "Final"},
    }
    old_capture(
        root,
        "mlb",
        "schedule",
        {"season": 2026, "game_type": "R"},
        "20260926T000000Z",
        payload={"dates": [{"date": "2026-04-14", "games": [game]}]},
        params={"season": 2026},
        url="https://statsapi.mlb.com/api/v1/schedule",
    )


def backfill(root):
    return runner.invoke(
        app, ["backfill", "mlb", "--season", "2026", "--only", "boxscore", "--raw-root", str(root)]
    )


def repair(root):
    return runner.invoke(app, ["repair", "--raw-root", str(root), "--dry-run"])


def test_backfill_and_repair_refuse_until_the_migration_is_finished(
    monkeypatch, tmp_path, requested
):
    """Catches a backfill or sweep running on a half-moved, reversed or unmigrated tree,
    and one that stays refused after the migration finishes (R6.7)."""
    root = tmp_path / "raw"
    cli_tree(root)
    zone = LandingZone(root)

    for command in (backfill, repair):
        refused = command(root)
        assert refused.exit_code != 0 and "migrate_landing_layout.py" in refused.output

    interrupt(monkeypatch, root, 2)
    with pytest.raises(NotMigrated):
        zone.sweep("20260927T000000Z")
    for command in (backfill, repair):
        refused = command(root)
        assert refused.exit_code != 0 and "migrate_landing_layout.py" in refused.output
    assert requested == []

    assert run(root) == 0
    assert repair(root).exit_code == 0
    done = backfill(root)
    assert done.exit_code == 0, done.output
    assert requested == ["/api/v1/game/11/boxscore"]


def test_after_a_reversal_the_package_refuses_again(tmp_path):
    """Catches a reversed tree that the package would treat as usable (R6.7)."""
    root = tmp_path / "raw"
    cli_tree(root)
    assert run(root) == 0
    assert repair(root).exit_code == 0
    assert run(root, "--reverse") == 0
    refused = repair(root)
    assert refused.exit_code != 0 and "migrate_landing_layout.py" in refused.output


# -- verify_migration: files -----------------------------------------------------------------


def manifest_of(root, path):
    lines = [f"{h}  ./{rel}" for rel, h in sorted(hashes(root).items())]
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def migrated(tmp_path, root, zone):
    manifest = manifest_of(root, tmp_path / "manifest.txt")
    assert run(root) == 0
    return manifest, zone.migration_dir / JOURNAL_FILE


def verify_files(root, migrated, deleted=None, tmp_path=None):
    manifest, journal = migrated
    argv = ["files", "--manifest", str(manifest), "--journal", str(journal), "--root", str(root)]
    if deleted is not None:
        listing = manifest.parent / "deleted.txt"
        listing.write_text("\n".join(deleted) + "\n")
        argv += ["--deleted", str(listing)]
    return verify.main(argv)


def test_verify_files_passes_on_a_correct_migration(root, migrated, capsys):
    """Catches a verifier that rejects a good migration."""
    assert verify_files(root, migrated) == 0
    assert "10 manifest lines" in capsys.readouterr().out


def test_verify_files_fails_on_a_changed_byte(root, migrated):
    """Catches a verifier that checks presence but not contents."""
    target = first_new_dir(LandingZone(root)) / "payload.json"
    target.chmod(0o644)
    target.write_bytes(target.read_bytes() + b" ")
    assert verify_files(root, migrated) != 0


def test_verify_files_fails_on_a_missing_file(root, migrated):
    """Catches a file lost in the move going unnoticed."""
    (first_new_dir(LandingZone(root)) / "meta.json").unlink()
    assert verify_files(root, migrated) != 0


def test_verify_files_fails_on_an_unexpected_file(root, migrated):
    """Catches a file under the root that no manifest line accounts for."""
    (root / "stray.json").write_text("{}")
    assert verify_files(root, migrated) != 0


def test_verify_files_fails_on_a_manifest_line_that_maps_nowhere(root, migrated, tmp_path):
    """Catches a manifest entry the journal never moved passing silently."""
    manifest, _journal = migrated
    with manifest.open("a") as handle:
        handle.write(f"{'0' * 64}  ./mlb/boxscore/season=2026/game_pk=99/fetched_at=1.json\n")
    assert verify_files(root, migrated) != 0


def test_verify_files_accounts_for_deleted_paths_both_ways(root, tmp_path, zone):
    """Catches a deleted path that is still there passing, or a gone one failing (the 201
    spike payloads are in the manifest and deleted by #21)."""
    spike = root / "espn/settings/season=2026/fetched_at=20260926T000000Z.json"
    spike.parent.mkdir(parents=True)
    spike.write_text('{"spike": 1}')
    manifest = manifest_of(root, tmp_path / "manifest.txt")
    spike.unlink()
    assert run(root) == 0
    pair = (manifest, zone.migration_dir / JOURNAL_FILE)
    relative = "espn/settings/season=2026/fetched_at=20260926T000000Z.json"
    assert verify_files(root, pair) != 0, "a manifest line neither mapped nor listed as deleted"
    assert verify_files(root, pair, deleted=[f"data/raw/{relative}"]) == 0
    assert verify_files(root, pair, deleted=[relative]) == 0
    spike.write_text('{"spike": 1}')
    assert verify_files(root, pair, deleted=[f"data/raw/{relative}"]) != 0


def test_verify_files_fails_when_the_journal_is_not_finished(tmp_path, monkeypatch, root, zone):
    """Catches verifying a migration that is still in progress."""
    manifest = manifest_of(root, tmp_path / "manifest.txt")
    interrupt(monkeypatch, root, 3)
    assert verify_files(root, (manifest, zone.migration_dir / JOURNAL_FILE)) != 0


# -- verify_migration: raw rows --------------------------------------------------------------

OLD_PREFIX = "data/raw"


def old_rows(root):
    """What the pre-migration loader stored: payload text, and file_path as given."""
    rows = []
    for payload in sorted(p for p in root.rglob("*.json") if not p.name.endswith(".meta.json")):
        meta = json.loads(Path(f"{str(payload)[: -len('.json')]}.meta.json").read_text())
        rows.append(
            (
                meta["source"],
                meta["endpoint"],
                LandingZone.request_path(meta["url"]),
                meta["request_key"],
                meta["fetched_at"],
                json.dumps(meta["partitions"]),
                json.dumps(json.loads(payload.read_text())),
                f"{OLD_PREFIX}/{payload.relative_to(root)}",
            )
        )
    return rows


@pytest.fixture
def warehouses(tmp_path, root, zone):
    old_db, new_db = tmp_path / "old_wh.duckdb", tmp_path / "new_wh.duckdb"
    with duckdb.connect(str(old_db)) as con:
        con.execute(CREATE_SQL)
        con.executemany(
            "insert into raw.api_responses values (?, ?, ?, ?, ?, ?, ?, ?)", old_rows(root)
        )
    assert run(root) == 0
    with duckdb.connect(str(new_db)) as con:
        assert load_landing_zone(con, zone) == 5
    return old_db, new_db, zone.migration_dir / JOURNAL_FILE


def verify_rows(root, warehouses):
    old_db, new_db, journal = warehouses
    return verify.main(
        [
            "rows",
            "--old-db",
            str(old_db),
            "--new-db",
            str(new_db),
            "--journal",
            str(journal),
            "--old-root-prefix",
            OLD_PREFIX,
            "--new-root-prefix",
            str(root),
        ]
    )


def edit_new(warehouses, sql):
    with duckdb.connect(str(warehouses[1])) as con:
        con.execute(sql)


def test_verify_rows_passes_on_equal_warehouses(root, warehouses, capsys):
    """Catches a comparison that rejects a faithful rebuild."""
    assert verify_rows(root, warehouses) == 0
    assert "5 matched, 0 changed, 0 missing, 0 extra" in capsys.readouterr().out


def test_verify_rows_fails_on_a_changed_payload(root, warehouses):
    """Catches a raw row changing while every model happened to agree."""
    edit_new(
        warehouses,
        "update raw.api_responses set payload = '{\"x\": 1}' "
        "where request_path like '%player_id_map'",
    )
    assert verify_rows(root, warehouses) != 0


def test_verify_rows_fails_on_a_changed_partition(root, warehouses):
    """Catches a changed partitions column going unnoticed."""
    edit_new(
        warehouses,
        'update raw.api_responses set partitions = \'{"provider": "x"}\' '
        "where request_path like '%player_id_map'",
    )
    assert verify_rows(root, warehouses) != 0


def test_verify_rows_fails_on_a_file_path_that_does_not_map(root, warehouses):
    """Catches a row whose file_path is not the old one mapped through the journal."""
    edit_new(
        warehouses,
        "update raw.api_responses set file_path = file_path || 'x' "
        "where request_path like '%player_id_map'",
    )
    assert verify_rows(root, warehouses) != 0


def test_verify_rows_fails_on_a_missing_and_an_extra_row(root, warehouses, capsys):
    """Catches a row dropped or invented by the rebuild."""
    edit_new(warehouses, "delete from raw.api_responses where request_path like '%player_id_map'")
    assert verify_rows(root, warehouses) != 0
    assert "1 missing" in capsys.readouterr().out
    edit_new(
        warehouses,
        "insert into raw.api_responses select 'mlb', 'x', '/x', '', 'S', '{}', '{}', 'p'",
    )
    assert verify_rows(root, warehouses) != 0
    assert "1 extra" in capsys.readouterr().out
