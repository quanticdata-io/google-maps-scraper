from __future__ import annotations

import httpx

from gmaps_places.enrich import EmailEnricher, contact_links, find_emails, normalize_website

HOME = """
<html><body>
  <a href="mailto:Info@Shop.example?subject=Hi">Write to us</a>
  <a href="/contact-us">Contact</a> <a href="https://shop.example/about">About</a>
  <a href="https://other.example/contact">Partner</a> <a href="tel:+15550100000">Call</a>
  <img src="logo@2x.png"> <p>noreply@example.com</p>
</body></html>
"""
CONTACT = "<p>Sales: sales&#64;shop.example, also info@shop.example.</p>"


def test_find_emails_filters_junk_and_dedups() -> None:
    assert find_emails(HOME) == ["info@shop.example"]
    assert find_emails(CONTACT) == ["sales@shop.example", "info@shop.example"]


def test_contact_links_same_site_only() -> None:
    assert contact_links(HOME, "https://www.shop.example/") == [
        "https://www.shop.example/contact-us",
        "https://shop.example/about",
    ]


def test_normalize_website() -> None:
    assert normalize_website("shop.example") == "https://shop.example"
    assert normalize_website("http://shop.example/x") == "http://shop.example/x"


def test_enricher_reads_home_and_contact_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pages = {"/": HOME, "/contact-us": CONTACT}
        body = pages.get(request.url.path)
        if body is None:
            return httpx.Response(404, text="missing")
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    enricher = EmailEnricher(transport=httpx.MockTransport(handler))
    try:
        assert enricher.emails_for("shop.example") == ["info@shop.example", "sales@shop.example"]
    finally:
        enricher.close()


def test_enricher_survives_unreachable_sites() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    enricher = EmailEnricher(transport=httpx.MockTransport(handler))
    assert enricher.emails_for("down.example") == []
    enricher.close()
