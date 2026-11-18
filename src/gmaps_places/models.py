"""The output schema shared by every engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

#: Stable column order of every export (CSV header, JSON keys).
COLUMNS: tuple[str, ...] = (
    "rank",
    "name",
    "category",
    "address",
    "phone",
    "website",
    "rating",
    "reviews",
    "latitude",
    "longitude",
    "place_id",
    "data_id",
    "maps_url",
    "emails",
    "query",
    "location",
    "found_by",
    "engine",
    "scraped_at",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Place:
    """One Google Maps place. Every engine fills the fields it can; the rest stay ``None``."""

    name: str
    rank: int | None = None
    category: str | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = None
    reviews: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    place_id: str | None = None
    data_id: str | None = None
    maps_url: str | None = None
    emails: list[str] = field(default_factory=list)
    query: str | None = None
    location: str | None = None
    found_by: str | None = None
    engine: str | None = None
    scraped_at: str = field(default_factory=utc_now)

    def key(self) -> str:
        """De-duplication key: place id, then data id, then Maps URL, then name and address."""
        if self.place_id and "…" not in self.place_id:
            return f"pid:{self.place_id}"
        if self.data_id and "…" not in self.data_id:
            return f"did:{self.data_id}"
        if self.maps_url:
            return f"url:{self.maps_url.split('?')[0]}"
        return f"na:{self.name.strip().lower()}|{(self.address or '').strip().lower()}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {col: data[col] for col in COLUMNS}

    def to_row(self) -> dict[str, str]:
        """Flat string row for CSV (emails joined with ``;``)."""
        row: dict[str, str] = {}
        for col, value in self.to_dict().items():
            if value is None:
                row[col] = ""
            elif isinstance(value, list):
                row[col] = ";".join(str(v) for v in value)
            else:
                row[col] = str(value)
        return row

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Place:
        """Inverse of :meth:`to_dict` / :meth:`to_row` (used to resume from an existing file)."""

        def num(value: Any, kind: type[int] | type[float]) -> Any:
            if value in (None, ""):
                return None
            try:
                return kind(value)
            except (TypeError, ValueError):
                return None

        emails = data.get("emails") or []
        if isinstance(emails, str):
            emails = [e for e in emails.split(";") if e]
        text = {k: (str(data[k]) if data.get(k) not in (None, "") else None) for k in COLUMNS}
        return cls(
            name=str(data.get("name") or ""),
            rank=num(data.get("rank"), int),
            category=text["category"],
            address=text["address"],
            phone=text["phone"],
            website=text["website"],
            rating=num(data.get("rating"), float),
            reviews=num(data.get("reviews"), int),
            latitude=num(data.get("latitude"), float),
            longitude=num(data.get("longitude"), float),
            place_id=text["place_id"],
            data_id=text["data_id"],
            maps_url=text["maps_url"],
            emails=list(emails),
            query=text["query"],
            location=text["location"],
            found_by=text["found_by"],
            engine=text["engine"],
            scraped_at=text["scraped_at"] or utc_now(),
        )
