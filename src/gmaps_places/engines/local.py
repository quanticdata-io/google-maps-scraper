"""Local engine: drives headless Chromium with Playwright, no API key needed.

It depends on Google's page markup, which changes without notice: when it
breaks, the fix belongs in :mod:`gmaps_places.parsing` (selectors) or here
(navigation). Install with ``pip install 'gmaps-places-scraper[browser]'`` and
``playwright install chromium``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote, urlparse

from ..grid import BBox, cell_centers, zoom_for_cell
from ..models import Place
from ..parsing import is_end_of_list, parse_feed_links, parse_place_html

if TYPE_CHECKING:
    from playwright.sync_api import ProxySettings

DEFAULT_MAPS_URL = "https://www.google.com/maps"
CONSENT_BUTTONS = (
    'button[aria-label="Reject all"]',
    'button:has-text("Reject all")',
    'button[aria-label="Accept all"]',
    'button:has-text("Accept all")',
    'form[action*="consent"] button',
)


def playwright_proxy(proxy_url: str | None) -> ProxySettings | None:
    """``http://user:pass@host:port`` -> Playwright's ``{"server", "username", "password"}``."""
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url if "://" in proxy_url else f"http://{proxy_url}")
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"Proxy must look like scheme://user:pass@host:port, got {proxy_url!r}")
    out: ProxySettings = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        out["username"] = unquote(parsed.username)
    if parsed.password:
        out["password"] = unquote(parsed.password)
    return out


def search_url(
    maps_url: str,
    query: str,
    location: str,
    *,
    center: tuple[float, float] | None = None,
    zoom: int | None = None,
    lang: str = "en",
) -> str:
    terms = " ".join(t for t in (query, location) if t).strip()
    url = f"{maps_url.rstrip('/')}/search/{quote(terms, safe='')}/"
    if center is not None:
        url += f"@{center[0]},{center[1]},{zoom or 14}z"
    return f"{url}?hl={lang}"


@dataclass
class LocalOptions:
    headless: bool = True
    proxy: str | None = None
    delay: float = 1.0
    scroll_pause: float = 1.2
    max_idle_scrolls: int = 4
    nav_timeout_ms: int = 30_000
    lang: str = "en"
    maps_url: str = DEFAULT_MAPS_URL


class LocalEngine:
    name = "local"

    def __init__(
        self, options: LocalOptions | None = None, *, log: Callable[[str], None] | None = None
    ) -> None:
        self.options = options or LocalOptions()
        self.log = log or (lambda _msg: None)

    # -- browser helpers ---------------------------------------------------

    def _accept_consent(self, page: Any) -> None:
        if "consent." not in page.url and not page.locator('form[action*="consent"]').count():
            return
        for selector in CONSENT_BUTTONS:
            button = page.locator(selector).first
            if button.count():
                button.click()
                page.wait_for_load_state("domcontentloaded")
                self.log("consent screen answered")
                return

    def _collect_links(self, page: Any, max_results: int) -> list[str]:
        o = self.options
        links: list[str] = []
        idle = 0
        while len(links) < max_results and idle < o.max_idle_scrolls:
            found = parse_feed_links(page.content(), page.url)
            if len(found) > len(links):
                links, idle = found, 0
            else:
                idle += 1
            if is_end_of_list(page.inner_text("body")):
                break
            page.evaluate(
                "() => { const f = document.querySelector('div[role=\"feed\"]');"
                " if (f) f.scrollTop = f.scrollHeight; else window.scrollTo(0, document.body.scrollHeight); }"
            )
            page.wait_for_timeout(int(o.scroll_pause * 1000))
        return links[:max_results]

    def _read_place(self, page: Any, url: str, rank: int) -> Place | None:
        page.goto(url, wait_until="domcontentloaded", timeout=self.options.nav_timeout_ms)
        self._accept_consent(page)
        try:
            page.wait_for_selector("h1", timeout=self.options.nav_timeout_ms)
        except Exception:
            return None
        return parse_place_html(page.content(), page.url, rank=rank)

    # -- public API ----------------------------------------------------------

    def search(
        self,
        query: str,
        location: str,
        *,
        max_results: int = 20,
        bbox: BBox | None = None,
        cell_km: float = 2.0,
        zoom: int | None = None,
    ) -> Iterator[Place]:
        """Yields places for ``query`` near ``location``; with ``bbox``, one search per grid cell."""
        try:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415 - optional [browser] extra
        except ImportError as exc:  # pragma: no cover - depends on the optional extra
            raise RuntimeError(
                "The local engine needs: pip install 'gmaps-places-scraper[browser]'"
                " && playwright install chromium"
            ) from exc

        o = self.options
        targets: list[tuple[float, float] | None] = [None]
        if bbox is not None:
            targets = list(cell_centers(bbox, cell_km))
            self.log(f"grid: {len(targets)} cells of about {cell_km} km")

        seen: set[str] = set()
        rank = 0
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=o.headless, proxy=playwright_proxy(o.proxy))
            context = browser.new_context(
                locale=f"{o.lang}-US" if o.lang == "en" else o.lang, viewport={"width": 1280, "height": 900}
            )
            try:
                feed_page = context.new_page()
                place_page = context.new_page()
                for center in targets:
                    if rank >= max_results:
                        break
                    z = zoom or (zoom_for_cell(cell_km, center[0]) if center else None)
                    url = search_url(
                        o.maps_url,
                        query,
                        location if center is None else "",
                        center=center,
                        zoom=z,
                        lang=o.lang,
                    )
                    self.log(f"search {url}")
                    feed_page.goto(url, wait_until="domcontentloaded", timeout=o.nav_timeout_ms)
                    self._accept_consent(feed_page)

                    if "/maps/place/" in feed_page.url:  # a single, exact match opens the place directly
                        links = [feed_page.url]
                    else:
                        try:
                            feed_page.wait_for_selector('div[role="feed"]', timeout=o.nav_timeout_ms)
                        except Exception:
                            self.log("no results feed on this search")
                            continue
                        links = self._collect_links(feed_page, max_results - rank + len(seen))

                    for link in links:
                        key = link.split("?")[0]
                        if key in seen or rank >= max_results:
                            continue
                        seen.add(key)
                        place = self._read_place(place_page, link, rank + 1)
                        if place is None:
                            continue
                        rank += 1
                        place.query, place.location = query, location
                        place.found_by = (
                            f"{query} {location}".strip()
                            if center is None
                            else f"{query} @{center[0]},{center[1]}"
                        )
                        yield place
                        time.sleep(o.delay)
            finally:
                context.close()
                browser.close()
