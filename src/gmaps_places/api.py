"""Minimal client for the QuanticData collector endpoints used by this tool.

Only documented endpoints are called (see https://quanticdata.io/docs/):

- ``GET  /scraper/collectors/{slug}``           collector details and its live ``input_schema``
- ``POST /scraper/collectors/{slug}/run``       run it (200 with rows, or 202 queued)
- ``GET  /scraper/collectors/runs/{runId}``     poll a run, ``?format=csv`` for CSV

Every answer uses the envelope ``{"type": "response"|"error", "message": ..., "payload": ...}``.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from ._version import __version__

DEFAULT_BASE_URL = "https://api.quanticdata.io/v1"
ENV_API_KEY = "QUANTICDATA_API_KEY"
ENV_API_BASE = "QUANTICDATA_API_BASE"
MAPS_COLLECTOR = "google_maps_places"
TERMINAL_STATUSES = frozenset({"done", "failed"})


class QuanticDataError(Exception):
    """The API answered with the error envelope, or could not be reached."""

    def __init__(self, message: str, *, status: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.payload = payload

    @property
    def code(self) -> str | None:
        if isinstance(self.payload, Mapping):
            code = self.payload.get("code")
            return code if isinstance(code, str) else None
        return None


class AuthenticationError(QuanticDataError):
    """HTTP 401: missing, unknown, disabled or expired API key."""


class PaymentRequiredError(QuanticDataError):
    """HTTP 402: the free tier and the balance cannot cover the run's worst case."""


class InputError(QuanticDataError):
    """HTTP 422: the input cannot succeed as sent; fix it instead of retrying."""


class RateLimitError(QuanticDataError):
    """HTTP 429: too many requests or runs. ``retry_after`` is in seconds when known."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        payload: Any = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, status=status, payload=payload)
        self.retry_after = retry_after


class RunTimeoutError(QuanticDataError):
    """A background run did not finish in time. It keeps running on the server."""

    def __init__(self, run_id: str, last_status: str | None, timeout: float) -> None:
        super().__init__(
            f"Run {run_id} did not finish within {timeout:.0f}s (last status: {last_status}). "
            f"It keeps running: check it later with `gmaps-places status {run_id}`."
        )
        self.run_id = run_id
        self.last_status = last_status


def _retry_after(response: httpx.Response, payload: Any) -> float | None:
    header = response.headers.get("retry-after")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    if isinstance(payload, Mapping) and isinstance(payload.get("retry_after"), (int, float)):
        return float(payload["retry_after"])
    return None


class QuanticDataClient:
    """Talks to the collector endpoints with retries on 429 and connection errors.

    A ``POST`` that reached the server is never sent again after a 5xx, so a
    billed run is never started twice by this client.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        max_retry_wait: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = api_key or os.environ.get(ENV_API_KEY, "").strip()
        if not key:
            raise AuthenticationError(
                f"No API key: pass api_key or set {ENV_API_KEY}. Create one on the API keys page "
                "of the QuanticData dashboard, or use the local engine (--engine local)."
            )
        self.base_url = (base_url or os.environ.get(ENV_API_BASE) or DEFAULT_BASE_URL).rstrip("/")
        self.max_retries = max_retries
        self.max_retry_wait = max_retry_wait
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": f"gmaps-places-scraper/{__version__}",
                "Accept": "application/json, text/csv;q=0.9",
            },
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> QuanticDataClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport ---------------------------------------------------------

    def _request(
        self, method: str, path: str, *, json: Any = None, params: Mapping[str, str] | None = None
    ) -> Any:
        idempotent = method == "GET"
        attempt = 0
        while True:
            try:
                response = self._http.request(method, path, json=json, params=params)
            except httpx.TransportError as exc:
                if idempotent and attempt < self.max_retries:
                    attempt += 1
                    self._sleep(min(2.0**attempt, 8.0))
                    continue
                raise QuanticDataError(f"Cannot reach the QuanticData API at {self.base_url}: {exc}") from exc

            ctype = response.headers.get("content-type", "")
            if "json" not in ctype:
                if response.is_success:
                    return response.text
                raise QuanticDataError(
                    response.text[:500] or f"HTTP {response.status_code}", status=response.status_code
                )
            try:
                doc = response.json()
            except ValueError as exc:
                raise QuanticDataError(
                    f"Invalid JSON (HTTP {response.status_code})", status=response.status_code
                ) from exc

            is_error = not response.is_success or (isinstance(doc, Mapping) and doc.get("type") == "error")
            if not is_error:
                return doc.get("payload", doc) if isinstance(doc, Mapping) else doc

            message = (
                str(doc.get("message") or f"HTTP {response.status_code}")
                if isinstance(doc, Mapping)
                else f"HTTP {response.status_code}"
            )
            payload = doc.get("payload") if isinstance(doc, Mapping) else None
            status = response.status_code
            if status == 429:
                wait = _retry_after(response, payload)
                if attempt < self.max_retries and (wait is None or wait <= self.max_retry_wait):
                    attempt += 1
                    self._sleep(wait if wait is not None else min(2.0**attempt, 8.0))
                    continue
                raise RateLimitError(message, status=status, payload=payload, retry_after=wait)
            if idempotent and status in (500, 502, 504) and attempt < self.max_retries:
                attempt += 1
                self._sleep(min(2.0**attempt, 8.0))
                continue
            error_cls = {401: AuthenticationError, 402: PaymentRequiredError, 422: InputError}.get(
                status, QuanticDataError
            )
            raise error_cls(message, status=status, payload=payload)

    # -- endpoints ---------------------------------------------------------

    def get_collector(self, slug: str = MAPS_COLLECTOR) -> dict[str, Any]:
        """Collector details, including the live ``input_schema`` and ``output_schema``."""
        payload = self._request("GET", f"/scraper/collectors/{slug}")
        collector = payload.get("collector", payload) if isinstance(payload, Mapping) else payload
        return dict(collector)

    def start_run(
        self, input: Mapping[str, Any], *, slug: str = MAPS_COLLECTOR, background: bool = False
    ) -> dict[str, Any]:
        """``POST /scraper/collectors/{slug}/run``. Short runs answer with rows; long ones are queued."""
        body: dict[str, Any] = {"input": dict(input)}
        if background:
            body["async"] = True
        return dict(self._request("POST", f"/scraper/collectors/{slug}/run", json=body))

    def get_run(self, run_id: str) -> dict[str, Any]:
        return dict(self._request("GET", f"/scraper/collectors/runs/{run_id}"))

    def get_run_csv(self, run_id: str) -> str:
        return str(self._request("GET", f"/scraper/collectors/runs/{run_id}", params={"format": "csv"}))

    def wait_for_run(
        self,
        run_id: str,
        *,
        poll_interval: float = 3.0,
        timeout: float = 900.0,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            run = self.get_run(run_id)
            if on_progress:
                on_progress(run)
            status = run.get("status")
            if status in TERMINAL_STATUSES:
                return run
            if time.monotonic() + poll_interval > deadline:
                raise RunTimeoutError(run_id, str(status), timeout)
            self._sleep(poll_interval)

    def run(
        self,
        input: Mapping[str, Any],
        *,
        slug: str = MAPS_COLLECTOR,
        background: bool = False,
        poll_interval: float = 3.0,
        timeout: float = 900.0,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Starts a run and, when it was queued, polls it until it is ``done`` or ``failed``."""
        started = self.start_run(input, slug=slug, background=background)
        if started.get("status") in TERMINAL_STATUSES and "results" in started:
            return started
        run_id = started.get("run_id")
        if not isinstance(run_id, str):
            raise QuanticDataError("The API answered without a run_id", payload=started)
        return self.wait_for_run(
            run_id, poll_interval=poll_interval, timeout=timeout, on_progress=on_progress
        )
