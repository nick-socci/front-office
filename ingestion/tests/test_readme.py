"""README.md must carry a table of the marts, and it must match the marts that exist.

The table under `## The marts` is the first thing a reader sees of what this project
builds. A mart added without a row, a row left behind for a removed mart, or a half-filled
row would make the front page quietly wrong; nothing else checks it (spec 0013, R5.1, R5.2).
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
MARTS = REPO / "dbt/models/marts"
HEADING = "## The marts"
COLUMNS = 4


def marts_table(text: str) -> list[list[str]]:
    """Data rows of the first table under `## The marts`, as lists of stripped cells.

    The header and separator rows are skipped. The search stops at the next `## `
    heading. Raises AssertionError if the heading or a table under it is missing.
    """
    lines = text.splitlines()
    assert HEADING in lines, f"README.md has no line exactly {HEADING!r}"
    section: list[str] = []
    for line in lines[lines.index(HEADING) + 1 :]:
        if line.startswith("## "):
            break
        section.append(line)
    table: list[str] = []
    for line in section:
        if line.strip().startswith("|"):
            table.append(line.strip())
        elif table:
            break
    assert len(table) >= 2, f"no Markdown table under {HEADING!r}"
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in table[2:]]


def mart_names() -> set[str]:
    return {p.stem for p in MARTS.iterdir() if p.suffix in {".sql", ".py"}}


def test_every_mart_has_one_row_and_every_row_is_a_mart():
    """Catches a mart missing from the table, or a row naming something that is no mart."""
    rows = marts_table(README.read_text())
    assert rows, "the marts table has no data rows"
    names = []
    for row in rows:
        cell = row[0]
        assert cell.startswith("`") and cell.endswith("`") and cell.count("`") == 2, (
            f"first column must be one name in backticks, got {cell!r}"
        )
        names.append(cell.strip("`"))
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, f"marts named twice: {duplicates}"
    expected = mart_names()
    missing = sorted(expected - set(names))
    extra = sorted(set(names) - expected)
    assert not missing and not extra, f"missing from README: {missing}; not marts: {extra}"


def test_marts_table_has_four_columns_and_no_empty_cell():
    """Catches a row with a blank cell, or a table of the wrong shape."""
    rows = marts_table(README.read_text())
    for row in rows:
        assert len(row) == COLUMNS, f"expected {COLUMNS} columns, got {len(row)}: {row}"
        assert all(row), f"empty cell in row {row}"


TABLE = """\
| Mart | Question | Grain | Rows |
| --- | --- | --- | --- |
| `fct_a` | Who won? | one per matchup | 10 |
"""
OTHER_TABLE = "| a | b | c | d |\n|---|---|---|---|\n| `z` | 1 | 2 | 3 |\n"


def test_helper_reads_the_table_after_the_heading():
    """Catches the parser returning header or separator rows as data."""
    text = f"# T\n\n{HEADING}\n\nintro\n\n{TABLE}"
    assert marts_table(text) == [["`fct_a`", "Who won?", "one per matchup", "10"]]


def test_helper_does_not_find_a_mart_named_only_in_prose():
    """Catches prose mentions counting as table rows."""
    text = f"{HEADING}\n\n`fct_b` is described here in prose.\n\n{TABLE}"
    names = [row[0] for row in marts_table(text)]
    assert "`fct_b`" not in names


def test_helper_ignores_a_table_under_another_heading():
    """Catches a table elsewhere in the README being used as the marts table."""
    text = f"## Other\n\n{OTHER_TABLE}\n{HEADING}\n\nnothing here\n"
    with pytest.raises(AssertionError, match="no Markdown table"):
        marts_table(text)


def test_helper_detects_an_empty_cell():
    """Catches a blank cell being dropped or hidden by the parser."""
    text = f"{HEADING}\n\n| a | b | c | d |\n|---|---|---|---|\n| `x` | q |  | 1 |\n"
    (row,) = marts_table(text)
    assert row == ["`x`", "q", "", "1"]
    assert not all(row)


def test_helper_stops_at_the_next_heading():
    """Catches a table after the next `## ` heading being read as part of this section."""
    text = f"{HEADING}\n\n{TABLE}\n## Next\n\n{OTHER_TABLE}"
    assert [row[0] for row in marts_table(text)] == ["`fct_a`"]
    with pytest.raises(AssertionError, match="no Markdown table"):
        marts_table(f"{HEADING}\n\nno table\n\n## Next\n\n{TABLE}")
