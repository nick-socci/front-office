"""The committed Streamlit settings (spec 0232, ADR 0146)."""

import tomllib
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml"


def test_the_app_makes_no_call_out_and_sends_no_usage_stats() -> None:
    """Catches the app contacting an outside service at start: with `server.address` 0.0.0.0
    (the container) and headless, Streamlit looks up the public IP unless `browser.serverAddress`
    is set; and usage stats, which are on by default."""
    settings = tomllib.loads(CONFIG.read_text())
    assert settings["browser"]["serverAddress"] == "localhost"
    assert settings["browser"]["gatherUsageStats"] is False
    assert settings["server"]["headless"] is True
    assert settings["server"]["enableXsrfProtection"] is True
