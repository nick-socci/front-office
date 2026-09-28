"""Tests for the one module that talks to the network.

Every test injects an httpx.MockTransport, so nothing here opens a socket. Sleeping and
the clock are injected too, so retry/backoff behaviour is asserted without real waiting.
"""

import httpx
import pytest

from front_office.http_client import AuthExpired, HttpClient, RequestFailed, SourceLimits


class FakeClock:
    """Monotonic clock + sleep that advance only when the client asks them to."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make_client(handler, *, source: str = "mlb", limits: SourceLimits | None = None):
    clock = FakeClock()
    client = HttpClient(
        source=source,
        limits=limits or SourceLimits(min_interval_s=0.0, max_attempts=5, backoff_base_s=0.5),
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    return client, clock


def test_returns_json_on_success():
    client, clock = make_client(lambda request: httpx.Response(200, json={"ok": True}))
    response = client.get("https://example.test/api")
    assert response.json() == {"ok": True}
    assert clock.slept == []


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_retries_then_succeeds(status):
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) < 3:
            return httpx.Response(status)
        return httpx.Response(200, json={"ok": True})

    client, clock = make_client(handler)
    assert client.get("https://example.test/api").json() == {"ok": True}
    assert len(attempts) == 3
    # exponential backoff: 0.5s, then 1.0s
    assert clock.slept == [0.5, 1.0]


def test_gives_up_after_max_attempts():
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(503)

    client, _ = make_client(handler)
    with pytest.raises(RequestFailed) as exc:
        client.get("https://example.test/api")
    assert len(attempts) == 5
    assert "503" in str(exc.value)


@pytest.mark.parametrize(
    "error",
    [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError, httpx.RemoteProtocolError],
)
def test_retries_transport_errors_then_succeeds(error):
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) < 3:
            raise error("simulated", request=request)
        return httpx.Response(200, json={"ok": True})

    client, clock = make_client(handler)
    assert client.get("https://example.test/api").json() == {"ok": True}
    assert len(attempts) == 3
    assert clock.slept == [0.5, 1.0], "same exponential backoff as a retryable status"


def test_gives_up_on_transport_errors_after_max_attempts():
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.ConnectError("simulated", request=request)

    client, _ = make_client(handler)
    with pytest.raises(RequestFailed) as exc:
        client.get("https://example.test/api")
    assert len(attempts) == 5
    assert "ConnectError" in str(exc.value)
    assert isinstance(exc.value.__cause__, httpx.ConnectError)


def test_status_and_transport_failures_share_one_attempt_budget():
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) % 2:
            raise httpx.ReadTimeout("simulated", request=request)
        return httpx.Response(503)

    client, _ = make_client(handler)
    with pytest.raises(RequestFailed) as exc:
        client.get("https://example.test/api")
    assert len(attempts) == 5
    assert "ReadTimeout" in str(exc.value), "the last attempt's failure is reported"


def test_non_retryable_transport_error_raises_immediately():
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.UnsupportedProtocol("simulated", request=request)

    client, _ = make_client(handler)
    with pytest.raises(httpx.UnsupportedProtocol):
        client.get("https://example.test/api")
    assert len(attempts) == 1


def test_honours_retry_after_header():
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={})

    client, clock = make_client(handler)
    client.get("https://example.test/api")
    assert clock.slept == [7.0]


def test_espn_auth_failure_fails_fast():
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(401)

    client, _ = make_client(handler, source="espn")
    with pytest.raises(AuthExpired) as exc:
        client.get("https://example.test/api")
    assert len(attempts) == 1, "auth failures must not be retried"
    assert "ESPN_S2" in str(exc.value)


def test_non_retryable_client_error_raises_immediately():
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(404)

    client, _ = make_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        client.get("https://example.test/api")
    assert len(attempts) == 1


def test_enforces_minimum_interval_between_requests():
    client, clock = make_client(
        lambda request: httpx.Response(200, json={}),
        limits=SourceLimits(min_interval_s=1.5, max_attempts=5, backoff_base_s=0.5),
    )
    client.get("https://example.test/a")
    assert clock.slept == [], "first request should not wait"
    client.get("https://example.test/b")
    assert clock.slept == [1.5], "second request waits out the interval"


def test_interval_accounts_for_time_already_elapsed():
    client, clock = make_client(
        lambda request: httpx.Response(200, json={}),
        limits=SourceLimits(min_interval_s=1.5, max_attempts=5, backoff_base_s=0.5),
    )
    client.get("https://example.test/a")
    clock.now += 1.0  # a second of work happened in between
    client.get("https://example.test/b")
    assert clock.slept == [pytest.approx(0.5)]


def test_follows_redirects():
    """The SFBB player id map is served through a 307; not following it yields no data."""

    def handler(request):
        if request.url.path == "/PLAYERIDMAPCSV":
            return httpx.Response(307, headers={"Location": "https://example.test/final.csv"})
        return httpx.Response(200, text="MLBID,ESPNID\n430911,5933\n")

    client, _ = make_client(handler)
    response = client.get("https://example.test/PLAYERIDMAPCSV")
    assert response.status_code == 200
    assert "430911" in response.text
