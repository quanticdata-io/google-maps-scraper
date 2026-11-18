"""End-to-end test of the local engine against a synthetic, local Maps-like site.

It drives a real headless Chromium through consent, an infinite-scroll results
feed and place pages. It never touches Google. Skipped when Playwright or its
Chromium build is not installed (`playwright install chromium`).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import unquote

import pytest

from gmaps_places.engines import LocalEngine, LocalOptions
from gmaps_places.engines.local import playwright_proxy, search_url
from gmaps_places.grid import BBox

TOTAL = 12

FEED_PAGE = """<!doctype html><html lang="en"><body>
<div role="main"><div role="feed" id="feed" style="height:300px;overflow-y:scroll"></div>
<p id="end"></p></div>
<script>
  const total = __TOTAL__; let shown = 0;
  const feed = document.getElementById('feed');
  function more() {
    for (let i = 0; i < 5 && shown < total; i++) {
      shown++;
      const d = document.createElement('div'); d.style.height = '120px';
      const id = shown.toString(16).padStart(2, '0');
      d.innerHTML = '<a href="/maps/place/Place+' + shown + '/data=!4m7!3m6!1s0x10000000000000' + id +
        ':0x20000000000000' + id + '!8m2!3d4' + shown + '.5!4d-7' + shown + '.25!19sChIJlocal' + shown + '?hl=en">Place ' + shown + '</a>';
      feed.appendChild(d);
    }
    if (shown >= total) document.getElementById('end').textContent = "You've reached the end of the list.";
  }
  more();
  feed.addEventListener('scroll', () => { if (feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 5) setTimeout(more, 50); });
</script></body></html>""".replace("__TOTAL__", str(TOTAL))

CONSENT_PAGE = """<!doctype html><html><body>
<form action="https://consent.local/save" onsubmit="event.preventDefault(); document.cookie='consent=1; path=/'; location.reload();">
<button aria-label="Reject all">Reject all</button></form></body></html>"""


def place_page(n: str) -> str:
    return f"""<!doctype html><html lang="en"><body><div role="main">
<h1>Place {n}</h1>
<div class="F7nice"><span aria-hidden="true">4.{n[-1]}</span><span aria-label="{n}0 reviews">({n}0)</span></div>
<button jsaction="pane.category">Cafe</button>
<button data-item-id="address" aria-label="Address: {n} Local Road, Testville"></button>
<button data-item-id="phone:tel:555010{n}" aria-label="Phone: 555-010-{n}"></button>
<a data-item-id="authority" href="https://place{n}.example/">place{n}.example</a>
</div></body></html>"""


class MapsHandler(BaseHTTPRequestHandler):
    searches: ClassVar[list[str]] = []

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _html(self, body: str) -> None:
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = unquote(self.path.split("?")[0])
        if path.startswith("/maps/search/"):
            if "consent=1" not in (self.headers.get("Cookie") or ""):
                self._html(CONSENT_PAGE)
                return
            self.searches.append(path)
            self._html(FEED_PAGE)
        elif path.startswith("/maps/place/"):
            n = path.split("/")[3].replace("Place+", "").replace("Place ", "")
            self._html(place_page(n))
        else:
            self.send_error(404)


@pytest.fixture(scope="module")
def maps_site() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), MapsHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/maps"
    server.shutdown()


@pytest.fixture(scope="module")
def chromium_ok() -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        with sync_api.sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception as exc:
        pytest.skip(f"Chromium for Playwright is not available: {exc}")


def options(maps_url: str) -> LocalOptions:
    return LocalOptions(
        maps_url=maps_url, delay=0, scroll_pause=0.3, max_idle_scrolls=3, nav_timeout_ms=10_000
    )


@pytest.mark.browser
@pytest.mark.usefixtures("chromium_ok")
def test_local_engine_scrolls_feed_and_reads_places(maps_site: str) -> None:
    engine = LocalEngine(options(maps_site))
    places = list(engine.search("cafe", "Testville", max_results=8))
    assert [p.name for p in places] == [f"Place {i}" for i in range(1, 9)]
    first = places[0]
    assert (first.rank, first.category, first.rating, first.reviews) == (1, "Cafe", 4.1, 10)
    assert first.address == "1 Local Road, Testville"
    assert first.phone == "555-010-1"
    assert first.website == "https://place1.example/"
    assert (first.latitude, first.longitude) == (41.5, -71.25)
    assert first.place_id == "ChIJlocal1"
    assert (first.query, first.location, first.engine) == ("cafe", "Testville", "local")


@pytest.mark.browser
@pytest.mark.usefixtures("chromium_ok")
def test_local_engine_stops_at_end_of_list(maps_site: str) -> None:
    places = list(LocalEngine(options(maps_site)).search("cafe", "Testville", max_results=50))
    assert len(places) == TOTAL


@pytest.mark.browser
@pytest.mark.usefixtures("chromium_ok")
def test_grid_searches_every_cell_and_dedups(maps_site: str) -> None:
    MapsHandler.searches.clear()
    box = BBox(40.0, -74.0, 40.02, -73.95)  # about 2.2 km x 4.3 km -> 2 x 3 cells at 2 km
    places = list(
        LocalEngine(options(maps_site)).search("cafe", "", max_results=TOTAL + 5, bbox=box, cell_km=2)
    )
    assert len(MapsHandler.searches) == 6
    assert all("@40.0" in s for s in MapsHandler.searches)
    assert len(places) == TOTAL  # the same places in every cell are kept once


def test_search_url_and_proxy_settings() -> None:
    assert search_url("https://www.google.com/maps", "pizza", "Brooklyn, NY") == (
        "https://www.google.com/maps/search/pizza%20Brooklyn%2C%20NY/?hl=en"
    )
    assert search_url("https://m.test/maps/", "pizza", "", center=(1.5, 2.5), zoom=15).endswith(
        "/search/pizza/@1.5,2.5,15z?hl=en"
    )
    assert playwright_proxy("http://us%40er:p%3Ass@gw.example:8080") == {
        "server": "http://gw.example:8080",
        "username": "us@er",
        "password": "p:ss",
    }
    assert playwright_proxy("gw.example:3128") == {"server": "http://gw.example:3128"}
    assert playwright_proxy(None) is None
    with pytest.raises(ValueError, match="Proxy"):
        playwright_proxy("http://no-port.example")


@pytest.mark.browser
@pytest.mark.usefixtures("chromium_ok")
def test_cli_local_engine(maps_site: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from gmaps_places.cli import main

    monkeypatch.delenv("QUANTICDATA_API_KEY", raising=False)
    out = tmp_path / "local.jsonl"
    args = [
        "search",
        "cafe",
        "-l",
        "Testville",
        "-n",
        "3",
        "--delay",
        "0",
        "--maps-url",
        maps_site,
        "-o",
        str(out),
    ]
    assert main(args) == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["name"] for r in rows] == ["Place 1", "Place 2", "Place 3"]
    assert {r["engine"] for r in rows} == {"local"}
