"""Tests for the ADR header reader (spec 0133 R2, R1.10, R3.2).

Each builds a tiny fake ADR directory under tmp_path; the last cases read the real one.
"""

from pathlib import Path

import pytest

import adr_index

REPO = Path(__file__).resolve().parents[2]
SPEC_LINK = "[0001-x](../specs/0001-x/design.md)"


def write_adr(
    tmp_path: Path,
    number: str = "0001",
    slug: str = "x",
    heading: str | None = None,
    lines: list[str] | None = None,
) -> Path:
    """Write docs/adr/<number>-<slug>.md; `lines` replaces the default header lines."""
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    spec = tmp_path / "docs" / "specs" / "0001-x" / "design.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("# spec\n")
    if lines is None:
        lines = ["- Status: accepted", "- Date: 2026-10-12", f"- Spec: {SPEC_LINK}"]
    head = heading if heading is not None else f"# {number}. A title"
    path = adr_dir / f"{number}-{slug}.md"
    path.write_text("\n".join([head, "", *lines, "", "## Context", "", "Body.", ""]))
    return path


def with_status(status: str) -> list[str]:
    return [f"- Status: {status}", "- Date: 2026-10-12", f"- Spec: {SPEC_LINK}"]


def fails(path: Path, *reason: str) -> None:
    with pytest.raises(adr_index.AdrError) as exc:
        adr_index.read_adr(path)
    text = str(exc.value)
    assert path.name in text
    for part in reason:
        assert part in text


def test_a_well_formed_header_reads_every_field(tmp_path):
    """Catches a field read from the wrong line, or the status kept only in part."""
    path = write_adr(
        tmp_path,
        lines=[
            "- Status: accepted; see [0002](0002-y.md)",
            "- Date: 2026-10-12",
            f"- Spec: {SPEC_LINK} · Issue: #1",
            "- Amends: [0002](0002-y.md), for how many",
        ],
    )
    (path.parent / "0002-y.md").write_text("x")
    adr = adr_index.read_adr(path)
    assert adr.number == "0001"
    assert adr.title == "A title"
    assert adr.status == "accepted; see [0002](0002-y.md)"
    assert adr.status_word == "accepted"
    assert adr.date == "2026-10-12"
    assert adr.spec_text == "0001-x"
    assert adr.spec_target == "../specs/0001-x/design.md"
    assert adr.amends == "[0002](0002-y.md), for how many"
    assert adr.supersedes is None


def test_a_heading_not_in_the_form_fails(tmp_path):
    """Catches a file that does not open with `# NNNN. <title>` being read anyway."""
    fails(write_adr(tmp_path, heading="# ADR 1: a title"), "heading")


def test_a_heading_number_differing_from_the_filename_fails(tmp_path):
    """Catches a renamed or copied ADR whose heading still carries the old number."""
    fails(write_adr(tmp_path, number="0001", heading="# 0002. A title"), "0002", "0001")


@pytest.mark.parametrize("key", ["Status", "Date", "Spec"])
def test_a_missing_header_line_fails(tmp_path, key):
    """Catches a header without Status, Date or Spec publishing a blank cell."""
    lines = [ln for ln in with_status("accepted") if not ln.startswith(f"- {key}:")]
    fails(write_adr(tmp_path, lines=lines), key)


@pytest.mark.parametrize("key", ["Status", "Date", "Spec"])
def test_a_repeated_header_line_fails(tmp_path, key):
    """Catches a page showing one value where the file states two."""
    lines = with_status("accepted")
    extra = next(ln for ln in lines if ln.startswith(f"- {key}:"))
    fails(write_adr(tmp_path, lines=[*lines, extra]), key, "more than once")


@pytest.mark.parametrize("date", ["2026-1-5", "12/10/2026", "2026-10-12T00:00", "2026-13-45"])
def test_a_date_not_iso_fails(tmp_path, date):
    """Catches a date that is not a real YYYY-MM-DD."""
    lines = ["- Status: accepted", f"- Date: {date}", f"- Spec: {SPEC_LINK}"]
    fails(write_adr(tmp_path, lines=lines), "Date")


def test_a_spec_line_with_no_link_fails(tmp_path):
    """Catches a Spec line naming a spec in plain text, which nothing can check."""
    lines = ["- Status: accepted", "- Date: 2026-10-12", "- Spec: 0001-x"]
    fails(write_adr(tmp_path, lines=lines), "Spec", "link")


def test_a_spec_line_with_two_links_fails(tmp_path):
    """Catches a Spec line where the page could not tell which link is the spec."""
    two = f"{SPEC_LINK} and {SPEC_LINK}"
    lines = ["- Status: accepted", "- Date: 2026-10-12", f"- Spec: {two}"]
    fails(write_adr(tmp_path, lines=lines), "Spec", "one link")


@pytest.mark.parametrize(
    ("status", "word"),
    [
        ("accepted", "accepted"),
        ("accepted; x", "accepted"),
        ("accepted, x", "accepted"),
        ("proposed", "proposed"),
        ("superseded by [0002](0002-y.md)", "superseded"),
    ],
)
def test_status_words_read(tmp_path, status, word):
    """Catches `accepted;` counted as its own word, or a valid word refused."""
    path = write_adr(tmp_path, lines=with_status(status))
    (path.parent / "0002-y.md").write_text("x")
    assert adr_index.read_adr(path).status_word == word


@pytest.mark.parametrize("status", ["accepted.", "Accepted", "rejected"])
def test_a_bad_status_word_fails(tmp_path, status):
    """Catches a misspelt, capitalised or unknown status word passing."""
    fails(write_adr(tmp_path, lines=with_status(status)), "Status")


def test_a_repeated_number_fails_naming_both_files(tmp_path):
    """Catches two ADRs numbered alike merging without a git conflict."""
    write_adr(tmp_path, number="0001", slug="a")
    write_adr(tmp_path, number="0001", slug="b")
    with pytest.raises(adr_index.AdrError) as exc:
        adr_index.read_all(tmp_path / "docs" / "adr")
    assert "0001-a.md" in str(exc.value)
    assert "0001-b.md" in str(exc.value)


def test_read_all_is_in_number_order(tmp_path):
    """Catches listing in filesystem or write order instead of number order."""
    for n in ("0010", "0002", "0001"):
        write_adr(tmp_path, number=n)
    got = adr_index.read_all(tmp_path / "docs" / "adr")
    assert [a.number for a in got] == ["0001", "0002", "0010"]


@pytest.mark.parametrize("key", ["Status", "Spec", "Amends", "Supersedes"])
def test_a_relative_link_to_a_missing_file_fails(tmp_path, key):
    """Catches a header link that points nowhere."""
    lines = with_status("accepted")
    broken = "[0099](0099-gone.md)"
    if key == "Status":
        lines[0] = f"- Status: accepted; see {broken}"
    elif key == "Spec":
        lines[2] = f"- Spec: {broken}"
    else:
        lines.append(f"- {key}: {broken}")
    fails(write_adr(tmp_path, lines=lines), key, "0099-gone.md")


def test_an_absolute_link_is_not_checked(tmp_path):
    """Catches a URL being resolved as a file path."""
    lines = with_status("accepted; see [x](https://example.com/nothing.md)")
    assert adr_index.read_adr(write_adr(tmp_path, lines=lines)).status_word == "accepted"


def test_a_link_fragment_is_stripped_before_the_check(tmp_path):
    """Catches `file.md#section` being looked up as a file with that name."""
    path = write_adr(tmp_path, lines=with_status("accepted; see [x](0002-y.md#why)"))
    (path.parent / "0002-y.md").write_text("x")
    assert adr_index.read_adr(path).number == "0001"


def test_a_missing_directory_fails_naming_it(tmp_path):
    """Catches an empty table published because a path was wrong."""
    missing = tmp_path / "nope"
    with pytest.raises(adr_index.AdrError) as exc:
        adr_index.read_all(missing)
    assert str(missing) in str(exc.value)


def test_a_directory_with_only_a_readme_fails_naming_it(tmp_path):
    """Catches README.md alone being taken as a directory of decisions."""
    (tmp_path / "README.md").write_text("# ADRs\n")
    with pytest.raises(adr_index.AdrError) as exc:
        adr_index.read_all(tmp_path)
    assert str(tmp_path) in str(exc.value)


def test_the_real_adr_files_all_read():
    """Catches an ADR merged with a header the generator would misread."""
    adr_dir = REPO / "docs" / "adr"
    expected = sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    got = adr_index.read_all(adr_dir)
    assert [a.path for a in got] == expected
    assert len(got) > 0


def test_a_readme_linking_an_adr_file_is_caught(tmp_path):
    """Catches readme_links missing a link to an ADR file."""
    readme = tmp_path / "README.md"
    readme.write_text("| [0001](0001-x.md) | A title |\n")
    assert adr_index.readme_links(readme) == ["0001-x.md"]


def test_a_readme_without_adr_links_is_clean(tmp_path):
    """Catches readme_links flagging ordinary links."""
    readme = tmp_path / "README.md"
    readme.write_text("See [the site](https://example.com/decisions.html) and [x](../y.md).\n")
    assert adr_index.readme_links(readme) == []


def test_the_real_readme_lists_no_adr():
    """Catches the hand-kept table coming back (fails until the table is removed, task 6)."""
    assert adr_index.readme_links(REPO / "docs" / "adr" / "README.md") == []
