"""ADR 0051: a ported model holds no SQL that BigQuery refuses.

A model of the BigQuery slice (spec 0130) is written once. Where DuckDB and BigQuery accept
the same spelling it is plain SQL; everything else goes through a dispatched ``fo_*`` macro
with a ``duckdb__`` form and a ``bigquery__`` form. This scans the slice's models, its
singular tests, and every project macro they reach, directly or through another macro, for
the constructs BigQuery is known to refuse, and fails on one found anywhere but in a
``duckdb__`` form.

What is scanned is taken from dbt's manifest, not from a list kept here: the slice is the
selector ``bigquery_slice``, and a macro is reached if a selected node or a reached macro
depends on it. So a refused construct in a shared macro such as ``fo_boxscore_players`` is
found, and a model outside the slice is not scanned at all.

The list of constructs is what has been found, not what there is: building the slice on
BigQuery with ``--empty`` is what shows none is left (R4.7), and each one that turns up is
added here.

This reads SQL text with comments and single-quoted strings blanked; it does not parse SQL.
Three consequences, all accepted:

* ``unnest(`` is allowed in a ``bigquery__`` form, where it is in a FROM clause, and nowhere
  else: in a model it has to be ``fo_unnest``. A hand-written ``cross join unnest(...)`` in a
  model is flagged although BigQuery accepts it.
* a type name inside a single-quoted string, or itself in double quotes, is not seen, so
  that the schema text given to ``fo_json_parse`` (``"BIGINT"``, ``"VARCHAR"``) passes
  whether it is a string or a ``{% set %}`` block. A refused type handed to a macro as a
  string, ``fo_safe_cast('x', 'double')``, is caught by its own pattern on the raw text.
* a ``bigquery__`` form is scanned too, except for ``unnest(``: BigQuery SQL has no reason to
  hold DuckDB's spelling.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_dbt_ordered_aggregate_rule import _arguments, _code

REPO = Path(__file__).resolve().parents[2]
DBT_ROOT = REPO / "dbt"
DBT = Path(sys.executable).parent / "dbt"
SELECTOR = "bigquery_slice"
PROJECT = "front_office"

# (what, pattern), matched against code with comments and single-quoted strings blanked.
_REFUSED = (
    ("x::type cast", re.compile(r"::")),
    ("filter (where ...)", re.compile(r"\bfilter\s*\(", re.IGNORECASE)),
    ("try_cast", re.compile(r"\btry_cast\b", re.IGNORECASE)),
    ("unnest(", re.compile(r"\bunnest\s*\(", re.IGNORECASE)),
    ("generate_series / range", re.compile(r"\b(generate_series|range)\s*\(", re.IGNORECASE)),
    ("bool_or", re.compile(r"\bbool_or\s*\(", re.IGNORECASE)),
    ("epoch_ms", re.compile(r"\bepoch_ms\s*\(", re.IGNORECASE)),
    ("map_values", re.compile(r"\bmap_values\s*\(", re.IGNORECASE)),
    ("strptime", re.compile(r"\bstrptime\s*\(", re.IGNORECASE)),
    ("list(", re.compile(r"\blist\s*\(", re.IGNORECASE)),
    ("to_timestamp", re.compile(r"\bto_timestamp\s*\(", re.IGNORECASE)),
    ("regexp_extract", re.compile(r"\bregexp_extract\s*\(", re.IGNORECASE)),
    ("from_json", re.compile(r"\bfrom_json\b", re.IGNORECASE)),
    ("-> / ->> operator", re.compile(r"->")),
    ("at time zone", re.compile(r"\bat\s+time\s+zone\b", re.IGNORECASE)),
    ("strip_accents", re.compile(r"\bstrip_accents\s*\(", re.IGNORECASE)),
    ("union without all or distinct", re.compile(r"\bunion\b(?!\s+(all|distinct)\b)", re.I)),
    ("type varchar", re.compile(r"(?<!\")\bvarchar\b(?!\")", re.IGNORECASE)),
    ("type double", re.compile(r"(?<!\")\bdouble\b(?!\")", re.IGNORECASE)),
    ("type timestamptz", re.compile(r"(?<!\")\btimestamptz\b(?!\")", re.IGNORECASE)),
)
# BigQuery's own SQL may unnest, in a FROM clause; regexp_extract with two arguments is its
# spelling too.
_ALLOWED_IN_BIGQUERY_FORM = frozenset({"unnest(", "regexp_extract"})
# An aggregate BigQuery will not take an order inside.
_ORDERED_AGGREGATE = re.compile(r"\b(sum|avg|corr)\s*\(", re.IGNORECASE)
_ORDER_BY = re.compile(r"\border\s+by\b", re.IGNORECASE)
# A refused type handed to a macro as a Jinja string: hidden from the scan above, which
# blanks strings.
_TYPE_IN_MACRO_ARGUMENT = re.compile(
    r"\bfo_safe_cast\s*\([^)]*['\"]\s*(double|varchar|timestamptz)\s*['\"]", re.IGNORECASE
)
# In a model, the order of an aggregate is Jinja-free SQL; in a macro body the arguments
# are {{ }} expressions, which _arguments leaves out, so the keyword is looked for as is.


def refused_constructs(sql: str, *, bigquery_form: bool = False) -> list[tuple[int, str]]:
    """(line number, what) for each construct BigQuery refuses, outside comments and strings."""
    code = _code(sql)
    found: list[tuple[int, str]] = []
    for number, line in enumerate(code.splitlines(), start=1):
        for what, pattern in _REFUSED:
            if bigquery_form and what in _ALLOWED_IN_BIGQUERY_FORM:
                continue
            if pattern.search(line):
                found.append((number, what))
    for match in _ORDERED_AGGREGATE.finditer(code):
        if _ORDER_BY.search(_arguments(code, match.end())):
            number = code.count("\n", 0, match.start()) + 1
            found.append((number, f"{match.group(1).lower()}(... order by ...)"))
    for match in _TYPE_IN_MACRO_ARGUMENT.finditer(sql):
        number = sql.count("\n", 0, match.start()) + 1
        found.append((number, f"type {match.group(1).lower()}"))
    return sorted(set(found))


# -- what the slice reaches, from the manifest -------------------------------------------


def _dbt(target_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "FO_BQ_PROJECT"}
    env["DBT_PROFILES_DIR"] = str(DBT_ROOT)
    env["FO_CI_DUCKDB_PATH"] = str(target_path / "unused_ci.duckdb")
    return subprocess.run(
        [str(DBT), *args, "--target", "ci", "--target-path", str(target_path)],
        cwd=DBT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def reached_macros(macros: dict[str, dict[str, object]], start: set[str]) -> set[str]:
    """The project's macros reachable from `start`, following macro-to-macro dependencies."""
    seen: set[str] = set()
    queue = sorted(start)
    while queue:
        name = queue.pop()
        if name in seen or name not in macros or macros[name]["package_name"] != PROJECT:
            continue
        seen.add(name)
        queue.extend(macros[name]["depends_on"]["macros"])  # type: ignore[index]
        # The manifest is of a DuckDB target, so a dispatched macro depends on its duckdb__
        # form alone. Its BigQuery form is reached by name.
        prefix, _, short = name.rpartition(".")
        if short.startswith("duckdb__"):
            queue.append(f"{prefix}.bigquery__{short.removeprefix('duckdb__')}")
    return seen


def collect_slice_sources(target_path: Path) -> dict[str, tuple[str, bool]]:
    """{label: (sql, is a bigquery__ form)} for every model and singular test of the slice
    and every project macro they reach, `duckdb__` forms left out."""
    if not (DBT_ROOT / "dbt_packages" / "dbt_utils").exists():
        deps = subprocess.run(
            [str(DBT), "deps"],
            cwd=DBT_ROOT,
            env={**os.environ, "DBT_PROFILES_DIR": str(DBT_ROOT)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert deps.returncode == 0, deps.stdout + deps.stderr
    ls = _dbt(target_path, "ls", "--selector", SELECTOR, "--output", "json", "-q")
    assert ls.returncode == 0, ls.stdout + ls.stderr
    selected = {
        json.loads(line)["unique_id"] for line in ls.stdout.splitlines() if line.startswith("{")
    }
    manifest = json.loads((target_path / "manifest.json").read_text())
    sources: dict[str, tuple[str, bool]] = {}
    start: set[str] = set()
    for unique_id in selected:
        node = manifest["nodes"].get(unique_id)
        if node is None:  # a unit test
            continue
        start.update(node["depends_on"]["macros"])
        is_singular_test = node["resource_type"] == "test" and "test_metadata" not in node
        if node["resource_type"] == "model" or is_singular_test:
            path = str(node["original_file_path"])
            sources[path] = ((DBT_ROOT / path).read_text(), False)
    for name in reached_macros(manifest["macros"], start):
        macro = manifest["macros"][name]
        short = str(macro["name"])
        if short.startswith("duckdb__"):
            continue
        label = f"{macro['original_file_path']}::{short}"
        sources[label] = (str(macro["macro_sql"]), short.startswith("bigquery__"))
    return sources


@pytest.fixture(scope="module")
def slice_sources(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[str, bool]]:
    return collect_slice_sources(tmp_path_factory.mktemp("dbt_target"))


def test_the_slice_and_the_macros_it_reaches_hold_no_sql_bigquery_refuses(
    slice_sources: dict[str, tuple[str, bool]],
) -> None:
    """Catches a refused construct coming back into a ported model or singular test, or
    sitting in a shared macro one of them calls."""
    models = [label for label in slice_sources if label.startswith("models/")]
    macros = [label for label in slice_sources if label.startswith("macros/")]
    assert len(models) == 31, "the slice's models were not all found"
    assert any("boxscore_players.sql" in label for label in macros), "macros are not followed"
    assert any("json.sql::bigquery__" in label for label in macros), "bigquery forms not reached"
    assert not any("::duckdb__" in label for label in slice_sources)
    problems = [
        f"dbt/{label}:{number}: {what}"
        for label, (sql, bigquery_form) in sorted(slice_sources.items())
        for number, what in refused_constructs(sql, bigquery_form=bigquery_form)
    ]
    assert not problems, (
        "BigQuery refuses these; write the shared spelling or a dispatched fo_* macro "
        "(ADR 0051; line numbers of a macro count from its own first line):\n" + "\n".join(problems)
    )


# -- the check itself, on made-up SQL ---------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "what"),
    [
        ("select x::bigint from t", "x::type cast"),
        ("select count(*) filter (where c) from t", "filter (where ...)"),
        ("select sum(x) FILTER(where c) from t", "filter (where ...)"),
        ("select try_cast(x as bigint) from t", "try_cast"),
        ("select unnest(xs) as x from t", "unnest("),
        ("select * from generate_series(1, 3)", "generate_series / range"),
        ("select * from range(1, 3)", "generate_series / range"),
        ("select bool_or(c) from t", "bool_or"),
        ("select epoch_ms(n) from t", "epoch_ms"),
        ("select map_values(m) from t", "map_values"),
        ("select strptime(s, f) from t", "strptime"),
        ("select list(x) from t", "list("),
        ("select to_timestamp(n) from t", "to_timestamp"),
        ("select regexp_extract(s, p, 1) from t", "regexp_extract"),
        ("select from_json(j, s) from t", "from_json"),
        ("select j ->> k from t", "-> / ->> operator"),
        ("select ts at time zone z from t", "at time zone"),
        ("select strip_accents(s) from t", "strip_accents"),
        ("select 1 union select 2", "union without all or distinct"),
        ("select cast(x as varchar) from t", "type varchar"),
        ("select cast(x as DOUBLE) from t", "type double"),
        ("select cast(x as timestamptz) from t", "type timestamptz"),
        ("select sum(x order by k) from t", "sum(... order by ...)"),
        ("select avg(x\n order by k) from t", "avg(... order by ...)"),
        ("select corr(y, x order by k) from t", "corr(... order by ...)"),
    ],
)
def test_each_refused_construct_is_caught_with_its_line_number(sql: str, what: str) -> None:
    """Catches a scanner that misses one of the constructs, or reports the wrong line."""
    assert refused_constructs("select 1\n" + sql) == [(2, what)]


def test_the_shared_spellings_and_the_macro_calls_pass() -> None:
    """Catches a scanner that flags the rewrites themselves."""
    sql = (
        "select cast(x as integer), cast(y as {{ fo_type_float() }}),\n"
        "    count(case when c then 1 end), sum(case when c then x end),\n"
        "    {{ fo_safe_cast('x', 'bigint') }}, {{ fo_sum_in_order('x', 'k') }},\n"
        "    {{ fo_any_true('c') }}, sum(x), avg(x), string_agg(s, ',' order by k),\n"
        "    row_number() over (partition by a order by b) as n,\n"
        "    sum(x) over (order by k) as running, x_range, filtered\n"
        "from t {{ fo_unnest('t.xs', 'x') }}\n"
        "where d between a and b order by 1\n"
        "union all select 1 union distinct select 2 UNION  ALL select 3\n"
    )
    assert refused_constructs(sql) == []


def test_comments_and_schema_strings_are_not_flagged() -> None:
    """Catches a scanner that reads prose, or the DuckDB type names of a fo_json_parse
    schema, as SQL."""
    sql = (
        "-- was x::bigint, with try_cast and unnest(xs)\n"
        "{# strptime(s, f) and a double #}\n"
        "/* list(x) */\n"
        '{% set schema = \'[{"id": "BIGINT", "name": "VARCHAR", "v": "DOUBLE"}]\' %}\n'
        "select {{ fo_json_parse('payload', '$.a', schema) }} from t\n"
        '{% set block %}\n[{"name": "VARCHAR", "v": "DOUBLE"}]\n{% endset %}\n'
    )
    assert refused_constructs(sql) == []
    # outside quotes it is a type, also when a schema names it inside a larger type
    assert refused_constructs('{% set s %}[{"m": "MAP(VARCHAR, BIGINT)"}]{% endset %}') == [
        (1, "type varchar")
    ]


def test_a_refused_type_handed_to_a_macro_as_a_string_is_caught() -> None:
    """Catches `double` reaching BigQuery through a macro argument, where blanking strings
    would hide it."""
    assert refused_constructs("select {{ fo_safe_cast('x', 'double') }} from t") == [
        (1, "type double")
    ]
    assert refused_constructs('select {{ fo_safe_cast("x", "varchar") }} from t') == [
        (1, "type varchar")
    ]
    assert refused_constructs("select {{ fo_safe_cast('x', fo_type_float()) }} from t") == []


def test_a_bigquery_form_may_unnest_and_nothing_else() -> None:
    """Catches DuckDB's spelling left in a bigquery__ form, and the one allowance widening."""
    body = "cross join unnest(t.xs) as x"
    assert refused_constructs(body) == [(1, "unnest(")]
    assert refused_constructs(body, bigquery_form=True) == []
    assert refused_constructs("regexp_extract(c, p)", bigquery_form=True) == []
    assert refused_constructs("try_cast(x as int64)", bigquery_form=True) == [(1, "try_cast")]


def test_an_order_in_a_window_or_a_nested_call_is_not_an_ordered_aggregate() -> None:
    """Catches a window function's order, which BigQuery accepts, read as the aggregate's."""
    assert refused_constructs("select sum(x) over (partition by a order by b) from t") == []
    assert refused_constructs("select sum(f(x)) from t order by 1") == []
    assert refused_constructs("select sum(string_agg(s, ',' order by k)) from t") == []


def test_macros_are_followed_through_other_macros() -> None:
    """Catches a refused construct two calls away from a model, and a package's macro or a
    macro nothing in the slice calls being swept in."""
    macros: dict[str, dict[str, object]] = {
        "macro.front_office.a": {
            "package_name": "front_office",
            "depends_on": {"macros": ["macro.front_office.b", "macro.dbt_utils.x"]},
        },
        "macro.front_office.b": {
            "package_name": "front_office",
            "depends_on": {"macros": ["macro.front_office.a"]},
        },
        "macro.front_office.unused": {
            "package_name": "front_office",
            "depends_on": {"macros": []},
        },
        "macro.dbt_utils.x": {
            "package_name": "dbt_utils",
            "depends_on": {"macros": ["macro.front_office.unused"]},
        },
    }
    assert reached_macros(macros, {"macro.front_office.a", "macro.dbt.missing"}) == {
        "macro.front_office.a",
        "macro.front_office.b",
    }


def test_the_bigquery_form_of_a_dispatched_macro_is_reached_with_what_it_calls() -> None:
    """Catches the BigQuery forms going unscanned: dbt records, for a DuckDB target, only
    the duckdb__ form a dispatcher resolved to."""
    macros: dict[str, dict[str, object]] = {
        f"macro.front_office.{name}": {"package_name": "front_office", "depends_on": {"macros": d}}
        for name, d in (
            ("fo_x", ["macro.front_office.duckdb__fo_x"]),
            ("duckdb__fo_x", []),
            ("bigquery__fo_x", ["macro.front_office.bigquery__helper"]),
            ("bigquery__helper", []),
            ("bigquery__fo_unreached", []),
            ("duckdb__fo_only", []),
        )
    }
    assert reached_macros(
        macros, {"macro.front_office.fo_x", "macro.front_office.duckdb__fo_only"}
    ) == {
        "macro.front_office.fo_x",
        "macro.front_office.duckdb__fo_x",
        "macro.front_office.bigquery__fo_x",
        "macro.front_office.bigquery__helper",
        "macro.front_office.duckdb__fo_only",
    }
