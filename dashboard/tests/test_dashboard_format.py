"""Display-only formatting (spec 0232 R3.3, R3.4)."""

import pandas as pd
import pytest

from front_office_dashboard import format as fmt


@pytest.mark.parametrize(
    ("outs", "shown"),
    [(19, "6.1"), (20, "6.2"), (21, "7.0"), (0, "0.0"), (1, "0.1"), (3, "1.0"), (None, "")],
)
def test_innings_are_whole_innings_and_thirds(outs: int | None, shown: str) -> None:
    """Catches decimal innings: 19 outs is 6 and a third, written 6.1, never 6.33 or 6.1 / 3."""
    assert fmt.innings(outs) == shown


def test_innings_of_a_missing_pandas_value_is_empty() -> None:
    """Catches a NaN or NA from a nullable column reaching int()."""
    assert fmt.innings(float("nan")) == ""
    assert fmt.innings(pd.NA) == ""


def test_innings_column_leaves_the_outs_alone() -> None:
    """Catches the formatted text replacing the number: the outs column stays for arithmetic."""
    frame = pd.DataFrame({"outs_recorded": [19, None, 21]})
    shown = fmt.with_innings(frame)
    assert list(shown["innings"]) == ["6.1", "", "7.0"]
    assert list(frame.columns) == ["outs_recorded"]


def test_rows_with_either_flag_are_marked() -> None:
    """Catches an unverified or unvalued row shown unmarked (R3.4)."""
    frame = pd.DataFrame(
        {
            "x": [1, 2, 3, 4],
            "has_unverified_inputs": [True, False, False, None],
            "is_unvalued": [False, True, False, False],
        }
    )
    marked = fmt.mark_flags(frame)
    assert list(marked.columns)[0] == "flag"
    assert list(marked["flag"]) == ["⚠", "⚠", "", ""]


def test_a_frame_with_one_flag_column_is_marked_by_it() -> None:
    frame = pd.DataFrame({"has_unverified_inputs": [True, False]})
    assert list(fmt.mark_flags(frame)["flag"]) == ["⚠", ""]


def test_a_frame_with_no_flag_column_is_unchanged() -> None:
    frame = pd.DataFrame({"x": [1]})
    assert list(fmt.mark_flags(frame).columns) == ["x"]
