"""The only module in this package that makes network calls.

Everything else asks this module for a response, which keeps three concerns in one place:
polite request spacing, retries on transient failures, and failing fast when ESPN's
cookies have expired. Tests inject a transport, a clock and a sleep function, so none of
that behaviour needs a socket or a real wait to verify.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

import httpx

ParamsType = Mapping[str, str | int] | list[tuple[str, str | int]] | None

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
AUTH_STATUSES = frozenset({401, 403})


class RequestFailed(RuntimeError):
    """A request kept failing with a retryable status until attempts ran out."""


class AuthExpired(RuntimeError):
    """Credentials were rejected. Retrying cannot help; a human must refresh them."""


@dataclass(frozen=True)
class SourceLimits:
    """How hard we are willing to lean on one API."""

    min_interval_s: float
    max_attempts: int = 5
    backoff_base_s: float = 0.5


# MLB's API is public and documented; ESPN's is neither, so it gets a gentler rate.
DEFAULT_LIMITS: Mapping[str, SourceLimits] = {
    "mlb": SourceLimits(min_interval_s=0.5),
    "espn": SourceLimits(min_interval_s=1.5),
    "idmap": SourceLimits(min_interval_s=1.0),
}

USER_AGENT = "front-office/0.1 (personal analytics project)"


class HttpClient:
    """An httpx client for one source, with spacing and retries applied to every request."""

    def __init__(
        self,
        source: str,
        *,
        limits: SourceLimits | None = None,
        transport: httpx.BaseTransport | None = None,
        cookies: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source = source
        self.limits = limits or DEFAULT_LIMITS.get(source, SourceLimits(min_interval_s=1.0))
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None
        self._client = httpx.Client(
            transport=transport,
            cookies=dict(cookies or {}),
            headers={"User-Agent": USER_AGENT, **dict(headers or {})},
            timeout=timeout,
        )

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(
        self,
        url: str,
        *,
        params: ParamsType = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """GET a URL, waiting out the rate limit and retrying transient failures."""
        # httpx's param types are invariant in their element types, so normalise here
        # rather than fight the annotation at every call site.
        query = None if params is None else httpx.QueryParams(cast("Any", params))
        last_status: int | None = None
        for attempt in range(1, self.limits.max_attempts + 1):
            self._wait_for_slot()
            response = self._client.get(url, params=query, headers=dict(headers or {}))
            self._last_request_at = self._monotonic()

            if response.status_code in AUTH_STATUSES:
                raise AuthExpired(self._auth_message(response.status_code))
            if response.status_code in RETRYABLE_STATUSES:
                last_status = response.status_code
                if attempt < self.limits.max_attempts:
                    self._sleep(self._retry_delay(response, attempt))
                continue
            response.raise_for_status()
            return response

        raise RequestFailed(
            f"{self.source}: gave up on {url} after {self.limits.max_attempts} attempts "
            f"(last status {last_status})"
        )

    def _auth_message(self, status: int) -> str:
        if self.source == "espn":
            return (
                f"ESPN returned {status}: cookies expired — refresh ESPN_S2/SWID in .env "
                "from a logged-in browser session"
            )
        return f"{self.source} returned {status}: credentials rejected"

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        """Honour Retry-After when the server sends one, else exponential backoff."""
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass  # a HTTP-date form we don't parse; fall back to backoff
        return self.limits.backoff_base_s * (2.0 ** (attempt - 1))

    def _wait_for_slot(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._monotonic() - self._last_request_at
        remaining = self.limits.min_interval_s - elapsed
        if remaining > 0:
            self._sleep(remaining)
