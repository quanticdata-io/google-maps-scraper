from __future__ import annotations

from pathlib import Path

import pytest

from gmaps_places.parsing import (
    is_end_of_list,
    parse_count,
    parse_feed_links,
    parse_maps_url,
    parse_place_html,
    parse_rating,
    unwrap_google_redirect,
)

FIXTURES = Path(__file__).parent / "fixtures"
PLACE_URL = (
    "https://www.google.com/maps/place/Example+Pizza+Co/data=!4m7!3m6"
    "!1s0x880b5e0000000001:0x1a2b3c4d5e6f7a8b!8m2!3d39.7817!4d-89.6501!16s%2Fg%2F11example!19sChIJexample0001?hl=en"
)


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_full_place_panel() -> None:
    place = parse_place_html(read("place_panel.html"), PLACE_URL, rank=1)
    assert place is not None
    assert place.name == "Example Pizza Co"
    assert place.category == "Pizza restaurant"
    assert place.address == "12 Example Street, Springfield, IL 62701"
    assert place.phone == "(555) 010-1234"
    assert place.website == "https://examplepizza.example/"
    assert place.rating == 4.6
    assert place.reviews == 1284
    assert (place.latitude, place.longitude) == (39.7817, -89.6501)
    assert place.data_id == "0x880b5e0000000001:0x1a2b3c4d5e6f7a8b"
    assert place.place_id == "ChIJexample0001"
    assert place.maps_url is not None
    assert "?" not in place.maps_url
    assert place.rank == 1
    assert place.engine == "local"


def test_minimal_panel_uses_fallbacks() -> None:
    url = "https://www.google.com/maps/place/Corner+Bakery/@39.79,-89.64,17z/data=!4m2!3m1!1s0x1:0x2"
    place = parse_place_html(read("place_panel_minimal.html"), url)
    assert place is not None
    assert place.name == "Corner Bakery Example"  # empty h1 skipped
    assert place.category == "Bakery"
    assert place.address == "5 Market Square, Exampletown"
    assert place.phone == "+15550109999"  # from data-item-id
    assert place.rating == 4.2  # decimal comma
    assert place.reviews == 87  # "(87)"
    assert (place.latitude, place.longitude) == (39.79, -89.64)  # from @lat,lng
    assert place.data_id == "0x1:0x2"
    assert place.website is None


def test_page_without_name_is_not_a_place() -> None:
    assert parse_place_html("<html><body><div role='main'></div></body></html>", "https://x.example") is None


def test_feed_links_are_absolute_unique_and_ordered() -> None:
    links = parse_feed_links(read("results_feed.html"), "https://www.google.com/maps/search/pizza/")
    assert len(links) == 2
    assert links[0].startswith("https://www.google.com/maps/place/Example+Pizza+Co/")
    assert links[1].startswith("https://www.google.com/maps/place/Corner+Bakery+Example/")


def test_end_of_list() -> None:
    assert is_end_of_list(read("results_feed.html"))
    assert is_end_of_list("You\u2019ve reached the end of the list.")
    assert not is_end_of_list("<div>more results</div>")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3,120", 3120),
        ("3.120", 3120),
        ("3\u00a0120", 3120),
        ("(87)", 87),
        ("", None),
        (None, None),
        ("none", None),
    ],
)
def test_parse_count(text: str | None, expected: int | None) -> None:
    assert parse_count(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("4.5", 4.5), ("4,5 stars", 4.5), ("5", 5.0), ("7.1", None), ("", None), (None, None)],
)
def test_parse_rating(text: str | None, expected: float | None) -> None:
    assert parse_rating(text) == expected


def test_parse_maps_url_without_ids() -> None:
    assert parse_maps_url("https://www.google.com/maps/search/pizza/") == {
        "latitude": None,
        "longitude": None,
        "data_id": None,
        "place_id": None,
    }


def test_data_coordinates_win_over_viewport() -> None:
    url = "https://www.google.com/maps/place/X/@10.0,20.0,15z/data=!3d11.5!4d21.5"
    out = parse_maps_url(url)
    assert (out["latitude"], out["longitude"]) == (11.5, 21.5)


def test_unwrap_google_redirect() -> None:
    assert (
        unwrap_google_redirect("https://www.google.com/url?q=https://a.example/&sa=U") == "https://a.example/"
    )
    assert unwrap_google_redirect("https://b.example/") == "https://b.example/"
    assert unwrap_google_redirect(None) is None
