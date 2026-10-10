"""Tests for the docs-site assembler (spec 0013 R1.3, R1.4).

Each builds a tiny fake dbt target dir and runs the real assemble step on it.
"""

import json
from pathlib import Path

import build_docs_site as site

RUN_ID = "11111111-2222-3333-4444-555555555555"
USER_ID = "66666666-7777-8888-9999-aaaaaaaaaaaa"
STRAY = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
THREE = {"index.html", "manifest.json", "catalog.json"}


def make_target(tmp_path: Path, manifest_extra: dict | None = None, database: str = "ci") -> Path:
    target = tmp_path / "target"
    target.mkdir(parents=True)
    (target / "index.html").write_text("<html></html>")
    node = {"resource_type": "model", "description": "..."}
    node.update(manifest_extra or {})
    manifest = {
        "metadata": {"invocation_id": RUN_ID, "user_id": USER_ID},
        "nodes": {"model.x.a": node},
        "sources": {},
        "exposures": {},
        "unit_tests": {},
    }
    catalog = {
        "metadata": {"invocation_id": RUN_ID},
        "nodes": {"model.x.a": {"metadata": {"database": database}}},
        "sources": {},
    }
    (target / "manifest.json").write_text(json.dumps(manifest))
    (target / "catalog.json").write_text(json.dumps(catalog))
    return target


def names(path: Path) -> set[str]:
    return {p.name for p in path.iterdir()}


def test_a_clean_site_passes_and_holds_exactly_three_files(tmp_path, capsys):
    """Catches dbt's own invocation/user ids failing the GUID check, or a wrong listing."""
    target = make_target(tmp_path)
    out = tmp_path / "site"
    assert site.assemble(target, out) == 0
    assert names(out) == THREE
    assert "1 models" in capsys.readouterr().out


def test_other_target_files_are_not_copied(tmp_path):
    """Catches run_results.json (which can hold paths and timings) reaching the site."""
    target = make_target(tmp_path)
    (target / "run_results.json").write_text("{}")
    out = tmp_path / "site"
    assert site.assemble(target, out) == 0
    assert names(out) == THREE


def test_a_non_empty_out_dir_is_refused(tmp_path, capsys):
    """Catches the assembler publishing into, or clearing, a directory with other things."""
    target = make_target(tmp_path)
    out = tmp_path / "site"
    out.mkdir()
    (out / "keep.txt").write_text("mine")
    assert site.assemble(target, out) == 1
    assert names(out) == {"keep.txt"}
    assert "not empty" in capsys.readouterr().out


def test_a_catalog_node_in_another_database_fails_and_leaves_nothing(tmp_path, capsys):
    """Catches real-season catalog metadata reaching the site, and a failed run leaving files."""
    target = make_target(tmp_path, database="warehouse")
    out = tmp_path / "site"
    assert site.assemble(target, out) == 1
    assert "warehouse" in capsys.readouterr().out
    assert not out.exists()


def test_a_failed_run_in_an_existing_empty_out_dir_leaves_it_empty(tmp_path):
    """Catches the cleanup deleting a directory the caller made, or leaving files in it."""
    target = make_target(tmp_path, database="warehouse")
    out = tmp_path / "site"
    out.mkdir()
    assert site.assemble(target, out) == 1
    assert out.exists()
    assert list(out.iterdir()) == []


def test_a_forbidden_json_key_fails(tmp_path, capsys):
    """Catches a league-member key appearing in the manifest."""
    target = make_target(tmp_path, {"owners": []})
    assert site.assemble(target, tmp_path / "site") == 1
    assert "owners" in capsys.readouterr().out


def test_a_forbidden_word_in_prose_does_not_fail(tmp_path):
    """Catches the key check flagging descriptions that say what is deliberately not kept."""
    target = make_target(tmp_path, {"description": "never selects owners or displayName"})
    assert site.assemble(target, tmp_path / "site") == 0


def test_a_guid_in_a_description_fails_without_being_printed(tmp_path, capsys):
    """Catches an account GUID reaching the site, and the log echoing it whole."""
    target = make_target(tmp_path, {"description": f"account {{{STRAY}}}"})
    assert site.assemble(target, tmp_path / "site") == 1
    out = capsys.readouterr().out
    assert STRAY[:8] in out
    assert STRAY not in out


def test_a_missing_catalog_fails_naming_it(tmp_path, capsys):
    """Catches docs generate having been run without the catalog step."""
    target = make_target(tmp_path)
    (target / "catalog.json").unlink()
    out = tmp_path / "site"
    assert site.assemble(target, out) == 1
    assert "catalog.json" in capsys.readouterr().out
    assert not out.exists()


def test_dbts_own_id_in_a_description_still_fails(tmp_path):
    """Catches an exemption by value: dbt's ids are allowed in two metadata fields only."""
    target = make_target(tmp_path, {"description": f"copied from run {RUN_ID}"})
    assert site.assemble(target, tmp_path / "site") == 1


def test_a_guid_in_index_html_fails_even_if_it_is_dbts_own(tmp_path):
    """Catches a GUID reaching the page itself, where no value is exempt."""
    target = make_target(tmp_path)
    (target / "index.html").write_text(f"<html>{RUN_ID}</html>")
    assert site.assemble(target, tmp_path / "site") == 1


def test_a_guid_in_a_list_or_a_key_fails(tmp_path):
    """Catches a GUID that is not a dict's string value: an item of a list, or a key."""
    in_list = make_target(tmp_path / "a", {"tags": [STRAY]})
    assert site.assemble(in_list, tmp_path / "a" / "site") == 1
    as_key = make_target(tmp_path / "b", {"meta": {STRAY: 1}})
    assert site.assemble(as_key, tmp_path / "b" / "site") == 1
