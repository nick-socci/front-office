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
    fails(write_adr(tmp_path, heading="# ADR 1: a title"), "does not open with a heading")


def test_a_heading_number_differing_from_the_filename_fails(tmp_path):
    """Catches a renamed or copied ADR whose heading still carries the old number."""
    fails(write_adr(tmp_path, number="0001", heading="# 0002. A title"), "0002", "0001")


@pytest.mark.parametrize("key", ["Status", "Date", "Spec"])
def test_a_missing_header_line_fails(tmp_path, key):
    """Catches a header without Status, Date or Spec publishing a blank cell."""
    lines = [ln for ln in with_status("accepted") if not ln.startswith(f"- {key}:")]
    fails(write_adr(tmp_path, lines=lines), f"no {key} line")


@pytest.mark.parametrize("key", ["Status", "Date", "Spec"])
def test_a_repeated_header_line_fails(tmp_path, key):
    """Catches a page showing one value where the file states two."""
    lines = with_status("accepted")
    extra = next(ln for ln in lines if ln.startswith(f"- {key}:"))
    fails(write_adr(tmp_path, lines=[*lines, extra]), key, "more than once")


@pytest.mark.parametrize(
    "date", ["2026-1-5", "12/10/2026", "2026-10-12T00:00", "2026-13-45", "20261012"]
)
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


@pytest.mark.parametrize(
    "target", ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,x", "vbscript:x"]
)
def test_a_link_with_a_scheme_other_than_http_fails(tmp_path, target):
    """Catches a header link that would run script from the published page."""
    lines = with_status(f"accepted; see [x]({target})")
    fails(write_adr(tmp_path, lines=lines), "Status", "http")


def test_link_syntax_inside_a_code_span_is_not_checked_as_a_link(tmp_path):
    """Catches text shown as code being refused as a link the page never makes."""
    lines = with_status("accepted; `[x](javascript:alert(1))` and `[y](0099-gone.md)` are code")
    assert adr_index.read_adr(write_adr(tmp_path, lines=lines)).status_word == "accepted"


def test_a_spec_link_inside_a_code_span_does_not_count(tmp_path):
    """Catches a Spec line whose only link-shaped text is code being read as its link."""
    lines = ["- Status: accepted", "- Date: 2026-10-12", f"- Spec: `{SPEC_LINK}`"]
    fails(write_adr(tmp_path, lines=lines), "Spec", "one link")


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
    assert "does not exist" in str(exc.value)


def test_a_directory_with_only_a_readme_fails_naming_it(tmp_path):
    """Catches README.md alone being taken as a directory of decisions."""
    (tmp_path / "README.md").write_text("# ADRs\n")
    with pytest.raises(adr_index.AdrError) as exc:
        adr_index.read_all(tmp_path)
    assert str(tmp_path) in str(exc.value)


def two_adrs(tmp_path: Path, naming_lines: list[str], named_status: str) -> Path:
    """ADR 0002 carries `naming_lines`; ADR 0001 carries `named_status`. Returns the dir."""
    write_adr(tmp_path, number="0001", slug="a", lines=with_status(named_status))
    write_adr(tmp_path, number="0002", slug="b", lines=naming_lines)
    return tmp_path / "docs" / "adr"


def naming(status: str, extra: str | None = None) -> list[str]:
    lines = with_status(status)
    return [*lines, extra] if extra else lines


def fails_all(adr_dir: Path, *reason: str) -> None:
    with pytest.raises(adr_index.AdrError) as exc:
        adr_index.read_all(adr_dir)
    for part in reason:
        assert part in str(exc.value)


@pytest.mark.parametrize("key", ["Amends", "Supersedes"])
def test_an_accepted_line_naming_an_adr_needs_a_back_link(tmp_path, key):
    """Catches an accepted Amends or Supersedes line the named ADR does not carry back."""
    adr_dir = two_adrs(tmp_path, naming("accepted", f"- {key}: [0001](0001-a.md)"), "accepted")
    fails_all(adr_dir, "0001-a.md", "0002-b.md")


@pytest.mark.parametrize("key", ["Amends", "Supersedes"])
def test_an_accepted_line_naming_an_adr_passes_with_the_back_link(tmp_path, key):
    """Catches a back-link being required in a form the named ADR already satisfies."""
    adr_dir = two_adrs(
        tmp_path,
        naming("accepted", f"- {key}: [0001](0001-a.md)"),
        "accepted; amended by [0002](0002-b.md)",
    )
    assert len(adr_index.read_all(adr_dir)) == 2


def test_a_status_clause_that_supersedes_needs_a_back_link(tmp_path):
    """Catches a `supersedes [X]` clause in Status being left one-way."""
    adr_dir = two_adrs(tmp_path, naming("accepted; supersedes [0001](0001-a.md)"), "accepted")
    fails_all(adr_dir, "0001-a.md", "0002-b.md")


def test_a_status_clause_naming_two_adrs_checks_both(tmp_path):
    """Catches only the first link of a clause being checked."""
    write_adr(tmp_path, number="0001", slug="a", lines=with_status("accepted; [0002](0002-b.md)"))
    write_adr(tmp_path, number="0003", slug="c", lines=with_status("accepted"))
    write_adr(
        tmp_path,
        number="0002",
        slug="b",
        lines=naming("accepted; supersedes [0001](0001-a.md), [0003](0003-c.md)"),
    )
    fails_all(tmp_path / "docs" / "adr", "0003-c.md", "0002-b.md")


def test_a_clause_that_is_superseded_by_names_nothing(tmp_path):
    """Catches `superseded by [X]` or `amended by [X]` in Status being read as naming X."""
    adr_dir = two_adrs(
        tmp_path, naming("accepted; its denominator is superseded by [0001](0001-a.md)"), "accepted"
    )
    assert len(adr_index.read_all(adr_dir)) == 2


def test_a_proposed_adr_naming_another_is_not_checked(tmp_path):
    """Catches a proposed amendment failing before it is accepted."""
    adr_dir = two_adrs(tmp_path, naming("proposed", "- Amends: [0001](0001-a.md)"), "accepted")
    assert len(adr_index.read_all(adr_dir)) == 2


def test_a_comma_clause_that_supersedes_needs_a_back_link(tmp_path):
    """Catches `accepted, supersedes [X]` being missed because the clause opens after a comma."""
    adr_dir = two_adrs(tmp_path, naming("accepted, supersedes [0001](0001-a.md)"), "accepted")
    fails_all(adr_dir, "0001-a.md", "0002-b.md")


def test_a_dot_slash_link_names_an_adr_and_counts_as_a_back_link(tmp_path):
    """Catches `./NNNN-*.md` being skipped, on either end of an amendment."""
    one_way = two_adrs(
        tmp_path / "a", naming("accepted", "- Amends: [0001](./0001-a.md)"), "accepted"
    )
    fails_all(one_way, "0001-a.md", "0002-b.md")
    both = two_adrs(
        tmp_path / "b",
        naming("accepted", "- Amends: [0001](./0001-a.md)"),
        "accepted, amended by [0002](./0002-b.md)",
    )
    assert len(adr_index.read_all(both)) == 2


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


@pytest.mark.parametrize(
    "text",
    [
        "[0001](<0001-x.md>)",
        "[0001][1]\n\n[1]: 0001-x.md",
        "[0001](./0001-x.md#why)",
        '<a href="0001-x.md">0001</a>',
    ],
)
def test_a_readme_linking_an_adr_in_another_markdown_form_is_caught(tmp_path, text):
    """Catches an angle-bracket, reference-style or ./ link to an ADR slipping past R3.2."""
    readme = tmp_path / "README.md"
    readme.write_text(text + "\n")
    assert adr_index.readme_links(readme) == ["0001-x.md"]


def test_a_readme_naming_an_adr_file_without_linking_it_is_clean(tmp_path):
    """Catches R3.2 (links) being widened to any mention of a filename."""
    readme = tmp_path / "README.md"
    readme.write_text("Files are named like `0062-the-adr-index.md`, as 0001-x.md is.\n")
    assert adr_index.readme_links(readme) == []


@pytest.mark.parametrize(
    "text",
    [
        "Write a row as `[0001](0001-x.md)`.",
        "Like this:\n\n```markdown\n| [0001](0001-x.md) | A title |\n```\n",
        "Like this:\n\n~~~\n[1]: 0001-x.md\n~~~\n",
    ],
)
def test_link_syntax_in_readme_code_is_not_a_link(tmp_path, text):
    """Catches an example in a code span or fence, which renders as text, failing R3.2."""
    readme = tmp_path / "README.md"
    readme.write_text(text)
    assert adr_index.readme_links(readme) == []


@pytest.mark.parametrize("anchor", ['<a HREF="0001-x.md">', "<a href = '0001-x.md'>"])
def test_an_html_link_in_any_case_or_spacing_is_caught(tmp_path, anchor):
    """Catches an HTML link to an ADR slipping past R3.2 by case or spacing."""
    readme = tmp_path / "README.md"
    readme.write_text(f"{anchor}0001</a>\n")
    assert adr_index.readme_links(readme) == ["0001-x.md"]


def test_the_real_readme_lists_no_adr():
    """Catches the hand-kept table coming back."""
    assert adr_index.readme_links(REPO / "docs" / "adr" / "README.md") == []


def three_adrs(tmp_path: Path) -> list[adr_index.Adr]:
    write_adr(tmp_path, number="0002", slug="b", lines=with_status("proposed"))
    write_adr(tmp_path, number="0001", slug="a")
    write_adr(tmp_path, number="0003", slug="c")
    return adr_index.read_all(tmp_path / "docs" / "adr")


def test_render_makes_a_page_of_rows_in_order_with_links_and_counts(tmp_path):
    """Catches a row missing or out of order, a wrong link, or a count wrong or omitted."""
    page = adr_index.render(three_adrs(tmp_path), repo_url="https://example.com/r")
    assert page.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in page
    assert "<title>Architecture decisions</title>" in page
    assert "3 decisions: 1 proposed, 2 accepted, 0 superseded" in page
    assert page.count("<tr>") == 4  # the header row and three ADRs
    links = [
        f'<a href="https://example.com/r/blob/main/docs/adr/000{n}-{s}.md">000{n}</a>'
        for n, s in ((1, "a"), (2, "b"), (3, "c"))
    ]
    positions = [page.index(link) for link in links]
    assert positions == sorted(positions)
    assert (
        '<a href="https://example.com/r/blob/main/docs/specs/0001-x/design.md">0001-x</a>' in page
    )


def test_render_turns_a_status_link_and_code_span_into_html(tmp_path):
    """Catches markdown left in the status cell, or a link or code span not rendered."""
    path = write_adr(
        tmp_path,
        lines=with_status("accepted; see [0002](0002-y.md#why) and `x_y`"),
    )
    (path.parent / "0002-y.md").write_text("x")
    page = adr_index.render([adr_index.read_adr(path)], repo_url="https://example.com/r")
    assert '<a href="https://example.com/r/blob/main/docs/adr/0002-y.md#why">0002</a>' in page
    assert "<code>x_y</code>" in page
    assert "](" not in page
    assert "`" not in page


def test_render_shows_an_amends_line_under_its_key_with_the_link_resolved(tmp_path):
    """Catches an Amends line dropped from the status cell, or its link left relative."""
    path = write_adr(
        tmp_path,
        lines=[*with_status("accepted"), "- Amends: [0002](../specs/0001-x/design.md)"],
    )
    page = adr_index.render([adr_index.read_adr(path)], repo_url="https://example.com/r")
    assert (
        "<br>Amends: "
        '<a href="https://example.com/r/blob/main/docs/specs/0001-x/design.md">0002</a>' in page
    )
    assert "Supersedes:" not in page


def test_render_keeps_an_absolute_link_as_it_is(tmp_path):
    """Catches a URL being joined onto the repository path."""
    path = write_adr(tmp_path, lines=with_status("accepted; [x](https://example.com/a.md)"))
    page = adr_index.render([adr_index.read_adr(path)], repo_url="https://example.com/r")
    assert '<a href="https://example.com/a.md">x</a>' in page


def test_render_escapes_the_title(tmp_path):
    """Catches ADR text reaching the page as markup."""
    path = write_adr(tmp_path, heading="# 0001. <script>alert(1)</script> & more")
    page = adr_index.render([adr_index.read_adr(path)])
    assert "<script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; more" in page


def test_render_escapes_markup_in_the_status_cell(tmp_path):
    """Catches the status cell, which gets links and code, letting raw markup through."""
    path = write_adr(tmp_path, lines=with_status("accepted; <b>bold</b> `<i>`"))
    page = adr_index.render([adr_index.read_adr(path)])
    assert "<b>" not in page
    assert "<code>&lt;i&gt;</code>" in page


def test_render_keeps_link_syntax_inside_a_code_span_as_code(tmp_path):
    """Catches `[a](b)` inside backticks being turned into a link."""
    path = write_adr(tmp_path, lines=with_status("accepted; `[a](https://example.com/b)` stays"))
    page = adr_index.render([adr_index.read_adr(path)])
    assert "<code>[a](https://example.com/b)</code>" in page
    assert '<a href="https://example.com/b"' not in page


def test_render_keeps_a_link_whose_label_is_code(tmp_path):
    """Catches a code span inside a link label breaking the link apart."""
    path = write_adr(tmp_path, lines=with_status("accepted; see [`x_y`](https://example.com/b)"))
    page = adr_index.render([adr_index.read_adr(path)])
    assert '<a href="https://example.com/b"><code>x_y</code></a>' in page


def test_the_real_adrs_render():
    """Catches a real ADR the page cannot be built from."""
    adrs = adr_index.read_all(REPO / "docs" / "adr")
    page = adr_index.render(adrs)
    assert f"{len(adrs)} decisions:" in page
