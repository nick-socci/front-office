"""Tests for the docs-site assembler (spec 0013 R1.3, R1.4; spec 0133 R1.6 to R1.10).

Each builds a tiny fake dbt target dir and a tiny fake ADR directory, and runs the real
assemble step on them.
"""

import json
from pathlib import Path

import build_docs_site as site

RUN_ID = "11111111-2222-3333-4444-555555555555"
USER_ID = "66666666-7777-8888-9999-aaaaaaaaaaaa"
STRAY = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
FOUR = {"index.html", "manifest.json", "catalog.json", "decisions.html"}


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


def make_adrs(tmp_path: Path, title: str = "A title", status: str | None = "accepted") -> Path:
    """A one-ADR directory under tmp_path; `status=None` leaves the Status line out."""
    adr_dir = tmp_path / "docs" / "adr"
    spec = tmp_path / "docs" / "specs" / "0001-x" / "design.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("# spec\n")
    adr_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"# 0001. {title}", ""]
    if status is not None:
        lines.append(f"- Status: {status}")
    lines += ["- Date: 2026-10-12", "- Spec: [0001-x](../specs/0001-x/design.md)", "", "## Context"]
    (adr_dir / "0001-x.md").write_text("\n".join(lines) + "\n")
    return adr_dir


def names(path: Path) -> set[str]:
    return {p.name for p in path.iterdir()}


def test_a_clean_site_passes_and_holds_exactly_four_files(tmp_path, capsys):
    """Catches dbt's own ids failing the GUID check, or a listing other than the four files."""
    target = make_target(tmp_path)
    out = tmp_path / "site"
    assert site.assemble(target, out, make_adrs(tmp_path)) == 0
    assert names(out) == FOUR
    assert "1 models" in capsys.readouterr().out


def test_other_target_files_are_not_copied(tmp_path):
    """Catches run_results.json (which can hold paths and timings) reaching the site."""
    target = make_target(tmp_path)
    (target / "run_results.json").write_text("{}")
    out = tmp_path / "site"
    assert site.assemble(target, out, make_adrs(tmp_path)) == 0
    assert names(out) == FOUR


def test_a_non_empty_out_dir_is_refused(tmp_path, capsys):
    """Catches the assembler publishing into, or clearing, a directory with other things."""
    target = make_target(tmp_path)
    out = tmp_path / "site"
    out.mkdir()
    (out / "keep.txt").write_text("mine")
    assert site.assemble(target, out, make_adrs(tmp_path)) == 1
    assert names(out) == {"keep.txt"}
    assert "not empty" in capsys.readouterr().out


def test_a_catalog_node_in_another_database_fails_and_leaves_nothing(tmp_path, capsys):
    """Catches real-season catalog metadata reaching the site, and a failed run leaving files."""
    target = make_target(tmp_path, database="warehouse")
    out = tmp_path / "site"
    assert site.assemble(target, out, make_adrs(tmp_path)) == 1
    assert "warehouse" in capsys.readouterr().out
    assert not out.exists()


def test_a_failed_run_in_an_existing_empty_out_dir_leaves_it_empty(tmp_path):
    """Catches the cleanup deleting a directory the caller made, or leaving files in it."""
    target = make_target(tmp_path, database="warehouse")
    out = tmp_path / "site"
    out.mkdir()
    assert site.assemble(target, out, make_adrs(tmp_path)) == 1
    assert out.exists()
    assert list(out.iterdir()) == []


def test_a_forbidden_json_key_fails(tmp_path, capsys):
    """Catches a league-member key appearing in the manifest."""
    target = make_target(tmp_path, {"owners": []})
    assert site.assemble(target, tmp_path / "site", make_adrs(tmp_path)) == 1
    assert "owners" in capsys.readouterr().out


def test_a_forbidden_word_in_prose_does_not_fail(tmp_path):
    """Catches the key check flagging descriptions that say what is deliberately not kept."""
    target = make_target(tmp_path, {"description": "never selects owners or displayName"})
    assert site.assemble(target, tmp_path / "site", make_adrs(tmp_path)) == 0


def test_a_guid_in_a_description_fails_without_being_printed(tmp_path, capsys):
    """Catches an account GUID reaching the site, and the log echoing it whole."""
    target = make_target(tmp_path, {"description": f"account {{{STRAY}}}"})
    assert site.assemble(target, tmp_path / "site", make_adrs(tmp_path)) == 1
    out = capsys.readouterr().out
    assert STRAY[:8] in out
    assert STRAY not in out


def test_a_missing_catalog_fails_naming_it(tmp_path, capsys):
    """Catches docs generate having been run without the catalog step."""
    target = make_target(tmp_path)
    (target / "catalog.json").unlink()
    out = tmp_path / "site"
    assert site.assemble(target, out, make_adrs(tmp_path)) == 1
    assert "catalog.json" in capsys.readouterr().out
    assert not out.exists()


def test_dbts_own_id_in_a_description_still_fails(tmp_path):
    """Catches an exemption by value: dbt's ids are allowed in two metadata fields only."""
    target = make_target(tmp_path, {"description": f"copied from run {RUN_ID}"})
    assert site.assemble(target, tmp_path / "site", make_adrs(tmp_path)) == 1


def test_a_guid_in_index_html_fails_even_if_it_is_dbts_own(tmp_path):
    """Catches a GUID reaching the page itself, where no value is exempt."""
    target = make_target(tmp_path)
    (target / "index.html").write_text(f"<html>{RUN_ID}</html>")
    assert site.assemble(target, tmp_path / "site", make_adrs(tmp_path)) == 1


def test_a_guid_in_a_list_or_a_key_fails(tmp_path):
    """Catches a GUID that is not a dict's string value: an item of a list, or a key."""
    in_list = make_target(tmp_path / "a", {"tags": [STRAY]})
    assert site.assemble(in_list, tmp_path / "a" / "site", make_adrs(tmp_path / "a")) == 1
    as_key = make_target(tmp_path / "b", {"meta": {STRAY: 1}})
    assert site.assemble(as_key, tmp_path / "b" / "site", make_adrs(tmp_path / "b")) == 1


def test_a_root_key_spelled_like_the_exempt_path_is_not_exempt(tmp_path):
    """Catches a path compared as dotted text: one key named `metadata.invocation_id`."""
    target = make_target(tmp_path)
    manifest = json.loads((target / "manifest.json").read_text())
    manifest["metadata.invocation_id"] = STRAY
    (target / "manifest.json").write_text(json.dumps(manifest))
    assert site.assemble(target, tmp_path / "site", make_adrs(tmp_path)) == 1


def test_a_duplicate_key_fails_naming_it(tmp_path, capsys):
    """Catches a GUID in a repeated key's earlier value, which parsing silently drops."""
    target = make_target(tmp_path)
    text = (target / "manifest.json").read_text()
    hidden = f'{{"description": "{STRAY}", "description": "...", '
    (target / "manifest.json").write_text(hidden + text[1:])
    assert site.assemble(target, tmp_path / "site", make_adrs(tmp_path)) == 1
    assert "duplicate key description" in capsys.readouterr().out


def assembled_site(tmp_path: Path) -> Path:
    out = tmp_path / "site"
    assert site.assemble(make_target(tmp_path), out, make_adrs(tmp_path)) == 0
    return out


def test_a_fifth_file_in_the_site_fails_the_check_naming_it(tmp_path):
    """Catches the site check no longer holding the file list (R1.7)."""
    out = assembled_site(tmp_path)
    (out / "extra.txt").write_text("x")
    problems = site.check_site(out)
    assert any("extra.txt" in problem for problem in problems)


def test_a_site_missing_decisions_html_fails_the_check_naming_it(tmp_path):
    """Catches the site being publishable without the generated page (R1.7)."""
    out = assembled_site(tmp_path)
    (out / "decisions.html").unlink()
    problems = site.check_site(out)
    assert any("decisions.html" in problem for problem in problems)


def test_a_guid_in_decisions_html_fails_the_check(tmp_path):
    """Catches the generated page being exempt from the GUID check."""
    out = assembled_site(tmp_path)
    (out / "decisions.html").write_text(f"<html>{STRAY}</html>")
    problems = site.check_site(out)
    assert any("decisions.html" in problem for problem in problems)


def test_a_guid_in_an_adr_title_fails_without_being_printed(tmp_path, capsys):
    """Catches a GUID in ADR text reaching the page, and the log echoing it whole (R1.7)."""
    target = make_target(tmp_path)
    out = tmp_path / "site"
    assert site.assemble(target, out, make_adrs(tmp_path, title=f"For {{{STRAY}}}")) == 1
    printed = capsys.readouterr().out
    assert "decisions.html" in printed
    assert STRAY[:8] in printed
    assert STRAY not in printed
    assert not out.exists()


def test_an_adr_with_no_status_fails_naming_the_file_and_creates_nothing(tmp_path, capsys):
    """Catches a bad ADR header publishing a page, or leaving an output directory (R1.6)."""
    target = make_target(tmp_path)
    out = tmp_path / "site"
    assert site.assemble(target, out, make_adrs(tmp_path, status=None)) == 1
    assert "0001-x.md" in capsys.readouterr().out
    assert not out.exists()


def test_a_missing_adr_directory_fails_naming_it(tmp_path, capsys):
    """Catches an empty decisions page published because a path was wrong (R1.10)."""
    target = make_target(tmp_path)
    missing = tmp_path / "nope"
    out = tmp_path / "site"
    assert site.assemble(target, out, missing) == 1
    assert str(missing) in capsys.readouterr().out
    assert not out.exists()


def test_an_adr_directory_with_only_a_readme_fails_naming_it(tmp_path, capsys):
    """Catches README.md alone being taken as a directory of decisions (R1.10)."""
    target = make_target(tmp_path)
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    (adr_dir / "README.md").write_text("# ADRs\n")
    out = tmp_path / "site"
    assert site.assemble(target, out, adr_dir) == 1
    assert str(adr_dir) in capsys.readouterr().out
    assert not out.exists()


def test_a_planted_decisions_html_is_not_what_ends_up_in_the_site(tmp_path):
    """Catches the page being copied from the target directory instead of generated (R1.8)."""
    target = make_target(tmp_path)
    (target / "decisions.html").write_text("<html>planted</html>")
    out = tmp_path / "site"
    assert site.assemble(target, out, make_adrs(tmp_path)) == 0
    page = (out / "decisions.html").read_text()
    assert "planted" not in page
    assert "<table>" in page
    assert "A title" in page
