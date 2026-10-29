"""ADR 0051: a ported model holds no SQL that BigQuery refuses.

A model of the BigQuery slice (spec 0130, widened to the whole project by spec 0135) is
written once. Where DuckDB and BigQuery accept
the same spelling it is plain SQL; everything else goes through a dispatched ``fo_*`` macro
with a ``duckdb__`` form and a ``bigquery__`` form. This scans the project's SQL models, its
singular tests, and every project macro they reach, directly or through another macro, for
the constructs BigQuery is known to refuse, and fails on one found anywhere but in a
``duckdb__`` form.

What is scanned is taken from dbt's manifest, not from a list kept here: every SQL model and
singular test of the project (the Python model is skipped), and a macro is reached if one of
them or a reached macro depends on it. So a refused construct in a shared macro such as
``fo_boxscore_players`` is found.

It also reads the unit tests' fixtures (spec 0138, ADR 0110), from the YAML text and not the
manifest, which holds an input only after the parse has resolved it. For each ``given``:

* a ``format: sql`` fixture, with ``{% raw %}`` and each ``{{ ... }}`` blanked (a ``}}`` inside
  a Jinja string does not end one), goes through ``refused_constructs`` (R5.1, R5.3);
* the macros its ``{{ ... }}`` call start the reach of macros scanned, as dbt records no
  dependency for a fixture, and so does dbt's ``bigquery__safe_cast`` override;
* an ``input`` naming ``source('raw', 'captures')`` or ``source('raw', 'api_responses')``
  fails, as each exists on one warehouse only (R2.2);
* a SQL fixture of a capture view that declares a structure must call ``fo_capture_rows(``
  (R3.4).

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
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import yaml

import check_plan_shapes as cps
from _sql_text import sql_code
from test_dbt_ordered_aggregate_rule import _arguments

REPO = Path(__file__).resolve().parents[2]
DBT_ROOT = REPO / "dbt"
DBT = Path(sys.executable).parent / "dbt"
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
    # BigQuery's md5 returns BYTES, not hex text (fo_md5_hex). Outside a bigquery__ form,
    # to_hex(md5(...)) is refused too: on DuckDB it is the hex of the hex text.
    ("md5", re.compile(r"\bmd5\s*\(", re.IGNORECASE)),
    ("concat_ws", re.compile(r"\bconcat_ws\s*\(", re.IGNORECASE)),
    # A VALUES list as a table: BigQuery has no table constructor (spec 0135, task 12).
    ("values list in from", re.compile(r"\(\s*values\s*\(", re.IGNORECASE)),
    # A CTE named with a word BigQuery reserves and DuckDB does not (spec 0135, task 11).
    (
        "CTE named a BigQuery reserved word",
        re.compile(
            r"(?:^|\bwith\b|,)\s*(?:groups|rows|range|window|lookup|rollup|cube|grouping|"
            r"partition|struct|array|hash|merge|enum|proto|define|qualify)\s+as\s*\(",
            re.IGNORECASE,
        ),
    ),
)
# BigQuery's own SQL may unnest, in a FROM clause; regexp_extract with two arguments is its
# spelling too.
_ALLOWED_IN_BIGQUERY_FORM = frozenset({"unnest(", "regexp_extract"})
# In a bigquery__ form, md5 is BigQuery's own only as the hex text DuckDB's md5 gives.
_MD5_AS_HEX = re.compile(r"\bto_hex\s*\(\s*md5\s*\(", re.IGNORECASE)
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
    code = sql_code(sql)
    found: list[tuple[int, str]] = []
    # Over the whole text, not line by line: a construct can span lines, as a fixture's
    # `from (values` with its first row on the next line does (spec 0138, task 1).
    for what, pattern in _REFUSED:
        if bigquery_form and what in _ALLOWED_IN_BIGQUERY_FORM:
            continue
        text = _MD5_AS_HEX.sub("to_hex(", code) if bigquery_form and what == "md5" else code
        for match in re.compile(pattern.pattern, pattern.flags | re.MULTILINE).finditer(text):
            found.append((text.count("\n", 0, match.start()) + 1, what))
    for match in _ORDERED_AGGREGATE.finditer(code):
        if _ORDER_BY.search(_arguments(code, match.end())):
            number = code.count("\n", 0, match.start()) + 1
            found.append((number, f"{match.group(1).lower()}(... order by ...)"))
    for match in _TYPE_IN_MACRO_ARGUMENT.finditer(sql):
        number = sql.count("\n", 0, match.start()) + 1
        found.append((number, f"type {match.group(1).lower()}"))
    for offset in _wheres_without_from(code):
        found.append((code.count("\n", 0, offset) + 1, "where without from"))
    return sorted(set(found))


_QUERY_TOKEN = re.compile(r"[();]|\b(?:select|from|where|union|intersect|except)\b", re.IGNORECASE)
_QUERY_ENDS = frozenset({";", "union", "intersect", "except"})


def _wheres_without_from(code: str) -> list[int]:
    """Offsets of each WHERE that belongs to a query with no FROM (spec 0138, R5.2).

    DuckDB takes ``select 1 as x where false``; BigQuery refuses it. For each ``select`` at
    parenthesis depth d, the query runs until the depth drops below d or a ``union``,
    ``intersect``, ``except`` or ``;`` comes at depth d. A ``from`` inside deeper
    parentheses (``extract(year from d)``) is not the query's FROM."""
    tokens = [(m.start(), m.group().lower()) for m in _QUERY_TOKEN.finditer(code)]
    # The depth each token sits at: an opening parenthesis at the depth outside it, a closing
    # one at the depth it returns to.
    depths: list[int] = []
    depth = 0
    for _, token in tokens:
        if token == ")":
            depth -= 1
        depths.append(depth)
        if token == "(":
            depth += 1
    found: list[int] = []
    for index, (_, token) in enumerate(tokens):
        if token != "select":
            continue
        base = depths[index]
        for at in range(index + 1, len(tokens)):
            offset, word = tokens[at]
            if depths[at] < base:
                break  # the parenthesis around the query closed
            if depths[at] > base:
                continue
            if word in _QUERY_ENDS or word in ("select", "from"):
                break
            if word == "where":
                found.append(offset)
                break
    return found


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


def load_manifest(target_path: Path) -> dict[str, Any]:
    """dbt's manifest of the project, parsed into `target_path`."""
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
    parse = _dbt(target_path, "parse", "-q")
    assert parse.returncode == 0, parse.stdout + parse.stderr
    manifest: dict[str, Any] = json.loads((target_path / "manifest.json").read_text())
    return manifest


def collect_project_sources(
    manifest: dict[str, Any], fixture_macros: frozenset[str] = frozenset()
) -> dict[str, tuple[str, bool]]:
    """{label: (sql, is a bigquery__ form)} for every SQL model and singular test of the
    project and every project macro they reach, `duckdb__` forms left out.

    dbt records no macro dependency for a unit test's fixture, so the macros the fixtures
    call (`fixture_macros`, short names) start the reach too, and so does dbt's `safe_cast`
    override, which dbt's fixture SQL calls and nothing in the project does (spec 0138)."""
    sources: dict[str, tuple[str, bool]] = {}
    start: set[str] = {f"macro.{PROJECT}.{name}" for name in fixture_macros}
    start.add(f"macro.{PROJECT}.bigquery__safe_cast")
    for node in manifest["nodes"].values():
        if node["package_name"] != PROJECT or node.get("language", "sql") != "sql":
            continue  # a package's node, or the Python model
        is_singular_test = node["resource_type"] == "test" and "test_metadata" not in node
        if node["resource_type"] == "model" or is_singular_test:
            start.update(node["depends_on"]["macros"])
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
def manifest(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return load_manifest(tmp_path_factory.mktemp("dbt_target"))


@pytest.fixture(scope="module")
def project_sources(manifest: dict[str, Any]) -> dict[str, tuple[str, bool]]:
    return collect_project_sources(manifest, fixture_macro_names(unit_test_fixtures()))


def test_the_slice_and_the_macros_it_reaches_hold_no_sql_bigquery_refuses(
    project_sources: dict[str, tuple[str, bool]],
) -> None:
    """Catches a refused construct coming back into a ported model or singular test, or
    sitting in a shared macro one of them calls."""
    models = [label for label in project_sources if label.startswith("models/")]
    macros = [label for label in project_sources if label.startswith("macros/")]
    # Every SQL model of the project (spec 0135): 75. Of these, 34 are the models of spec
    # 0130, nine the capture views they read (spec 0150), two the games-started limit models
    # (spec 0152), three added by spec 0147 (stg_espn__matchup_player_lines,
    # rec_espn__matchup_line_totals and rec_espn__winner_differences), the lineup solver's
    # model, which was a Python model until spec 0137, and the 26 others are ported by spec
    # 0135.
    assert len(models) == 75, "the project's SQL models were not all found"
    assert any("boxscore_players.sql" in label for label in macros), "macros are not followed"
    assert any("json.sql::bigquery__" in label for label in macros), "bigquery forms not reached"
    assert not any("::duckdb__" in label for label in project_sources)
    problems = [
        f"dbt/{label}:{number}: {what}"
        for label, (sql, bigquery_form) in sorted(project_sources.items())
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
        ("select md5(s) from t", "md5"),
        ("select concat_ws('|', a, b) from t", "concat_ws"),
        ("with groups as (select 1)", "CTE named a BigQuery reserved word"),
        ("cross join (values ('a'), ('b')) as t (x)", "values list in from"),
        # Across lines, as a fixture writes it (spec 0138, task 1): matched over the text.
        ("select * from (values\n    ('a'),\n    ('b')) as t (x)", "values list in from"),
        ("), rows as (select 1)", "CTE named a BigQuery reserved word"),
        ("groups as (", "CTE named a BigQuery reserved word"),
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
        "where {{ fo_solve_lineup_period() }}(a, {{ fo_struct([('a', 'x')]) }}) is null\n"
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
    # md5 is allowed only as to_hex(md5(...)), the hex text that DuckDB's md5 gives
    assert refused_constructs("to_hex(md5(s))", bigquery_form=True) == []
    assert refused_constructs("md5(s)", bigquery_form=True) == [(1, "md5")]
    assert refused_constructs("to_hex(md5(s))") == [(1, "md5")]


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


def macro_forms(name: str) -> dict[str, str]:
    """The duckdb__ and bigquery__ bodies of a macro of portable.sql, by form."""
    text = (DBT_ROOT / "macros" / "portable.sql").read_text()
    forms = {}
    for form in ("duckdb", "bigquery"):
        match = re.search(
            rf"\{{% macro {form}__{name}\([^)]*\) -?%\}}(.*?)\{{%-? endmacro %\}}", text, re.S
        )
        assert match, f"{form}__{name} not found"
        forms[form] = match.group(1)
    return forms


def test_the_struct_and_solver_macros_keep_duckdb_syntax_in_the_duckdb_form() -> None:
    """Catches the lineup solver's two macros (spec 0137) leaking DuckDB's spelling into the
    BigQuery form: struct_pack(name := x) is DuckDB's, struct(x as name) is BigQuery's, and
    the solver is a bare name on DuckDB but a dbt function resource on BigQuery."""
    struct = macro_forms("fo_struct")
    assert ":=" in struct["duckdb"] and "struct_pack" in struct["duckdb"]
    assert ":=" not in struct["bigquery"] and "struct_pack" not in struct["bigquery"]
    assert " as " in struct["bigquery"]
    solver = macro_forms("fo_solve_lineup_period")
    assert solver["duckdb"].strip() == "solve_lineup_period"
    assert "function('solve_lineup_period')" in solver["bigquery"]
    for body in (struct["bigquery"], solver["bigquery"]):
        assert refused_constructs(body, bigquery_form=True) == []
    assert refused_constructs(struct["duckdb"]) == []


# -- unit-test fixtures, from the YAML text (spec 0138, ADR 0110) -------------------------

# The two sources a unit test must not name literally: they exist on one warehouse each.
_LITERAL_MANIFEST_INPUT = re.compile(
    r"^\s*source\(\s*['\"]raw['\"]\s*,\s*['\"](?:captures|api_responses)['\"]\s*\)\s*$"
)
_CAPTURE_VIEW_INPUT = re.compile(r"^\s*ref\(\s*['\"](stg_raw__\w+)['\"]\s*\)\s*$")
_RAW_TAG = re.compile(r"\{%-?\s*(?:end)?raw\s*-?%\}")
_MACRO_CALL = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\(")


class Fixture(NamedTuple):
    path: str  # the YAML file, from the repo root
    test: str  # the unit test's name
    input: str  # the `input:` of the `given` entry
    format: str
    rows: object  # SQL text for `format: sql`; a list of mappings for `dict`


def unit_test_fixtures(root: Path = DBT_ROOT / "models") -> Iterator[Fixture]:
    """Each `given` of each unit test in the model YAML under `root`.

    Read from the YAML text: the manifest holds an input after the parse has resolved it.
    A fixture given by `fixture:` (a file under tests/fixtures/) is not read: this project
    has none (spec 0138, C7), and a file there would be compiled with the project's macros
    and need no blanking."""
    for path in sorted(root.rglob("*.yml")):
        document = yaml.safe_load(path.read_text())
        if not isinstance(document, dict):
            continue
        for unit_test in document.get("unit_tests") or []:
            for given in unit_test.get("given") or []:
                yield Fixture(
                    str(path.relative_to(REPO)),
                    str(unit_test["name"]),
                    str(given.get("input", "")),
                    str(given.get("format", "dict")),
                    given.get("rows"),
                )


def _jinja_expression_end(text: str, start: int) -> int:
    """The offset just after the `}}` that closes the expression whose `{{` ends at `start`.
    A `}}` inside a Jinja string literal (JSON text, say) does not close it."""
    quote = ""
    at = start
    while at < len(text):
        char = text[at]
        if quote:
            if char == "\\":
                at += 1  # the escaped character cannot close the string
            elif char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif text.startswith("}}", at):
            return at + 2
        at += 1
    return len(text)


def _blank(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def blank_jinja(rows: str) -> tuple[str, list[str]]:
    """`rows` with `{% raw %}`, `{% endraw %}` and each `{{ ... }}` blanked, newlines kept so
    line numbers hold, and the text of each expression."""
    out: list[str] = []
    expressions: list[str] = []
    at = 0
    while at < len(rows):
        open_at = rows.find("{{", at)
        if open_at < 0:
            break
        end = _jinja_expression_end(rows, open_at + 2)
        out.append(rows[at:open_at])
        out.append(_blank(rows[open_at:end]))
        expressions.append(rows[open_at + 2 : end - 2])
        at = end
    out.append(rows[at:])
    return _RAW_TAG.sub(lambda tag: _blank(tag.group()), "".join(out)), expressions


def macro_names(expression: str) -> set[str]:
    """The macros called in a Jinja expression: a name straight before `(`, outside string
    literals, nested calls included."""
    code = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", "''", expression)
    return set(_MACRO_CALL.findall(code))


def fixture_macro_names(fixtures: Iterator[Fixture]) -> frozenset[str]:
    names: set[str] = set()
    for fixture in fixtures:
        if fixture.format == "sql" and isinstance(fixture.rows, str):
            for expression in blank_jinja(fixture.rows)[1]:
                names |= macro_names(expression)
    return frozenset(names)


def fixture_problems(fixtures: Iterator[Fixture], capture_views: set[str]) -> list[str]:
    """The fixtures that name a manifest input literally (R2.2), hold a construct BigQuery
    refuses (R5.3), or give a capture view's rows without fo_capture_rows (R3.4), as
    `<yaml>::<unit test>::<input>:<line>: <what>`."""
    problems: list[str] = []
    for fixture in fixtures:
        where = f"{fixture.path}::{fixture.test}::{fixture.input}"
        if _LITERAL_MANIFEST_INPUT.match(fixture.input):
            problems.append(
                f"{where}:1: manifest input named literally (use the target-dependent "
                "spelling of spec 0138, design 3)"
            )
        if fixture.format != "sql" or not isinstance(fixture.rows, str):
            continue
        view = _CAPTURE_VIEW_INPUT.match(fixture.input)
        if view and view.group(1) in capture_views and "fo_capture_rows(" not in fixture.rows:
            problems.append(f"{where}:1: capture view fixture without fo_capture_rows")
        code, _ = blank_jinja(fixture.rows)
        problems.extend(f"{where}:{n}: {what}" for n, what in refused_constructs(code))
    return problems


def capture_view_names(manifest: dict[str, Any]) -> set[str]:
    """The views that declare a structure, as the plan-shapes gate finds them."""
    nodes = manifest["nodes"]
    return {nodes[unique_id]["name"] for unique_id in cps.heavy_views(nodes)}


def test_the_views_that_declare_a_structure_are_found(manifest: dict[str, Any]) -> None:
    """Catches a lookup that finds no view, which would let every capture fixture pass."""
    assert capture_view_names(manifest) == {
        "stg_raw__espn_roster",
        "stg_raw__espn_matchup_days",
        "stg_raw__mlb_boxscore",
        "stg_raw__mlb_schedule",
    }


def test_unit_test_fixtures_hold_nothing_bigquery_refuses(manifest: dict[str, Any]) -> None:
    """Catches a unit test that cannot run on BigQuery: a source named literally (R2.2), a
    capture view's rows not given through fo_capture_rows (R3.4), or a SQL fixture with a
    construct BigQuery refuses (R5.1, R5.3)."""
    fixtures = list(unit_test_fixtures())
    assert any(f.format == "sql" for f in fixtures), "no SQL fixture was found"
    problems = fixture_problems(iter(fixtures), capture_view_names(manifest))
    assert not problems, (
        "these unit-test fixtures would not run on BigQuery (spec 0138):\n" + "\n".join(problems)
    )


@pytest.mark.parametrize(
    "sql",
    [
        "select 1 as x where false",
        "select 1 as x\nwhere false",
        "select * from t where c union all select 1 as x where c",
        "select * from (select 1 as x where c) as s",
        "with a as (select 1 as x where c) select * from a",
    ],
)
def test_a_where_in_a_query_with_no_from_is_caught(sql: str) -> None:
    """Catches `select 1 where c`, which DuckDB takes and BigQuery refuses (R5.2)."""
    assert [what for _, what in refused_constructs(sql)] == ["where without from"]


@pytest.mark.parametrize(
    "sql",
    [
        "select 1 from t where c",
        "select extract(year from d) as y from t where c",
        "select substring(s from 1) as y from t where c",
        "select * from (select 1 as x) as s where x = 1",
        "select 1 as x union all select 2 as x",
        "select a, (select max(b) from u where u.k = t.k) as m from t where c",
        "select count(*) as n from t where c; select 1 as y",
    ],
)
def test_a_where_that_has_its_from_is_not_caught(sql: str) -> None:
    """Catches a from inside parentheses (extract, substring) read as the query's FROM, a
    subquery's from mistaken for the outer one's, and a WHERE with a FROM flagged."""
    assert refused_constructs(sql) == []


def test_the_line_of_a_where_without_from_is_reported() -> None:
    """Catches the wrong line reported for the WHERE."""
    assert refused_constructs("select 1 as a\nunion all\nselect 2 as a\nwhere c") == [
        (4, "where without from")
    ]


def test_a_jinja_expression_ends_at_a_closing_brace_pair_outside_its_strings() -> None:
    """Catches `}}` inside a JSON string literal ending the expression, which would leave
    the rest of the call to be read as SQL and shift nothing but the verdict."""
    rows = (
        "select {{ fo_capture_rows('espn', 'roster', "
        "[{'payload': '{\"a\": {\"b\": 1}} x::int'}]) }}\n"
        "from t where x::bigint"
    )
    code, expressions = blank_jinja(rows)
    assert len(expressions) == 1 and '\'{"a": {"b": 1}} x::int\'' in expressions[0]
    assert code.count("\n") == rows.count("\n") and len(code) == len(rows)
    assert refused_constructs(code) == [(2, "x::type cast")]
    # an escaped quote does not end the string either
    code, expressions = blank_jinja("a {{ f('it\\'s }} here') }} b::int")
    assert expressions == [" f('it\\'s }} here') "] and refused_constructs(code) == [
        (1, "x::type cast")
    ]


def test_raw_tags_are_blanked_with_the_expressions() -> None:
    """Catches {% raw %} text read as SQL, or a line number shifted by the blanking."""
    code, _ = blank_jinja("{% raw %}\nselect {{ x::int }}\n{% endraw %}\nselect y::int")
    assert code.count("\n") == 3 and refused_constructs(code) == [(4, "x::type cast")]


def test_macro_names_are_taken_from_nested_calls_outside_strings() -> None:
    """Catches a nested call missed (the reach would skip fo_int_series) and a macro named
    inside a string, or a method call, taken for a call."""
    assert macro_names("fo_unnest(fo_int_series(1, 100))") == {"fo_unnest", "fo_int_series"}
    assert macro_names("fo_capture_rows('espn', 'roster', [{'a': 'fo_hidden(1)'}])") == {
        "fo_capture_rows"
    }
    assert macro_names("x.get('k') if target.type == 'bigquery' else y") == set()
    assert fixture_macro_names(
        iter([Fixture("f.yml", "t", "ref('m')", "sql", "{{ fo_a(fo_b(1)) }} x {{ fo_c() }}")])
    ) == {"fo_a", "fo_b", "fo_c"}


_TARGET_INPUT = (
    "source('raw', '{{ 'api_responses' if target.type == 'bigquery' else 'captures' }}')"
)


@pytest.mark.parametrize(
    "given",
    [
        "source('raw', 'captures')",
        'source("raw", "api_responses")',
        "source( 'raw' ,'captures' )",
    ],
)
def test_a_source_named_literally_is_refused_and_the_target_spelling_passes(given: str) -> None:
    """Catches a unit test that names raw.captures or raw.api_responses, each of which
    exists on one warehouse only (R2.2), and the accepted spelling flagged."""
    refused = Fixture("dbt/models/m.yml", "a_test", given, "dict", [])
    allowed = Fixture("dbt/models/m.yml", "a_test", _TARGET_INPUT, "dict", [])
    problems = fixture_problems(iter([refused]), set())
    assert len(problems) == 1
    assert problems[0].startswith(f"dbt/models/m.yml::a_test::{given}:")
    assert fixture_problems(iter([allowed]), set()) == []


def test_a_capture_fixture_must_go_through_fo_capture_rows() -> None:
    """Catches rows given to a capture view that declares a structure by hand (R3.4), and
    flagging a fixture that does call fo_capture_rows, or a view with no structure."""
    heavy = {"stg_raw__mlb_schedule"}
    by_hand = Fixture(
        "dbt/models/m.yml", "t", "ref('stg_raw__mlb_schedule')", "sql", "select 1 as game_pk"
    )
    problems = fixture_problems(iter([by_hand]), heavy)
    assert problems == [
        "dbt/models/m.yml::t::ref('stg_raw__mlb_schedule'):1: "
        "capture view fixture without fo_capture_rows"
    ]
    through = by_hand._replace(rows="{% raw %}select * from {{ fo_capture_rows('mlb', 's', []) }}")
    assert fixture_problems(iter([through]), heavy) == []
    plain = by_hand._replace(input="ref('stg_raw__mlb_players')")
    assert fixture_problems(iter([plain]), heavy) == []


def test_a_refused_construct_in_a_sql_fixture_is_named_with_its_line() -> None:
    """Catches a fixture's SQL going unscanned, or reported without the unit test's name
    and the line (R5.3)."""
    fixture = Fixture(
        "dbt/models/m.yml", "t", "ref('x')", "sql", "select 1 as a\nunion all\nselect '2'::int as a"
    )
    assert fixture_problems(iter([fixture]), set()) == [
        "dbt/models/m.yml::t::ref('x'):3: x::type cast"
    ]
    assert fixture_problems(iter([fixture._replace(format="dict")]), set()) == []


def test_the_fixture_macros_and_safe_cast_start_the_reach(manifest: dict[str, Any]) -> None:
    """Catches a macro called only from a fixture going unscanned (dbt records no
    dependency for it)."""
    sources = collect_project_sources(manifest, frozenset({"fo_int_series"}))
    assert (
        any("::fo_int_series" in label or "::bigquery__fo_int_series" in label for label in sources)
        or f"macro.{PROJECT}.fo_int_series" not in manifest["macros"]
    )
