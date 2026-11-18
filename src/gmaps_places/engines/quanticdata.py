"""API engine: the QuanticData ``google_maps_places`` collector.

The collector is maintained server-side, pages past the first results, and is
billed per delivered place (pricing: https://quanticdata.io/pricing/). Its live
input schema is printed by ``gmaps-places schema``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from typing import Any

from ..api import MAPS_COLLECTOR, QuanticDataClient, QuanticDataError
from ..models import Place

#: Columns of a collector row that map 1:1 onto :class:`Place`.
_TEXT_FIELDS = ("category", "address", "phone", "website", "place_id", "data_id", "found_by")


def _float(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _int(v: Any) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def place_from_row(row: Mapping[str, Any], *, query: str | None, location: str | None) -> Place:
    """Maps one collector row onto the shared schema."""
    text = {k: (str(row[k]) if row.get(k) not in (None, "") else None) for k in _TEXT_FIELDS}
    maps_url = row.get("maps_url") or row.get("url")
    return Place(
        name=str(row.get("name") or ""),
        rank=_int(row.get("rank")),
        category=text["category"],
        address=text["address"],
        phone=text["phone"],
        website=text["website"],
        rating=_float(row.get("rating")),
        reviews=_int(row.get("reviews")),
        latitude=_float(row.get("latitude")),
        longitude=_float(row.get("longitude")),
        place_id=text["place_id"],
        data_id=text["data_id"],
        maps_url=str(maps_url) if maps_url else None,
        query=query,
        location=location,
        found_by=text["found_by"],
        engine="quanticdata",
    )


class CollectorRunError(QuanticDataError):
    """The run finished with status ``failed``."""


class QuanticDataEngine:
    name = "quanticdata"

    def __init__(
        self,
        client: QuanticDataClient,
        *,
        background: bool = False,
        poll_interval: float = 3.0,
        timeout: float = 900.0,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.client = client
        self.background = background
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.on_progress = on_progress
        self.last_run: dict[str, Any] | None = None

    def build_input(
        self,
        query: str,
        location: str,
        *,
        max_results: int | None = None,
        country: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Collector input: the documented ``query``, ``location``, ``country`` and ``max_results``,
        plus any other field of the live ``input_schema`` passed through ``extra``."""
        data: dict[str, Any] = {"query": query, "location": location}
        if country:
            data["country"] = country
        if max_results is not None:
            data["max_results"] = max_results
        if extra:
            data.update(extra)
        return data

    def search(
        self,
        query: str,
        location: str,
        *,
        max_results: int | None = None,
        country: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> Iterator[Place]:
        payload = self.build_input(query, location, max_results=max_results, country=country, extra=extra)
        run = self.client.run(
            payload,
            slug=MAPS_COLLECTOR,
            background=self.background,
            poll_interval=self.poll_interval,
            timeout=self.timeout,
            on_progress=self.on_progress,
        )
        self.last_run = run
        if run.get("status") == "failed":
            raise CollectorRunError(str(run.get("error") or "Collector run failed"), payload=run)
        for row in run.get("results") or []:
            if isinstance(row, Mapping):
                yield place_from_row(row, query=query, location=location)
