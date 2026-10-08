"""AGENTS.md: all JSON access goes through ``fo_json_*``; models never write DuckDB JSON syntax.

The BigQuery migration only works if the DuckDB spelling lives in ``dbt/macros/json.sql``
alone, so this scans every model and singular test for it (spec 79, AC1 and AC7). Macros are
the one place allowed to spell it, so ``dbt/macros/`` is not scanned.

``->`` is flagged wherever it appears, not only as ``->>``: no model uses a lambda
(``x -> ...``), and a JSON arrow and a lambda arrow cannot be told apart without a parser.
If a lambda is ever needed, wrap it in a macro.
"""

import re
from pathlib import Path

import pytest

DBT_ROOT = Path(__file__).resolve().parents[2] / "dbt"
SCANNED_DIRS = ("models", "tests")

# SQL line comments and Jinja comments (which may span lines): leftmost match wins, so a
# "--" inside a {# #} block, or a {# inside a "--" line, is handled by whichever comes first.
_COMMENT = re.compile(r"\{#.*?#\}|--[^\n]*", re.DOTALL)

# (what, pattern). "fo_json_text(" does not match json_\w+\( because the \b needs a
# non-word character before "json", and "_" is a word character.
_SYNTAX = (
    ("from_json", re.compile(r"\bfrom_json\b", re.IGNORECASE)),
    ("json_* function", re.compile(r"\bjson_\w+\s*\(", re.IGNORECASE)),
    ("-> / ->> operator", re.compile(r"->")),
    ("::JSON cast", re.compile(r"::\s*json\b", re.IGNORECASE)),
)


def _blank(match: re.Match[str]) -> str:
    """Replace a comment by its newlines alone, so line numbers stay true."""
    return "\n" * match.group().count("\n")


def json_syntax_violations(sql: str) -> list[tuple[int, str]]:
    """(line number, what was found) for each DuckDB JSON construct outside comments."""
    code = _COMMENT.sub(_blank, sql)
    found = []
    for number, line in enumerate(code.splitlines(), start=1):
        for what, pattern in _SYNTAX:
            if pattern.search(line):
                found.append((number, what))
    return found


def _sql_files() -> list[Path]:
    return sorted(p for d in SCANNED_DIRS for p in (DBT_ROOT / d).rglob("*.sql"))


def test_no_dbt_model_or_test_writes_duckdb_json_syntax() -> None:
    """Catches DuckDB JSON syntax creeping back into a model or singular test."""
    assert _sql_files(), "found no .sql files: DBT_ROOT is wrong"
    problems = [
        f"{path.relative_to(DBT_ROOT.parent)}:{number}: {what}"
        for path in _sql_files()
        for number, what in json_syntax_violations(path.read_text())
    ]
    assert not problems, "use a fo_json_* macro (dbt/macros/json.sql):\n" + "\n".join(problems)


# -- the check itself, on made-up SQL ---------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "what"),
    [
        ("select from_json(x, 'a')", "from_json"),
        ("select json_extract(p, '$.a')", "json_* function"),
        ("select json_extract_string(p, '$.a')", "json_* function"),
        ("select unnest(json_keys(p, '$.a'))", "json_* function"),
        ("select JSON_ARRAY_LENGTH (p)", "json_* function"),
        ("select p ->> '$.a'", "-> / ->> operator"),
        ("select p -> '$.a'", "-> / ->> operator"),
        ("select p::JSON", "::JSON cast"),
        ("select p :: json", "::JSON cast"),
        ("select p::json[]", "::JSON cast"),
    ],
)
def test_each_kind_of_json_syntax_is_caught_with_its_line_number(sql: str, what: str) -> None:
    """Catches a scanner that misses one spelling of DuckDB JSON syntax, or the wrong line."""
    assert json_syntax_violations("select 1\n" + sql) == [(2, what)]


def test_json_syntax_inside_a_macro_argument_string_is_caught() -> None:
    """Catches syntax hidden in a string passed to another macro, as fo_latest_by_entity takes."""
    sql = "{{ fo_latest_by_entity(['game_pk', \"player ->> '$.person.id'\"]) }}"
    assert json_syntax_violations(sql) == [(1, "-> / ->> operator")]


def test_comments_are_not_flagged() -> None:
    """Catches a scanner that flags prose about JSON in a SQL or Jinja comment."""
    sql = (
        "-- was json_extract(p, '$.a') ->> 'x'\n"
        "select 1 -- from_json here\n"
        "{# json_keys(p, '$.a')\n"
        "   spans lines: p ->> '$.b'::JSON #}\n"
        "select 2\n"
    )
    assert json_syntax_violations(sql) == []


def test_line_numbers_survive_a_multi_line_comment() -> None:
    """Catches comment stripping that shifts the line a violation is reported on."""
    sql = "{# one\n two\n three #}\nselect json_keys(p, '$.a')\n"
    assert json_syntax_violations(sql) == [(4, "json_* function")]


def test_code_after_a_comment_on_the_same_line_is_still_scanned() -> None:
    """Catches a scanner that treats the rest of a line as comment after a closed {# #}."""
    assert json_syntax_violations("{# note #} select p ->> '$.a'") == [(1, "-> / ->> operator")]


def test_fo_json_macro_calls_are_not_flagged() -> None:
    """Catches a scanner that flags the macros themselves ('fo_json_' contains 'json_')."""
    sql = (
        "select {{ fo_json_text('payload', '$.id') }} as id,\n"
        "       {{ fo_json_int('m', '$.home.teamId') }},\n"
        "       {{ fo_json_keys('m', '$.a') }},\n"
        "       {{ fo_json_parse('payload', '$.teams', schema) }}\n"
    )
    assert json_syntax_violations(sql) == []
