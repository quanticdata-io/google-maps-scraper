"""Optional email enrichment: reads a place's own website (homepage and a few contact pages).

Only the business's public website is fetched, never Google. Turned on with
``--emails``; off by default.
"""

from __future__ import annotations

import html as html_lib
import re
from urllib.parse import unquote, urljoin, urlparse

import httpx

from ._version import __version__

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
_HREF = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.IGNORECASE)
_CONTACT_HINTS = ("contact", "kontakt", "contatti", "contacto", "impressum", "about", "chi-siamo", "legal")
_JUNK_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
_JUNK_DOMAINS = ("example.com", "example.org", "domain.com", "email.com", "sentry.io", "wixpress.com")


def normalize_website(website: str) -> str:
    """``joespizza.example`` -> ``https://joespizza.example``."""
    website = website.strip()
    if not re.match(r"^https?://", website, re.IGNORECASE):
        website = "https://" + website.lstrip("/")
    return website


def find_emails(html: str) -> list[str]:
    """Emails from ``mailto:`` links and visible text, lower-cased, without obvious junk."""
    text = html_lib.unescape(unquote(html))
    found: list[str] = []
    for raw in _EMAIL.findall(text):
        email = raw.strip(".").lower()
        domain = email.rsplit("@", 1)[-1]
        if email.endswith(_JUNK_SUFFIXES) or any(domain.endswith(d) for d in _JUNK_DOMAINS):
            continue
        if email not in found:
            found.append(email)
    return found


def contact_links(html: str, base_url: str, limit: int = 3) -> list[str]:
    """Same-site links that look like contact or legal pages."""
    host = urlparse(base_url).netloc.lower().removeprefix("www.")
    links: list[str] = []
    for href in _HREF.findall(html):
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower().removeprefix("www.") != host:
            continue
        if any(h in parsed.path.lower() for h in _CONTACT_HINTS) and url not in links:
            links.append(url)
        if len(links) >= limit:
            break
    return links


class EmailEnricher:
    """Fetches a website's homepage and up to ``max_pages`` contact pages, and collects emails."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        max_pages: int = 3,
        proxy: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.max_pages = max_pages
        self._http = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            proxy=proxy,
            transport=transport,
            headers={"User-Agent": f"Mozilla/5.0 (compatible; gmaps-places-scraper/{__version__})"},
        )

    def close(self) -> None:
        self._http.close()

    def _get(self, url: str) -> str | None:
        try:
            r = self._http.get(url)
        except httpx.HTTPError:
            return None
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
            return None
        return r.text

    def emails_for(self, website: str) -> list[str]:
        home_url = normalize_website(website)
        home = self._get(home_url)
        if home is None:
            return []
        emails = find_emails(home)
        for link in contact_links(home, home_url, self.max_pages):
            page = self._get(link)
            if page:
                emails.extend(e for e in find_emails(page) if e not in emails)
        return emails
