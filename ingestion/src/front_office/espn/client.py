"""ESPN credentials and client construction.

This is the only module that reads ESPN credentials. They are session cookies for a real
ESPN account, so they must never reach a landing file, a metadata sidecar, a log line or
a traceback -- hence the custom repr and the absence of any logging of their values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from front_office.http_client import HttpClient

# ESPN's read-only host for league data.
BASE_HOST = "https://lm-api-reads.fantasy.espn.com"
GAME = "flb"  # fantasy baseball


class MissingCredentials(RuntimeError):
    """ESPN credentials are absent or incomplete."""


@dataclass(frozen=True)
class EspnCredentials:
    """Cookies for a logged-in ESPN session, plus the league they apply to."""

    espn_s2: str
    swid: str
    league_id: str

    def __repr__(self) -> str:
        # Deliberately opaque: these values are live session credentials.
        return f"EspnCredentials(league_id={self.league_id!r}, cookies=<redacted>)"

    @classmethod
    def from_env(cls) -> EspnCredentials:
        """Read credentials from the environment only.

        Loading .env is the CLI's job (see load_env_file): keeping it out of here means
        this function has no hidden dependency on the working directory, and the
        missing-credentials path is testable.
        """
        values = {name: os.getenv(name) for name in ("ESPN_S2", "SWID", "LEAGUE_ID")}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise MissingCredentials(
                f"missing {', '.join(missing)}. Add them to .env in the repo root "
                "(gitignored): copy espn_s2 and SWID from a logged-in browser session, "
                "and LEAGUE_ID from your league URL."
            )
        return cls(
            espn_s2=str(values["ESPN_S2"]),
            swid=str(values["SWID"]),
            league_id=str(values["LEAGUE_ID"]),
        )

    def cookies(self) -> dict[str, str]:
        return {"espn_s2": self.espn_s2, "SWID": self.swid}


def load_env_file(dotenv_path: Path | None = None) -> None:
    """Load .env into the environment. Called once, at the CLI edge."""
    load_dotenv(dotenv_path)


def league_url(season: int, league_id: str) -> str:
    return f"{BASE_HOST}/apis/v3/games/{GAME}/seasons/{season}/segments/0/leagues/{league_id}"


def espn_client(credentials: EspnCredentials) -> HttpClient:
    """An HttpClient carrying the session cookies. 401/403 fails fast, not retried."""
    return HttpClient("espn", cookies=credentials.cookies())
