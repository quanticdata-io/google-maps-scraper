"""Parsing of Google Maps pages for the local engine.

Everything that depends on Google's markup lives here, isolated from the
browser automation, so it can be unit-tested against saved HTML and fixed in
one place when the markup changes. Selectors prefer stable hooks (``data-item-id``,
``aria-label``, ``role``) over generated class names.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from .models import Place

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

_COORDS_DATA = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
_COORDS_AT = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_DATA_ID = re.compile(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")
_PLACE_ID = re.compile(r"!19s(ChIJ[\w-]+)")
_RATING = re.compile(r"(\d(?:[.,]\d)?)\s*stars?", re.IGNORECASE)
_REVIEWS = re.compile(r"([\d][\d.,\s\u00a0]*)\s*reviews?", re.IGNORECASE)
_PAREN_COUNT = re.compile(r"\(\s*([\d][\d.,\s\u00a0]*)\s*\)")
END_OF_LIST_MARKERS = ("You've reached the end of the list", "You\u2019ve reached the end of the list")


def _soup(html: str) -> BeautifulSoup:
    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415 - optional [browser] extra
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "The local engine needs the browser extra: pip install 'gmaps-places-scraper[browser]'"
        ) from exc
    return BeautifulSoup(html, "html.parser")


def parse_count(text: str | None) -> int | None:
    """``"3,120"``, ``"3.120"``, ``"3 120"`` -> 3120."""
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def parse_rating(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"\d(?:[.,]\d)?", text)
    if not m:
        return None
    value = float(m.group(0).replace(",", "."))
    return value if 0 <= value <= 5 else None


def parse_maps_url(url: str) -> dict[str, Any]:
    """Coordinates and ids encoded in a Google Maps place URL."""
    out: dict[str, Any] = {"latitude": None, "longitude": None, "data_id": None, "place_id": None}
    decoded = unquote(url)
    m = _COORDS_DATA.search(decoded) or _COORDS_AT.search(decoded)
    if m:
        out["latitude"], out["longitude"] = float(m.group(1)), float(m.group(2))
    if m := _DATA_ID.search(decoded):
        out["data_id"] = m.group(1)
    if m := _PLACE_ID.search(decoded):
        out["place_id"] = m.group(1)
    return out


def _attr(tag: Tag | None, name: str) -> str | None:
    if tag is None:
        return None
    value = tag.get(name)
    if isinstance(value, list):
        value = " ".join(value)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _text(tag: Tag | None) -> str | None:
    if tag is None:
        return None
    text = tag.get_text(" ", strip=True)
    return text or None


def _strip_label(value: str | None, *prefixes: str) -> str | None:
    if not value:
        return None
    for p in prefixes:
        if value.lower().startswith(p.lower()):
            value = value[len(p) :]
    value = value.strip(" :\u00a0")
    return value or None


def unwrap_google_redirect(href: str | None) -> str | None:
    """``/url?q=https://site.example/&...`` -> ``https://site.example/``."""
    if not href:
        return None
    parsed = urlparse(href)
    if parsed.path == "/url":
        q = parse_qs(parsed.query).get("q") or parse_qs(parsed.query).get("url")
        if q:
            return q[0]
    return href


def parse_place_html(html: str, url: str, *, rank: int | None = None) -> Place | None:
    """Reads one place panel. Returns ``None`` when the page has no place name."""
    soup = _soup(html)
    root: Any = soup.select_one('div[role="main"]') or soup

    name = None
    for h1 in root.select("h1"):
        name = _text(h1)
        if name:
            break
    if not name:
        return None

    category = _text(root.select_one('button[jsaction*="category"]')) or _text(root.select_one(".DkEaL"))

    address_el = root.select_one('[data-item-id="address"]')
    address = _strip_label(_attr(address_el, "aria-label"), "Address") or _text(address_el)

    phone = None
    phone_el = root.select_one('[data-item-id^="phone:tel:"]')
    if phone_el is not None:
        phone = _strip_label(_attr(phone_el, "aria-label"), "Phone") or _text(phone_el)
        if not phone:
            phone = (_attr(phone_el, "data-item-id") or "").removeprefix("phone:tel:") or None

    website = unwrap_google_redirect(_attr(root.select_one('a[data-item-id="authority"]'), "href"))

    rating: float | None = None
    reviews: int | None = None
    for el in root.select("[aria-label]"):
        label = _attr(el, "aria-label") or ""
        if rating is None and (m := _RATING.search(label)):
            rating = parse_rating(m.group(1))
        if reviews is None and (m := _REVIEWS.search(label)):
            reviews = parse_count(m.group(1))
    if rating is None:
        rating = parse_rating(_text(root.select_one('.F7nice span[aria-hidden="true"]')))
    if reviews is None:
        container = root.select_one(".F7nice")
        if container is not None and (m := _PAREN_COUNT.search(container.get_text(" ", strip=True))):
            reviews = parse_count(m.group(1))

    ids = parse_maps_url(url)
    return Place(
        name=name,
        rank=rank,
        category=category,
        address=address,
        phone=phone,
        website=website,
        rating=rating,
        reviews=reviews,
        latitude=ids["latitude"],
        longitude=ids["longitude"],
        place_id=ids["place_id"],
        data_id=ids["data_id"],
        maps_url=url.split("?", maxsplit=1)[0] if "/maps/place/" in url else url,
        engine="local",
    )


def parse_feed_links(html: str, base_url: str) -> list[str]:
    """Place links of a results feed, in display order and without duplicates."""
    soup = _soup(html)
    feed: Any = soup.select_one('div[role="feed"]') or soup
    seen: set[str] = set()
    links: list[str] = []
    for a in feed.select('a[href*="/maps/place/"]'):
        href = _attr(a, "href")
        if not href:
            continue
        absolute = urljoin(base_url, href)
        key = absolute.split("?")[0]
        if key not in seen:
            seen.add(key)
            links.append(absolute)
    return links


def is_end_of_list(text: str) -> bool:
    return any(marker in text for marker in END_OF_LIST_MARKERS)
