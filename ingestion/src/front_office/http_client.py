"""The only module in this package that makes network calls.

Everything else asks this module for a response, which keeps three concerns in one place:
polite request spacing, retries on transient failures, and failing fast when ESPN's
cookies have expired. Tests inject a transport, a clock and a sleep function, so none of
that behaviour needs a socket or a real wait to verify.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import httpx

# Sequence (covariant) rather than list (invariant), so callers can pass a
# list[tuple[str, str]] without a type error; the values are normalised below.
ParamsType = Mapping[str, str | int] | Sequence[tuple[str, str | int]] | None

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
AUTH_STATUSES = frozenset({401, 403})
# Failures where no usable response arrived but a retry may succeed: timeouts, dropped or
# refused connections, and a server hanging up mid-response. Not included: errors a retry
# cannot fix, such as an unsupported URL scheme or a misconfigured proxy.
RETRYABLE_TRANSPORT_ERRORS: tuple[type[httpx.TransportError], ...] = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


class RequestFailed(RuntimeError):
    """A request kept failing retryably (status or transport) until attempts ran out."""


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
        follow_redirects: bool = True,
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
            # Redirects are followed by default: the SFBB id map is served through one,
            # and httpx would otherwise hand back a 307 as if it were the answer.
            follow_redirects=follow_redirects,
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
        last_failure = "none"
        last_error: httpx.TransportError | None = None
        for attempt in range(1, self.limits.max_attempts + 1):
            self._wait_for_slot()
            try:
                response = self._client.get(url, params=query, headers=dict(headers or {}))
            except RETRYABLE_TRANSPORT_ERRORS as error:
                self._last_request_at = self._monotonic()
                last_failure, last_error = type(error).__name__, error
                if attempt < self.limits.max_attempts:
                    self._sleep(self._backoff(attempt))
                continue
            self._last_request_at = self._monotonic()

            if response.status_code in AUTH_STATUSES:
                raise AuthExpired(self._auth_message(response.status_code))
            if response.status_code in RETRYABLE_STATUSES:
                last_failure, last_error = f"status {response.status_code}", None
                if attempt < self.limits.max_attempts:
                    self._sleep(self._retry_delay(response, attempt))
                continue
            response.raise_for_status()
            return response

        raise RequestFailed(
            f"{self.source}: gave up on {url} after {self.limits.max_attempts} attempts "
            f"(last failure: {last_failure})"
        ) from last_error

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
        return self._backoff(attempt)

    def _backoff(self, attempt: int) -> float:
        return self.limits.backoff_base_s * (2.0 ** (attempt - 1))

    def _wait_for_slot(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._monotonic() - self._last_request_at
        remaining = self.limits.min_interval_s - elapsed
        if remaining > 0:
            self._sleep(remaining)
