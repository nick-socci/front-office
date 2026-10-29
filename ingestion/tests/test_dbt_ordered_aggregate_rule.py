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
``/* */``, ``{# #}``) and string literals. It takes an order only from plain SQL: not from
inside a ``{% %}`` block or a ``{{ }}`` expression, either of which may render nothing. It
does not follow a macro that builds an aggregate from pieces, nor a dollar-quoted string. It
is a tripwire for the ordinary way of writing these calls, which is the way all of them here
are written.

Two limits are accepted because they fail safe, flagging SQL that is fine and never passing
SQL that is not (owner, 2026-10-10): the exemption is read from a ``--`` comment, not from a
``/* */`` one; and an order has to stand outside all of a call's Jinja blocks, so one written
between two blocks, or once in each branch of an ``if``, is flagged. A rule that could not be
fooled would read the SQL dbt compiles, parsed; this one does not try to be that.
"""

import re
from pathlib import Path

import pytest

from _sql_text import NOT_NEWLINE, is_exempt, sql_code

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

# The BigQuery forms of the three ordered-aggregate macros (ADR 0051, 0053). BigQuery has no
# way to state the order of a float aggregate, so these three bodies, and no others, hold one
# without it; a model reaches them only through fo_sum_in_order / fo_avg_in_order /
# fo_corr_in_order, whose
# DuckDB forms state the order. Their bodies are not read as SQL here.
_UNORDERED_BY_NECESSITY = re.compile(
    r"\{%-?\s*macro\s+bigquery__fo_(?:sum|avg|corr)_in_order\b.*?\{%-?\s*endmacro\s*-?%\}",
    re.DOTALL,
)
_JINJA_EXPRESSION = re.compile(r"\{\{.*?\}\}", re.DOTALL)


def _arguments(code: str, start: int) -> str:
    """The text between the parenthesis that opens at `start - 1` and the one closing it, with
    nested parentheses emptied, everything from the first `{%` to the last `%}` left out, and
    every `{{ }}` expression too: what is left is the call's own, in every rendering."""
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
    if 0 <= first < last:
        text = text[:first] + " " + text[last + 2 :]
    # What a {{ }} expression renders is not known here either: an order has to be SQL.
    return _JINJA_EXPRESSION.sub(" ", text)


def unordered_aggregates(sql: str) -> list[tuple[int, str]]:
    """(line number, aggregate) for each statistical aggregate with no order and no exemption."""
    code = _UNORDERED_BY_NECESSITY.sub(lambda m: NOT_NEWLINE.sub(" ", m.group()), sql_code(sql))
    lines = sql.splitlines()
    found = []
    for match in _AGGREGATE.finditer(code):
        number = code.count("\n", 0, match.start()) + 1
        if _ORDER_BY.search(_arguments(code, match.end())) or is_exempt(lines, number, _EXEMPTION):
            continue
        found.append((number, match.group(1).lower()))
    return found


def _sql_files() -> list[Path]:
    return sorted(p for d in SCANNED_DIRS for p in (DBT_ROOT / d).rglob("*.sql"))


def test_every_statistical_aggregate_in_dbt_states_its_order() -> None:
    """Catches an `order by` removed from avg, corr or the like, or a new one written
    without it: the regression the last-digit unit tests only catch in most runs."""
    assert _sql_files(), "found no .sql files: DBT_ROOT is wrong"
    scanned = "\n".join(sql_code(p.read_text()) for p in _sql_files())
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
    dashes_in_double_quotes = 'select "-- order-exempt: an identifier", avg(x) from t'
    assert unordered_aggregates(dashes_in_double_quotes) == [(1, "avg")]
    escaped_in_jinja = 'select avg(x), {{ "\'a\\" -- order-exempt: no\'" }} from t'
    assert unordered_aggregates(escaped_in_jinja) == [(1, "avg")]
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
    # nor from inside a {{ }} expression, which can render empty just as well
    inline = 'select avg(score {{ "order by game_id" if false else "" }}) from t'
    assert unordered_aggregates(inline) == [(1, "avg")]


def test_the_limits_that_fail_safe_are_the_ones_accepted() -> None:
    """Pins two accepted limits (owner, 2026-10-10, PR #120): each flags SQL that is in fact
    ordered or exempt, so the author rewrites it; neither lets an unordered call through.
    Catches either one changing unnoticed.

    An exemption is read from a `--` comment only, not a block comment. An order between two
    separate Jinja blocks is left out with them: it has to stand outside all of the call's
    Jinja blocks.
    """
    in_a_block_comment = "select avg(x) /* order-exempt: whole numbers below 2^53 */ from t"
    assert unordered_aggregates(in_a_block_comment) == [(1, "avg")]
    between_blocks = (
        "select avg({% if a %} x {% else %} y {% endif %} order by k"
        " {% if b %}, j {% endif %}) from t"
    )
    assert unordered_aggregates(between_blocks) == [(1, "avg")]


def test_names_that_only_contain_an_aggregates_name_are_not_flagged() -> None:
    """Catches a scanner without word boundaries, and sum, median and count being swept in."""
    sql = "select moving_avg(x), sum(x), median(x), count(*), max(x), avg_score from t"
    assert unordered_aggregates(sql) == []


def test_an_aggregate_written_through_the_in_order_macros_is_in_order() -> None:
    """Catches the rule flagging a ported model: fo_avg_in_order is how a model of the
    BigQuery slice states the order (ADR 0051), and its DuckDB form writes the order by."""
    model = "select {{ fo_avg_in_order('margin', 'matchup_id') }} as mean_margin from t"
    assert unordered_aggregates(model) == []
    duckdb_form = (
        "{% macro duckdb__fo_avg_in_order(expression, order_by) %}\n"
        "    avg({{ expression }} order by {{ order_by }})\n"
        "{%- endmacro %}"
    )
    assert unordered_aggregates(duckdb_form) == []


def test_an_aggregate_written_through_fo_corr_in_order_is_in_order() -> None:
    """Catches the rule flagging a model that states a correlation's order through the macro
    (spec 0135), or its BigQuery form, which cannot state one, being flagged."""
    model = "select {{ fo_corr_in_order('y', 'x', 'k') }} as r from t"
    assert unordered_aggregates(model) == []
    bigquery_form = (
        "{% macro bigquery__fo_corr_in_order(y, x, order_by) %}\n"
        "    corr({{ y }}, {{ x }})\n"
        "{%- endmacro %}\n"
    )
    assert unordered_aggregates(bigquery_form) == []


def test_only_the_three_bigquery_forms_may_leave_the_order_out() -> None:
    """Catches the allowance widening: BigQuery cannot state the order, so the BigQuery
    forms of fo_sum_in_order and fo_avg_in_order hold an aggregate without one, and nothing
    else may, whatever it is named and wherever it stands in the same file."""
    allowed = (
        "{% macro bigquery__fo_avg_in_order(expression, order_by) %}\n"
        "    avg({{ expression }})\n"
        "{%- endmacro %}\n"
    )
    assert unordered_aggregates(allowed) == []
    other_form = allowed.replace("bigquery__fo_avg_in_order", "bigquery__fo_mean")
    assert unordered_aggregates(other_form) == [(2, "avg")]
    duckdb_form = allowed.replace("bigquery__", "duckdb__")
    assert unordered_aggregates(duckdb_form) == [(2, "avg")]
    after = allowed + "{% macro fo_other(x) %}\n    avg({{ x }})\n{%- endmacro %}\n"
    assert unordered_aggregates(after) == [(5, "avg")]
