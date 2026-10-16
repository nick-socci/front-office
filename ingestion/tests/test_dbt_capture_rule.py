"""Staging reads captures through the capture views, and nothing is built a season at a time
(spec 0150, R3.4, R3.5, R4.1).

``fo_captures`` (``dbt/macros/json.sql``) is the one place that reads payload files and the
manifest ``raw.captures``; the eleven views in ``dbt/models/staging/raw`` call it, and every
other model and singular test reads a view. So no ``.sql`` file under ``dbt/models`` or
``dbt/tests`` names ``read_json``, ``read_json_objects`` or the raw tables, and only
``json.sql`` among the macros names the two functions. Unit tests in YAML are not scanned:
they must name the sources they replace.

The six models once built a season at a time (microbatch, spec 0143); they are plain tables
now, and the second check keeps batching from returning unnoticed.
"""

import re
from pathlib import Path

import pytest

DBT_ROOT = Path(__file__).resolve().parents[2] / "dbt"
JSON_MACROS = DBT_ROOT / "macros" / "json.sql"

# The one place outside json.sql allowed to name the manifest: it checks the views against
# it, which no view can do about itself.
MANIFEST_CHECK = DBT_ROOT / "tests" / "stg_raw__capture_views_cover_the_manifest.sql"

# Same comment syntax as test_dbt_json_rule.py: SQL line comments and Jinja comments.
_COMMENT = re.compile(r"\{#.*?#\}|--[^\n]*", re.DOTALL)
_YAML_COMMENT = re.compile(r"#[^\n]*")

_READ_FILES = ("read_json / read_json_objects", re.compile(r"\bread_json\w*", re.IGNORECASE))
_RAW_TABLES = (
    "raw.api_responses / raw.captures",
    re.compile(r"\braw[\"'`]?\s*\.\s*[\"'`]?(api_responses|captures)\b", re.IGNORECASE),
)
# source('raw', 'api_responses') in any spacing and quoting; a Jinja call can also pass the
# names by keyword or on two lines, so the whitespace class includes newlines.
_RAW_SOURCES = (
    "source('raw', 'api_responses' / 'captures')",
    re.compile(
        r"\bsource\s*\(\s*[\"']raw[\"']\s*,\s*[\"'](api_responses|captures)[\"']\s*\)",
        re.IGNORECASE,
    ),
)
_BATCHING = (
    "microbatch / event_time / incremental_strategy",
    re.compile(r"\b(microbatch|event_time|incremental_strategy)\b", re.IGNORECASE),
)


def _blank(match: re.Match[str]) -> str:
    """Replace a comment by its newlines alone, so line numbers stay true."""
    return "\n" * match.group().count("\n")


def violations(
    text: str, checks: tuple[tuple[str, re.Pattern[str]], ...], comment: re.Pattern[str] = _COMMENT
) -> list[tuple[int, str]]:
    """(line number, what was found) for each construct in ``checks`` outside comments."""
    code = comment.sub(_blank, text)
    return [
        (number, what)
        for number, line in enumerate(code.splitlines(), start=1)
        for what, pattern in checks
        if pattern.search(line)
    ]


def _model_and_test_sql() -> list[Path]:
    return sorted(
        p for d in ("models", "tests") for p in (DBT_ROOT / d).rglob("*.sql") if p != MANIFEST_CHECK
    )


def _relative(path: Path) -> str:
    return str(path.relative_to(DBT_ROOT.parent))


def test_no_model_or_test_reads_payload_files_or_the_raw_tables() -> None:
    """Catches a model or singular test reading files or the manifest itself, instead of a
    capture view: the table that once held every payload, or a second way to read them."""
    files = _model_and_test_sql()
    assert files and MANIFEST_CHECK.exists(), "DBT_ROOT is wrong or the manifest check moved"
    problems = [
        f"{_relative(path)}:{number}: {what}"
        for path in files
        for number, what in violations(path.read_text(), (_READ_FILES, _RAW_TABLES, _RAW_SOURCES))
    ]
    assert not problems, "read a stg_raw__<source>_<endpoint> view instead:\n" + "\n".join(problems)


def test_only_json_sql_names_the_file_readers() -> None:
    """Catches a macro besides json.sql reading payload files, which would be a second place
    to keep the glob, the join to the manifest and the BigQuery variant."""
    macros = sorted(p for p in (DBT_ROOT / "macros").rglob("*.sql") if p != JSON_MACROS)
    assert macros and JSON_MACROS.exists()
    problems = [
        f"{_relative(path)}:{number}: {what}"
        for path in macros
        for number, what in violations(path.read_text(), (_READ_FILES,))
    ]
    assert not problems, "read files only in fo_captures (dbt/macros/json.sql):\n" + "\n".join(
        problems
    )


def _batching_files() -> list[Path]:
    return sorted(
        [DBT_ROOT / "dbt_project.yml"]
        + [p for p in (DBT_ROOT / "models").rglob("*.yml")]
        + [p for p in (DBT_ROOT / "models").rglob("*.sql")]
    )


def test_no_model_is_built_a_season_at_a_time() -> None:
    """Catches microbatch, an event time or an incremental strategy coming back (R4.1): a
    model reads every capture at once, and a batch would miss the seasons it does not name."""
    problems = []
    for path in _batching_files():
        pattern = _YAML_COMMENT if path.suffix == ".yml" else _COMMENT
        problems += [
            f"{_relative(path)}:{number}: {what}"
            for number, what in violations(path.read_text(), (_BATCHING,), pattern)
        ]
    assert not problems, "models are plain tables or views:\n" + "\n".join(problems)


# -- the check itself, on made-up SQL ---------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "what"),
    [
        ("select * from read_json('a')", "read_json / read_json_objects"),
        ("select * from READ_JSON_OBJECTS('a')", "read_json / read_json_objects"),
        ("select * from raw.api_responses", "raw.api_responses / raw.captures"),
        ("select * from raw . captures", "raw.api_responses / raw.captures"),
        ('select * from "raw"."captures"', "raw.api_responses / raw.captures"),
        ("{{ source('raw', 'api_responses') }}", "source('raw', 'api_responses' / 'captures')"),
        ('{{ source( "raw" ,"captures" ) }}', "source('raw', 'api_responses' / 'captures')"),
    ],
)
def test_each_way_of_naming_a_raw_table_is_caught_with_its_line_number(sql: str, what: str) -> None:
    """Catches a scanner that misses one spelling of a read it is meant to forbid."""
    found = violations("select 1\n" + sql, (_READ_FILES, _RAW_TABLES, _RAW_SOURCES))
    assert (2, what) in found


def test_other_sources_and_comments_are_not_flagged() -> None:
    """Catches a scanner that flags another source, or prose in a comment."""
    sql = (
        "-- read_json and source('raw', 'captures') here\n"
        "{# raw.api_responses\n   read_json_objects #}\n"
        "select * from {{ source('raw', 'something_else') }}, {{ ref('stg_raw__mlb_boxscore') }}\n"
    )
    assert violations(sql, (_READ_FILES, _RAW_TABLES, _RAW_SOURCES)) == []


def test_batching_is_caught_in_sql_and_in_yaml() -> None:
    """Catches a scanner that misses a config in a model's SQL or in a properties file."""
    sql = "{{ config(incremental_strategy='microbatch', event_time='season_start') }}"
    assert {w for _, w in violations(sql, (_BATCHING,))} == {_BATCHING[0]}
    yml = "models:\n  - name: m\n    config:\n      event_time: d  # not this one: event_time\n"
    assert violations(yml, (_BATCHING,), _YAML_COMMENT) == [(4, _BATCHING[0])]
    assert violations("# event_time: d\nmodels: []\n", (_BATCHING,), _YAML_COMMENT) == []
