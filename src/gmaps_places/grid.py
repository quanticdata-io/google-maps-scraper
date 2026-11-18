"""Grid search: split a bounding box into cells so each search stays under the per-search result cap."""

from __future__ import annotations

import math
from dataclasses import dataclass

KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LNG_EQUATOR = 111.320
EARTH_CIRCUMFERENCE_KM = 40075.016
#: Approximate viewport width in tiles (256 px each) of the default browser window.
VIEWPORT_TILES = 1280 / 256


@dataclass(frozen=True)
class BBox:
    south: float
    west: float
    north: float
    east: float

    def __post_init__(self) -> None:
        if not (-90 <= self.south < self.north <= 90):
            raise ValueError("bbox: need -90 <= south < north <= 90")
        if not (-180 <= self.west < self.east <= 180):
            raise ValueError(
                "bbox: need -180 <= west < east <= 180 (boxes across the antimeridian are not supported)"
            )

    @property
    def center_lat(self) -> float:
        return (self.south + self.north) / 2

    def size_km(self) -> tuple[float, float]:
        """(height, width) in km, width measured at the centre latitude."""
        height = (self.north - self.south) * KM_PER_DEG_LAT
        width = (self.east - self.west) * KM_PER_DEG_LNG_EQUATOR * math.cos(math.radians(self.center_lat))
        return height, width


def parse_bbox(text: str) -> BBox:
    """``"south,west,north,east"`` in decimal degrees."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be 'south,west,north,east', e.g. 40.57,-74.04,40.74,-73.83")
    try:
        s, w, n, e = (float(p) for p in parts)
    except ValueError as exc:
        raise ValueError(f"bbox has a non-numeric value: {text!r}") from exc
    return BBox(s, w, n, e)


def cell_centers(bbox: BBox, cell_km: float) -> list[tuple[float, float]]:
    """Centres of a grid of roughly ``cell_km`` x ``cell_km`` cells covering ``bbox``, row by row."""
    if cell_km <= 0:
        raise ValueError("cell size must be positive")
    height_km, width_km = bbox.size_km()
    rows = max(1, math.ceil(height_km / cell_km))
    cols = max(1, math.ceil(width_km / cell_km))
    dlat = (bbox.north - bbox.south) / rows
    dlng = (bbox.east - bbox.west) / cols
    return [
        (round(bbox.south + dlat * (r + 0.5), 6), round(bbox.west + dlng * (c + 0.5), 6))
        for r in range(rows)
        for c in range(cols)
    ]


def zoom_for_cell(cell_km: float, lat: float) -> int:
    """Map zoom whose viewport is about ``cell_km`` wide at ``lat`` (clamped to 3..20)."""
    width_at_zoom0 = EARTH_CIRCUMFERENCE_KM * math.cos(math.radians(lat)) * VIEWPORT_TILES
    zoom = math.log2(width_at_zoom0 / max(cell_km, 0.01))
    return max(3, min(20, round(zoom)))
