"""The JavaScript function bodies in dbt/functions/ can be a UDF body (spec 0139, R3.4).

Beside `test_the_file_can_be_a_udf_body` of the lineup solver (test_solve_lineup_period.py),
which holds the same for the Python body.
"""

from pathlib import Path

import pytest

FUNCTIONS = Path(__file__).resolve().parents[2] / "dbt/functions"

# The two folds, named, not globbed: a glob over no files passes without reading anything.
# A third .js file is added here when it exists (and `test_no_js_file_is_left_unchecked`
# fails until it is).
BODIES = ("sum_in_order.js", "corr_in_order.js")


@pytest.mark.parametrize("name", BODIES)
def test_the_file_can_be_a_udf_body(name: str) -> None:
    """Catches a construct that breaks the function body: dbt renders it as Jinja and
    BigQuery wraps it in a triple-quoted string (r'''...'''), so neither delimiter may
    appear (ADR 0115). A missing file fails here, not skips."""
    text = (FUNCTIONS / name).read_text()
    assert text.strip(), f"{name} is empty"
    for forbidden in ("'''", "{{", "{%", "{#"):
        assert forbidden not in text


def test_no_js_file_is_left_unchecked() -> None:
    """Catches a new .js function that the list above does not name."""
    assert sorted(path.name for path in FUNCTIONS.glob("*.js")) == sorted(BODIES)
