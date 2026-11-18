"""Local stand-in for the three QuanticData collector endpoints this tool calls.

Run it to try the CLI without a key or network:

    python tests/mock_api.py            # http://127.0.0.1:4011/v1
    QUANTICDATA_API_KEY=qd_test_123 QUANTICDATA_API_BASE=http://127.0.0.1:4011/v1 \
        gmaps-places search "pizza restaurants" -l "Brooklyn, NY" -n 3

Responses follow the documented envelope and shapes. The places are fictional.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

COLLECTOR: dict[str, Any] = {
    "slug": "google_maps_places",
    "name": "Google Maps places",
    "version": "1.1.0",
    "category": "local",
    "unit": "place",
    "max_results": 300,
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search, e.g. pizza restaurants"},
            "location": {"type": "string", "description": "Where, e.g. Brooklyn, NY"},
            "country": {"type": "string", "description": "Two-letter country code"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 300},
        },
        "required": ["query", "location"],
        "additionalProperties": False,
    },
    "output_schema": {"fields": []},
    "run_url": "/api/v1/scraper/collectors/google_maps_places/run",
}


def fake_rows(query: str, location: str, n: int) -> list[dict[str, Any]]:
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "rank": i,
                "name": f"Example Place {i}",
                "rating": round(4.0 + (i % 10) / 10, 1),
                "reviews": 100 * i,
                "category": "Pizza restaurant",
                "address": f"{i} Example Street, Springfield",
                "phone": f"+1 555-010-{i:04d}",
                "website": f"place{i}.example",
                "latitude": round(40.7 + i / 1000, 6),
                "longitude": round(-73.9 - i / 1000, 6),
                "place_id": f"ChIJexample{i:04d}",
                "data_id": f"0x89c25900000000{i:02x}:0x00000000000000{i:02x}",
                "found_by": f"{query} {location}".strip(),
            }
        )
    return rows


class MockState:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str, Any]] = []
        self.counter = 0


class Handler(BaseHTTPRequestHandler):
    state: MockState

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send(self, status: int, body: Any, ctype: str = "application/json") -> None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if re.fullmatch(r"Bearer qd_(live|test)_[A-Za-z0-9]+", auth):
            return True
        self._send(401, {"type": "error", "message": "Invalid or missing API key"})
        return False

    def _route(self, method: str) -> None:
        path, _, query = self.path.partition("?")
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"null") if length else None
        self.state.requests.append((method, self.path, body))
        if not self._authorized():
            return
        if method == "GET" and path == "/v1/scraper/collectors/google_maps_places":
            self._send(200, {"type": "response", "message": "Collector", "payload": {"collector": COLLECTOR}})
            return
        if method == "POST" and path == "/v1/scraper/collectors/google_maps_places/run":
            inp = (body or {}).get("input", body or {})
            if not inp.get("query") or not inp.get("location"):
                self._send(
                    422,
                    {
                        "type": "error",
                        "message": "Invalid input: query and location are required",
                        "payload": {"error_kind": "input"},
                    },
                )
                return
            n = int(inp.get("max_results") or 20)
            self.state.counter += 1
            run_id = f"run_{self.state.counter:04d}"
            run = {
                "run_id": run_id,
                "slug": "google_maps_places",
                "version": "1.1.0",
                "status": "done",
                "input": inp,
                "count": n,
                "partial": False,
                "error": None,
                "results": fake_rows(inp["query"], inp["location"], n),
                "notes": [],
            }
            self.state.runs[run_id] = run
            if (body or {}).get("async"):
                self._send(
                    202,
                    {
                        "type": "response",
                        "message": "Collector run queued",
                        "payload": {
                            "run_id": run_id,
                            "status": "queued",
                            "statusUrl": f"/api/v1/scraper/collectors/runs/{run_id}",
                        },
                    },
                )
            else:
                self._send(200, {"type": "response", "message": "Collector run complete", "payload": run})
            return
        m = re.fullmatch(r"/v1/scraper/collectors/runs/([\w-]+)", path)
        if method == "GET" and m:
            found = self.state.runs.get(m.group(1))
            if found is None:
                self._send(404, {"type": "error", "message": "Run not found"})
            elif "format=csv" in query:
                out = io.StringIO()
                w = csv.DictWriter(
                    out, fieldnames=list(found["results"][0].keys()) if found["results"] else ["name"]
                )
                w.writeheader()
                w.writerows(found["results"])
                self._send(200, out.getvalue(), "text/csv")
            else:
                self._send(200, {"type": "response", "message": "Collector run", "payload": found})
            return
        self._send(404, {"type": "error", "message": f"No route for {method} {path}"})

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")


def start(port: int = 0) -> tuple[ThreadingHTTPServer, MockState, str]:
    state = MockState()
    handler = type("BoundHandler", (Handler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state, f"http://127.0.0.1:{server.server_address[1]}/v1"


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4011
    srv, _state, url = start(port)
    print(f"QuanticData mock API listening on {url}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
