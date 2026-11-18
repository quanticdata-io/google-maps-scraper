from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from gmaps_places.api import (
    AuthenticationError,
    InputError,
    PaymentRequiredError,
    QuanticDataClient,
    QuanticDataError,
    RateLimitError,
    RunTimeoutError,
)
from gmaps_places.engines import CollectorRunError, QuanticDataEngine, place_from_row

KEY = "qd_test_abc123"
Handler = Callable[[httpx.Request, int], httpx.Response]


def ok(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"type": "response", "message": "OK", "payload": payload})


def err(
    status: int, message: str, payload: Any = None, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status, json={"type": "error", "message": message, "payload": payload}, headers=headers
    )


def make(handler: Handler, **kw: Any) -> tuple[QuanticDataClient, list[httpx.Request], list[float]]:
    calls: list[httpx.Request] = []
    sleeps: list[float] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request, len(calls))

    client = QuanticDataClient(
        KEY,
        base_url="https://api.test/v1",
        transport=httpx.MockTransport(transport),
        sleep=sleeps.append,
        **kw,
    )
    return client, calls, sleeps


ROW = {
    "rank": 1,
    "name": "Example Place",
    "rating": 4.5,
    "reviews": 120,
    "category": "Cafe",
    "address": "1 Example St",
    "phone": "+1 555-010-0001",
    "website": "cafe.example",
    "latitude": 40.7,
    "longitude": -73.9,
    "place_id": "ChIJx",
    "data_id": "0x1:0x2",
    "found_by": "cafe Springfield",
}


def test_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUANTICDATA_API_KEY", raising=False)
    with pytest.raises(AuthenticationError, match="No API key"):
        QuanticDataClient()


def test_env_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTICDATA_API_KEY", KEY)
    monkeypatch.setenv("QUANTICDATA_API_BASE", "http://127.0.0.1:9/v1/")
    assert QuanticDataClient().base_url == "http://127.0.0.1:9/v1"


def test_sync_run_sends_wrapped_input_and_bearer() -> None:
    client, calls, _ = make(lambda r, n: ok({"run_id": "r1", "status": "done", "count": 1, "results": [ROW]}))
    run = client.run({"query": "cafe", "location": "Springfield", "max_results": 5})
    assert run["count"] == 1
    req = calls[0]
    assert req.method == "POST"
    assert req.url.path == "/v1/scraper/collectors/google_maps_places/run"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(req.content) == {
        "input": {"query": "cafe", "location": "Springfield", "max_results": 5}
    }


def test_queued_run_is_polled_until_done() -> None:
    def handler(r: httpx.Request, n: int) -> httpx.Response:
        if r.method == "POST":
            return ok(
                {"run_id": "r9", "status": "queued", "statusUrl": "/api/v1/scraper/collectors/runs/r9"}, 202
            )
        return ok({"run_id": "r9", "status": "running" if n < 4 else "done", "count": 1, "results": [ROW]})

    client, calls, sleeps = make(handler)
    seen: list[str] = []
    run = client.run(
        {"query": "q", "location": "l"},
        background=True,
        poll_interval=0.5,
        on_progress=lambda r: seen.append(r["status"]),
    )
    assert run["status"] == "done"
    assert json.loads(calls[0].content)["async"] is True
    assert [c.url.path for c in calls[1:]] == ["/v1/scraper/collectors/runs/r9"] * 3
    assert seen == ["running", "running", "done"]
    assert sleeps == [0.5, 0.5]


def test_wait_times_out() -> None:
    client, _, _ = make(lambda r, n: ok({"run_id": "r1", "status": "running"}))
    with pytest.raises(RunTimeoutError, match="keeps running"):
        client.wait_for_run("r1", poll_interval=10, timeout=1)


@pytest.mark.parametrize(
    ("status", "cls"),
    [(401, AuthenticationError), (402, PaymentRequiredError), (422, InputError), (404, QuanticDataError)],
)
def test_errors_map_to_classes(status: int, cls: type[QuanticDataError]) -> None:
    client, _, _ = make(lambda r, n: err(status, "nope", {"code": "X"}))
    with pytest.raises(cls) as info:
        client.start_run({"query": "q", "location": "l"})
    assert info.value.status == status
    assert info.value.message == "nope"
    assert info.value.code == "X"


def test_error_envelope_with_http_200_is_an_error() -> None:
    client, _, _ = make(lambda r, n: httpx.Response(200, json={"type": "error", "message": "bad"}))
    with pytest.raises(QuanticDataError, match="bad"):
        client.get_run("r1")


def test_429_is_retried_with_retry_after() -> None:
    def handler(r: httpx.Request, n: int) -> httpx.Response:
        if n == 1:
            return err(429, "slow down", headers={"Retry-After": "2"})
        return ok({"run_id": "r1", "status": "done", "results": []})

    client, calls, sleeps = make(handler)
    client.run({"query": "q", "location": "l"})
    assert len(calls) == 2
    assert sleeps == [2.0]


def test_long_429_wait_is_not_slept_through() -> None:
    client, calls, sleeps = make(
        lambda r, n: err(429, "Too many collector runs this hour.", {"retry_after": 900})
    )
    with pytest.raises(RateLimitError) as info:
        client.start_run({"query": "q", "location": "l"})
    assert info.value.retry_after == 900
    assert len(calls) == 1
    assert sleeps == []


def test_post_is_not_retried_on_5xx_but_get_is() -> None:
    client, calls, _ = make(lambda r, n: err(500, "boom"))
    with pytest.raises(QuanticDataError):
        client.start_run({"query": "q", "location": "l"})
    assert len(calls) == 1

    client, calls, _ = make(
        lambda r, n: err(502, "bad gateway") if n == 1 else ok({"run_id": "r", "status": "done"})
    )
    assert client.get_run("r")["status"] == "done"
    assert len(calls) == 2


def test_connection_errors() -> None:
    def boom(r: httpx.Request, n: int) -> httpx.Response:
        raise httpx.ConnectError("refused", request=r)

    client, calls, _ = make(boom)
    with pytest.raises(QuanticDataError, match="Cannot reach"):
        client.start_run({"query": "q", "location": "l"})
    assert len(calls) == 1  # POST: not retried
    client, calls, _ = make(boom)
    with pytest.raises(QuanticDataError):
        client.get_run("r")
    assert len(calls) == 3  # GET: 1 + 2 retries


def test_csv_and_collector_schema() -> None:
    def handler(r: httpx.Request, n: int) -> httpx.Response:
        if r.url.path.endswith("/runs/r1"):
            assert r.url.params["format"] == "csv"
            return httpx.Response(200, text="name\nA\n", headers={"content-type": "text/csv"})
        return ok(
            {"collector": {"slug": "google_maps_places", "input_schema": {"required": ["query", "location"]}}}
        )

    client, _, _ = make(handler)
    assert client.get_run_csv("r1") == "name\nA\n"
    assert client.get_collector()["input_schema"]["required"] == ["query", "location"]


def test_engine_maps_rows_and_passes_documented_fields() -> None:
    client, calls, _ = make(lambda r, n: ok({"run_id": "r1", "status": "done", "count": 1, "results": [ROW]}))
    engine = QuanticDataEngine(client)
    places = list(engine.search("cafe", "Springfield", max_results=5, country="us", extra={"language": "en"}))
    assert json.loads(calls[0].content)["input"] == {
        "query": "cafe",
        "location": "Springfield",
        "country": "us",
        "max_results": 5,
        "language": "en",
    }
    p = places[0]
    assert (p.name, p.rating, p.reviews, p.place_id, p.engine) == (
        "Example Place",
        4.5,
        120,
        "ChIJx",
        "quanticdata",
    )
    assert (p.query, p.location, p.found_by) == ("cafe", "Springfield", "cafe Springfield")


def test_engine_raises_on_failed_run() -> None:
    client, _, _ = make(
        lambda r, n: ok({"run_id": "r1", "status": "failed", "error": "upstream timeout", "results": []})
    )
    with pytest.raises(CollectorRunError, match="upstream timeout"):
        list(QuanticDataEngine(client).search("q", "l"))


def test_place_from_row_tolerates_missing_and_bad_types() -> None:
    p = place_from_row(
        {"name": "X", "rating": "4.5", "reviews": True, "website": ""}, query=None, location=None
    )
    assert (p.rating, p.reviews, p.website) == (None, None, None)
