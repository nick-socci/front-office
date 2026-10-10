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

This reads SQL text; it does not parse SQL or render Jinja. It knows comments (``--``,
``/* */``, ``{# #}``) and string literals, and it will not take an order from inside a
``{% %}`` block, since a branch may render nothing. It does not follow a macro that builds an
aggregate from pieces, nor a dollar-quoted string. It is a tripwire for the ordinary way of
writing these calls, which is the way all of them here are written.
"""

import re
from pathlib import Path

import pytest

DBT_ROOT = Path(__file__).resolve().parents[2] / "dbt"
SCANNED_DIRS = ("models", "tests", "macros")

# Aggregates whose result is a floating-point statistic of many rows. median and quantile
# choose a value and min, max and count are exact, so they are not here.
_AGGREGATE = re.compile(
    r"\b(avg|mean|corr|stddev|stddev_pop|stddev_samp|variance|var_pop|var_samp"
    r"|covar_pop|covar_samp|regr_\w+|kurtosis\w*|skewness)\s*\(",
    re.IGNORECASE,
)
_ORDER_BY = re.compile(r"\border\s+by\b", re.IGNORECASE)
# The exemption: the marker in a SQL comment, followed by a reason with a letter or a digit
# in it. An empty or quoted-empty reason, or punctuation, is not one.
_EXEMPTION = re.compile(r"order-exempt:.*[A-Za-z0-9]")


_NOT_NEWLINE = re.compile(r"[^\n]")


def _code(sql: str) -> str:
    """`sql` with comments and string literals blanked, character for character.

    One pass, so whichever opens first wins: a `--` inside a string is part of the string, and
    an apostrophe inside a comment is part of the comment. Newlines are kept, so line numbers
    stay true. A double-quoted span on one line (an identifier, or a string in Jinja) is kept
    as it is, so that an apostrophe inside it does not open a string.
    """
    out: list[str] = []
    at, end = 0, len(sql)

    def blanked(stop: int) -> int:
        out.append(_NOT_NEWLINE.sub(" ", sql[at:stop]))
        return stop

    def after(closer: str, start: int) -> int:
        found = sql.find(closer, start)
        return end if found < 0 else found + len(closer)

    while at < end:
        if sql.startswith("{#", at):
            at = blanked(after("#}", at + 2))
        elif sql.startswith("--", at):
            newline = sql.find("\n", at)
            at = blanked(end if newline < 0 else newline)
        elif sql.startswith("/*", at):
            at = blanked(after("*/", at + 2))
        elif sql[at] == "'":
            close = at + 1
            while close < end and (sql[close] != "'" or sql.startswith("''", close)):
                close += 2 if sql[close] == "'" else 1
            at = blanked(min(close + 1, end))
        elif sql[at] == '"' and '"' in sql[at + 1 : after("\n", at + 1)]:
            close = sql.index('"', at + 1)
            out.append(sql[at : close + 1])
            at = close + 1
        else:
            out.append(sql[at])
            at += 1
    return "".join(out)


def _arguments(code: str, start: int) -> str:
    """The text between the parenthesis that opens at `start - 1` and the one closing it, with
    nested parentheses emptied and everything from the first `{%` to the last `%}` left out:
    what is left is the call's own, in every rendering."""
    depth, own = 1, []
    for char in code[start:]:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1:
            own.append(char)
    text = "".join(own)
    first, last = text.find("{%"), text.rfind("%}")
    return text if first < 0 or last < first else text[:first] + " " + text[last + 2 :]


def _line_comment(line: str) -> str | None:
    """The text after the first `--` that is not inside a string literal, or None.

    Quotes are tracked only up to that point: after it the line is prose, and an apostrophe
    in it is not a string.
    """
    quoted = False
    for at, char in enumerate(line):
        if char == "'":
            quoted = not quoted
        elif not quoted and line.startswith("--", at):
            return line[at + 2 :]
    return None


def _is_exempt(lines: list[str], number: int) -> bool:
    """True when a comment on the call's line, or the comment lines directly above it, claims
    the exemption and gives a reason."""

    def claims(line: str) -> bool:
        comment = _line_comment(line)
        return comment is not None and bool(_EXEMPTION.search(comment))

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
    code = _code(sql)
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
    scanned = "\n".join(_code(p.read_text()) for p in _sql_files())
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
    # an empty quoted value is not a reason, and a reason that contains quotes still is one
    assert unordered_aggregates("select avg(x) -- order-exempt: ''\nfrom t") == [(1, "avg")]
    assert unordered_aggregates("select avg(x) -- order-exempt: '  ' \nfrom t") == [(1, "avg")]
    assert unordered_aggregates("select avg(x) -- order-exempt: it's a count, 162 at most") == []
    # apostrophes in the comment are prose, not strings, wherever they fall round the marker
    straddling = "select avg(x) -- the league's games, order-exempt: whole, a side's total is 162"
    assert unordered_aggregates(straddling) == []
    # and punctuation alone is not a reason
    assert unordered_aggregates("select avg(x) -- order-exempt: ...") == [(1, "avg")]
    assert unordered_aggregates("select avg(x) -- order-exempt: '-'") == [(1, "avg")]


def test_prose_about_an_aggregate_in_a_comment_is_not_flagged() -> None:
    """Catches a scanner that reads comments as SQL, as the header of the scales model would be."""
    sql = "-- sqrt(avg(margin^2)) does not; not avg(): see #28\n{# corr(y, x) #}\nselect 1\n"
    assert unordered_aggregates(sql) == []


def test_a_string_literal_is_neither_a_comment_nor_a_call() -> None:
    """Catches a `--` in a string hiding the rest of its line, and prose in a string read as
    a call (PR #120, focused review F1)."""
    assert unordered_aggregates("select '--' as marker, avg(score) from t") == [(1, "avg")]
    assert unordered_aggregates("select 'it''s --' as s, avg(score) from t") == [(1, "avg")]
    assert unordered_aggregates("select 'avg(score)' as example from t") == []
    spanning = "select '{#' as a,\n avg(score),\n '#}' as b from t"
    assert unordered_aggregates(spanning) == [(2, "avg")]


def test_a_block_comment_is_not_code() -> None:
    """Catches an order by, or a call, that is only in a /* */ comment (focused review F2)."""
    assert unordered_aggregates("select avg(score /* order by game_id */) from t") == [(1, "avg")]
    assert unordered_aggregates("select 1 /* avg(score) */ from t") == []
    assert unordered_aggregates("/* one\n two */\nselect avg(score) from t") == [(3, "avg")]


def test_an_order_that_only_a_jinja_branch_supplies_does_not_count() -> None:
    """Catches an order by that some rendering leaves out: a conditional branch may render
    nothing, so the order has to stand outside any {% %} block (focused review F3)."""
    conditional = "select avg(score {% if false %} order by game_id {% endif %}) from t"
    assert unordered_aggregates(conditional) == [(1, "avg")]
    either_way = "select avg(score {% if x %} order by a {% else %} order by b {% endif %}) from t"
    assert unordered_aggregates(either_way) == [(1, "avg")]
    outside = "select avg({% if x %} a {% else %} b {% endif %} order by game_id) from t"
    assert unordered_aggregates(outside) == []
    expression = "select avg({{ column }} order by {{ key }}) from {{ ref('t') }}"
    assert unordered_aggregates(expression) == []


def test_names_that_only_contain_an_aggregates_name_are_not_flagged() -> None:
    """Catches a scanner without word boundaries, and sum, median and count being swept in."""
    sql = "select moving_avg(x), sum(x), median(x), count(*), max(x), avg_score from t"
    assert unordered_aggregates(sql) == []
