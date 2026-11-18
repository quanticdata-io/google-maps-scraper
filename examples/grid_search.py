"""Local engine with a grid: one browser search per cell, results de-duplicated.

Needs: pip install 'gmaps-places-scraper[browser]' && playwright install chromium
Optional: export PROXY_URL=http://user:pass@host:port (for example a QuanticData proxy string)
"""

from __future__ import annotations

import os

from gmaps_places import LocalEngine, LocalOptions, PlaceWriter, cell_centers, parse_bbox


def main() -> None:
    bbox = parse_bbox("30.20,-97.80,30.32,-97.68")  # central Austin, TX
    print(f"{len(cell_centers(bbox, 3.0))} cells of about 3 km")
    engine = LocalEngine(LocalOptions(proxy=os.environ.get("PROXY_URL"), delay=1.5), log=print)
    with PlaceWriter("austin-dentists.csv", "csv", resume=True) as writer:
        for place in engine.search("dentist", "", max_results=200, bbox=bbox, cell_km=3.0):
            writer.write(place)


if __name__ == "__main__":
    main()
