"""The app with no extract (spec 0232 R6.3): one page that says so, and nothing else."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import front_office_dashboard

APP = Path(front_office_dashboard.__file__).parent / "app.py"


def test_with_no_extract_one_page_says_how_to_make_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a page that raises, or shows tables or pickers, over a missing file."""
    monkeypatch.setenv("FO_DASHBOARD_EXTRACT", str(tmp_path / "missing.duckdb"))
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    text = " ".join(e.value for e in at.error) + " ".join(m.value for m in at.markdown)
    assert "no extract" in text.lower()
    assert "front-office extract-marts" in " ".join(c.value for c in at.code)
    assert len(at.dataframe) == 0
    assert len(at.selectbox) == 0
    assert len(at.caption) == 0  # no freshness banner either: there is nothing to date
