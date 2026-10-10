"""AGENTS.md, ADR 0046: a floating-point aggregate takes an ``order by`` inside its parentheses.

The last digit of ``avg``, ``corr``, ``stddev`` and the like depends on the order of their
rows, row order changes between builds, and warehouses are compared exactly. The unit tests
that pin a last digit fail on an unordered aggregate in most runs and pass in some (DuckDB's
row order inside a dbt unit test varies), so this reads the SQL instead: every call of one
of the aggregates below, in a model, a singular test or a macro, must state its order, or
claim the exemption in a comment (spec 0115, R5; PR #120 review, F2).

``sum`` is not checked. Whether a sum is floating-point cannot be read from the SQL: most
sums here add whole counts, which are exact in any order, and flagging them all would bury
the ones that matter under exemptions. An unordered sum of doubles is caught only when two
real builds are compared, as #115 was.

An aggregate that is exact whatever the order (integer-valued inputs whose magnitudes sum
below 2^53) says so with ``order-exempt:`` and the bound, in a comment on its own line or
the lines directly above it. The marker alone, or the marker in a string, exempts nothing.
"""

import re
from pathlib import Path

import pytest

DBT_ROOT = Path(__file__).resolve().parents[2] / "dbt"
SCANNED_DIRS = ("models", "tests", "macros")

# SQL line comments and Jinja comments, as in test_dbt_json_rule.py.
_COMMENT = re.compile(r"\{#.*?#\}|--[^\n]*", re.DOTALL)

# Aggregates whose result is a floating-point statistic of many rows. median and quantile
# choose a value and min, max and count are exact, so they are not here.
_AGGREGATE = re.compile(
    r"\b(avg|mean|corr|stddev|stddev_pop|stddev_samp|variance|var_pop|var_samp"
    r"|covar_pop|covar_samp|regr_\w+|kurtosis\w*|skewness)\s*\(",
    re.IGNORECASE,
)
_ORDER_BY = re.compile(r"\border\s+by\b", re.IGNORECASE)
# The exemption: a SQL comment carrying the marker and, after it, a reason. String literals
# are set aside first, so neither the marker nor a "--" inside one is read as a comment.
_STRING = re.compile(r"'[^']*'")
_EXEMPTION = re.compile(r"--.*order-exempt:[ \t]*\S")


def _blank(match: re.Match[str]) -> str:
    """Replace a comment by its newlines alone, so line numbers stay true."""
    return "\n" * match.group().count("\n")


def _arguments(code: str, start: int) -> str:
    """The text between the parenthesis that opens at `start - 1` and the one closing it,
    with nested parentheses and string literals emptied: what is left is the call's own."""
    depth, own, quoted = 1, [], False
    for char in code[start:]:
        if quoted:
            quoted = char != "'"
        elif char == "'":
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1:
            own.append(char)
    return "".join(own)


def _is_exempt(lines: list[str], number: int) -> bool:
    """True when a comment on the call's line, or the comment lines directly above it, claims
    the exemption and gives a reason."""

    def claims(line: str) -> bool:
        return bool(_EXEMPTION.search(_STRING.sub("''", line)))

    if claims(lines[number - 1]):
        return True
    above = number - 2
    while above >= 0 and lines[above].lstrip().startswith("--"):
        if claims(lines[above]):
            return True
        above -= 1
    return False


def unordered_aggregates(sql: str) -> list[tuple[int, str]]:
    """(line number, aggregate) for each statistical aggregate with no order and no exemption."""
    code = _COMMENT.sub(_blank, sql)
    lines = sql.splitlines()
    found = []
    for match in _AGGREGATE.finditer(code):
        number = code.count("\n", 0, match.start()) + 1
        if _ORDER_BY.search(_arguments(code, match.end())) or _is_exempt(lines, number):
            continue
        found.append((number, match.group(1).lower()))
    return found


def _sql_files() -> list[Path]:
    return sorted(p for d in SCANNED_DIRS for p in (DBT_ROOT / d).rglob("*.sql"))


def test_every_statistical_aggregate_in_dbt_states_its_order() -> None:
    """Catches an `order by` removed from avg, corr or the like, or a new one written
    without it: the regression the last-digit unit tests only catch in most runs."""
    assert _sql_files(), "found no .sql files: DBT_ROOT is wrong"
    scanned = "\n".join(_COMMENT.sub(_blank, p.read_text()) for p in _sql_files())
    assert len(_AGGREGATE.findall(scanned)) >= 3, "the three aggregates of #115 were not found"
    problems = [
        f"{path.relative_to(DBT_ROOT.parent)}:{number}: {name}() has no order by"
        for path in _sql_files()
        for number, name in unordered_aggregates(path.read_text())
    ]
    assert not problems, (
        "state the order inside the aggregate, on the grain's key (ADR 0046):\n"
        + "\n".join(problems)
    )


# -- the check itself, on made-up SQL ---------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "name"),
    [
        ("select avg(score) from t", "avg"),
        ("select AVG (score) from t", "avg"),
        ("select corr(y, x) as correlation from t", "corr"),
        ("select stddev_pop(margin) from t", "stddev_pop"),
        ("select var_samp(margin) from t", "var_samp"),
        ("select regr_slope(y, x) from t", "regr_slope"),
        ("select sqrt(avg(margin * margin)) from t", "avg"),
    ],
)
def test_an_aggregate_with_no_order_is_caught_with_its_line_number(sql: str, name: str) -> None:
    """Catches a scanner that misses one of the aggregates, or reports the wrong line."""
    assert unordered_aggregates("select 1\n" + sql) == [(2, name)]


@pytest.mark.parametrize(
    "sql",
    [
        "select avg(score order by matchup_id, side) from t",
        "select corr(y, x order by player_id, team_id) as correlation from t",
        "select avg(\n    score\n    order by matchup_id\n) from t",
        "select avg(coalesce(score, 0) ORDER  BY matchup_id) from t",
    ],
)
def test_an_aggregate_that_states_its_order_passes(sql: str) -> None:
    """Catches a scanner that flags the fix itself, however the call is laid out."""
    assert unordered_aggregates(sql) == []


def test_an_order_in_a_nested_call_or_a_window_is_not_the_aggregates_own() -> None:
    """Catches an order by borrowed from elsewhere: an inner aggregate's, an over clause's, or
    a string's."""
    assert unordered_aggregates("select avg(sum(x order by k)) from t") == [(1, "avg")]
    assert unordered_aggregates("select avg(x) over (order by k) from t") == [(1, "avg")]
    assert unordered_aggregates("select avg(x) from t order by 1") == [(1, "avg")]
    assert unordered_aggregates("select corr(y, f('order by')) from t") == [(1, "corr")]


def test_an_exemption_is_claimed_in_a_comment_at_the_aggregate() -> None:
    """Catches an exemption that is not read, or one read from a comment somewhere else."""
    on_the_line = "select avg(games) -- order-exempt: whole numbers, at most 162 a row\nfrom t"
    above = (
        "select\n"
        "    -- A count of games per side.\n"
        "    -- order-exempt: whole numbers summing far below 2^53\n"
        "    avg(games) as mean_games\n"
        "from t"
    )
    elsewhere = "-- order-exempt: not about this call\nselect 1,\n    avg(games)\nfrom t"
    assert unordered_aggregates(on_the_line) == []
    assert unordered_aggregates(above) == []
    assert unordered_aggregates(elsewhere) == [(3, "avg")]


def test_an_exemption_needs_a_reason_and_has_to_be_a_comment() -> None:
    """Catches an aggregate passed over on the marker alone, or on the marker in a string."""
    no_reason = "select avg(games) -- order-exempt:\nfrom t"
    blank_reason = "select\n    -- order-exempt:   \n    avg(games)\nfrom t"
    in_a_string = "select avg(x) as mean_x, 'order-exempt: not a comment' as note from t"
    dashes_in_a_string = "select avg(x), '-- order-exempt: still a string' as note from t"
    assert unordered_aggregates(no_reason) == [(1, "avg")]
    assert unordered_aggregates(blank_reason) == [(3, "avg")]
    assert unordered_aggregates(in_a_string) == [(1, "avg")]
    assert unordered_aggregates(dashes_in_a_string) == [(1, "avg")]


def test_prose_about_an_aggregate_in_a_comment_is_not_flagged() -> None:
    """Catches a scanner that reads comments as SQL, as the header of the scales model would be."""
    sql = "-- sqrt(avg(margin^2)) does not; not avg(): see #28\n{# corr(y, x) #}\nselect 1\n"
    assert unordered_aggregates(sql) == []


def test_names_that_only_contain_an_aggregates_name_are_not_flagged() -> None:
    """Catches a scanner without word boundaries, and sum, median and count being swept in."""
    sql = "select moving_avg(x), sum(x), median(x), count(*), max(x), avg_score from t"
    assert unordered_aggregates(sql) == []
