"""AGENTS.md rule 5, ADRs 0107 and 0108: a window that depends on row order goes through a
checked macro.

``row_number``, ``lag``, ``lead``, ``first_value``, ``last_value``, ``nth_value`` and ``ntile``
give a different answer for rows that tie on the window's order, and DuckDB and BigQuery
break the tie differently, so nothing says a row was chosen by chance. ``fo_keep_first`` and
``fo_row_number`` check their own order on every build and stop it on a tie (ADR 0107). This
reads the SQL instead of the data: a model, a singular test or a macro that calls one of the
functions below itself must either go through the two macros or claim the exemption with
``tie-exempt:`` and a reason, in a ``--`` comment on the call's line or the comment lines
directly above it (spec 0141, R2.1 and R2.2).

``rank``, ``dense_rank``, ``percent_rank`` and ``cume_dist`` are not checked: tied rows get the
same value from them, in either warehouse, so a tie changes nothing.

The marker alone, or the marker in a string, exempts nothing. The bodies of ``fo_keep_first``
and ``fo_row_number`` are not read: they are where the calls are made, checked.

This reads SQL text; it does not parse SQL or render Jinja. It knows comments (``--``,
``/* */``, ``{# #}``) and string literals, the way the ordered-aggregate rule does (they share
``_sql_text``). It does not follow a macro that builds a call from pieces, nor a dollar-quoted
string. It is a tripwire for the ordinary way of writing these calls, which is the way all of
them here are written. As in that rule, the exemption is read from a ``--`` comment, not from a
``/* */`` one, which fails safe: the call is flagged and its author rewrites the comment.
"""

import re
from pathlib import Path

import pytest

from _sql_text import NOT_NEWLINE, is_exempt, sql_code

DBT_ROOT = Path(__file__).resolve().parents[2] / "dbt"
SCANNED_DIRS = ("models", "tests", "macros")

# Windows whose result depends on the order of tied rows. rank, dense_rank, percent_rank and
# cume_dist give tied rows one value, so they are not here.
_ORDER_DEPENDENT = re.compile(
    r"\b(row_number|lag|lead|first_value|last_value|nth_value|ntile)\s*\(",
    re.IGNORECASE,
)
# The exemption: the marker in a SQL comment, followed by a reason with a letter or a digit
# in it. An empty or quoted-empty reason, or punctuation, is not one.
_EXEMPTION = re.compile(r"tie-exempt:.*[A-Za-z0-9]")

# The two macros that make the calls, checked (ADR 0108). Their bodies are not read as SQL.
_CHECKED_MACRO_BODIES = re.compile(
    r"\{%-?\s*macro\s+(?:fo_keep_first|fo_row_number)\b.*?\{%-?\s*endmacro\s*-?%\}",
    re.DOTALL,
)


def unchecked_windows(sql: str) -> list[tuple[int, str]]:
    """(line number, function) for each order-dependent window outside the two macros and
    without an exemption."""
    code = _CHECKED_MACRO_BODIES.sub(lambda m: NOT_NEWLINE.sub(" ", m.group()), sql_code(sql))
    lines = sql.splitlines()
    found = []
    for match in _ORDER_DEPENDENT.finditer(code):
        number = code.count("\n", 0, match.start()) + 1
        if not is_exempt(lines, number, _EXEMPTION):
            found.append((number, match.group(1).lower()))
    return found


def _sql_files() -> list[Path]:
    return sorted(p for d in SCANNED_DIRS for p in (DBT_ROOT / d).rglob("*.sql"))


def test_every_order_dependent_window_in_dbt_goes_through_a_checked_macro() -> None:
    """Catches a `row_number()`, `lag()` or the like written in a model, test or macro outside
    fo_keep_first / fo_row_number, with no `tie-exempt:` reason: a ranking whose tie would be
    broken by chance, differently in the two warehouses."""
    assert _sql_files(), "found no .sql files: DBT_ROOT is wrong"
    problems = [
        f"{path.relative_to(DBT_ROOT.parent)}:{number}: {name}() is not checked for ties"
        for path in _sql_files()
        for number, name in unchecked_windows(path.read_text())
    ]
    assert not problems, (
        "go through fo_keep_first / fo_row_number (dbt/macros/latest_by_entity.sql), or say why "
        "ties change nothing with `-- tie-exempt: <reason>` on the line or directly above it "
        "(ADR 0108):\n" + "\n".join(problems)
    )


# -- the check itself, on made-up SQL ---------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "name"),
    [
        ("select row_number() over (order by k) from t", "row_number"),
        ("select ROW_NUMBER () over (order by k) from t", "row_number"),
        ("select lag(x) over (order by k) from t", "lag"),
        ("select lead(x, 2) over (order by k) from t", "lead"),
        ("select first_value(x) over (order by k) from t", "first_value"),
        ("select last_value(x) over (order by k) from t", "last_value"),
        ("select nth_value(x, 2) over (order by k) from t", "nth_value"),
        ("select ntile(4) over (order by k) from t", "ntile"),
    ],
)
def test_an_unchecked_window_is_caught_with_its_line_number(sql: str, name: str) -> None:
    """Catches a scanner that misses one of the functions, or reports the wrong line."""
    assert unchecked_windows("select 1\n" + sql) == [(2, name)]


def test_a_call_exempted_on_its_line_or_the_comment_lines_above_passes() -> None:
    """Catches an exemption that is not read, or one read from a comment somewhere else."""
    on_the_line = "select lag(x) over w -- tie-exempt: ties hold equal values\nfrom t"
    above = (
        "select\n"
        "    -- Only the middle positions are read.\n"
        "    -- tie-exempt: tied rows hold equal values\n"
        "    row_number() over w as position\n"
        "from t"
    )
    assert unchecked_windows(on_the_line) == []
    assert unchecked_windows(above) == []


def test_an_exemption_separated_from_the_call_by_code_does_not_apply() -> None:
    """Catches an exemption read from a comment that is about another line."""
    separated = (
        "-- tie-exempt: this is about the first call\n"
        "select row_number() over w as a,\n"
        "    row_number() over w as b\n"
        "from t"
    )
    assert unchecked_windows(separated) == [(3, "row_number")]


def test_an_exemption_needs_a_reason_and_has_to_be_a_comment() -> None:
    """Catches a call passed over on the marker alone, or on the marker in a string."""
    no_reason = "select row_number() over w -- tie-exempt:\nfrom t"
    blank_reason = "select\n    -- tie-exempt:   \n    row_number() over w\nfrom t"
    in_a_string = "select row_number() over w, 'tie-exempt: not a comment' as note from t"
    dashes_in_a_string = "select row_number() over w, '-- tie-exempt: still a string' as n from t"
    assert unchecked_windows(no_reason) == [(1, "row_number")]
    assert unchecked_windows(blank_reason) == [(3, "row_number")]
    assert unchecked_windows(in_a_string) == [(1, "row_number")]
    assert unchecked_windows(dashes_in_a_string) == [(1, "row_number")]
    dashes_in_double_quotes = 'select "-- tie-exempt: an identifier", row_number() over w from t'
    assert unchecked_windows(dashes_in_double_quotes) == [(1, "row_number")]
    after_a_quoted_identifier = 'select "a""b", lag(x) over w -- tie-exempt: same window\nfrom t'
    assert unchecked_windows(after_a_quoted_identifier) == []
    escaped_in_jinja = '{{ x("a \\" -- tie-exempt: inside the string") }} row_number() over w'
    assert unchecked_windows(escaped_in_jinja) == [(1, "row_number")]
    # a backslash in a SQL string is a plain character, so the string ends at its quote
    backslash_in_sql = "select row_number() over w, 'a\\' || '-- tie-exempt: a string' from t"
    assert unchecked_windows(backslash_in_sql) == [(1, "row_number")]
    call_before_escaped = 'select row_number() over w, {{ "\'a\\" -- tie-exempt: no\'" }} from t'
    assert unchecked_windows(call_before_escaped) == [(1, "row_number")]
    # a backslash at the end of a line does not carry the span onto the next one, where it
    # would keep a comment as code
    trailing_backslash = 'select "a\\\n-- row_number() named in "prose"\nfrom t'
    assert unchecked_windows(trailing_backslash) == []
    assert unchecked_windows("select lag(x) over w -- tie-exempt: ...") == [(1, "lag")]
    assert unchecked_windows("select lag(x) over w -- tie-exempt: it's equal") == []


def test_the_two_macro_bodies_are_not_read_and_nothing_else_is_spared() -> None:
    """Catches the allowance widening: the bodies of fo_keep_first and fo_row_number make the
    calls, and no other macro, nor the text after them, may."""
    keep_first = (
        "{% macro fo_keep_first(partition_by, order_by, rows=1) %}\n"
        "    qualify row_number() over (order by {{ order_by }}) <= 1\n"
        "{%- endmacro %}\n"
    )
    row_number = (
        "{% macro fo_row_number(partition_by, order_by) -%}\n"
        "    row_number() over (order by {{ order_by }})\n"
        "{%- endmacro %}\n"
    )
    assert unchecked_windows(keep_first) == []
    assert unchecked_windows(row_number) == []
    other = keep_first.replace("fo_keep_first", "fo_other")
    assert unchecked_windows(other) == [(2, "row_number")]
    after = keep_first + "{% macro fo_other(x) %}\n    lag({{ x }}) over w\n{%- endmacro %}\n"
    assert unchecked_windows(after) == [(5, "lag")]


def test_functions_that_give_tied_rows_one_value_are_not_flagged() -> None:
    """Catches the rule sweeping in rank, dense_rank, percent_rank and cume_dist, and names
    that only contain a flagged name."""
    sql = (
        "select rank() over w, dense_rank() over w, percent_rank() over w, cume_dist() over w,\n"
        "    my_row_number(x), lagged(x), first_value_of(x) from t"
    )
    assert unchecked_windows(sql) == []


def test_prose_in_a_comment_or_a_string_is_not_a_call() -> None:
    """Catches a scanner that reads comments, as a model's header would be, or strings as SQL."""
    sql = (
        "-- row_number() would pick one of the tied rows\n"
        "{# lag(x) is not used #}\n"
        "/* ntile(4) */\n"
        "select 'row_number()' as example from t\n"
    )
    assert unchecked_windows(sql) == []
    assert unchecked_windows("select '--' as m, row_number() over w from t") == [(1, "row_number")]
