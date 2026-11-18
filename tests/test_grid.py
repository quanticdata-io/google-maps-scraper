from __future__ import annotations

import pytest

from gmaps_places.grid import BBox, cell_centers, parse_bbox, zoom_for_cell


def test_parse_bbox() -> None:
    assert parse_bbox("40.57, -74.04, 40.74, -73.83") == BBox(40.57, -74.04, 40.74, -73.83)


@pytest.mark.parametrize("text", ["1,2,3", "a,b,c,d", "10,0,5,1", "0,10,1,5", "-91,0,1,1"])
def test_parse_bbox_rejects_bad_input(text: str) -> None:
    with pytest.raises(ValueError, match="bbox"):
        parse_bbox(text)


def test_cells_cover_the_box_and_stay_inside() -> None:
    box = BBox(40.57, -74.04, 40.74, -73.83)  # about 19 km x 18 km
    height, width = box.size_km()
    assert 18 < height < 20
    assert 17 < width < 19
    centers = cell_centers(box, 5)
    assert len(centers) == 4 * 4
    for lat, lng in centers:
        assert box.south < lat < box.north
        assert box.west < lng < box.east
    # row by row, south to north
    assert centers[0][0] < centers[-1][0]
    assert centers[0][1] < centers[1][1]


def test_small_box_is_one_cell() -> None:
    box = BBox(45.0, 9.0, 45.001, 9.001)
    assert cell_centers(box, 2) == [(45.0005, 9.0005)]


def test_cell_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        cell_centers(BBox(0, 0, 1, 1), 0)


def test_zoom_grows_as_cells_shrink() -> None:
    assert zoom_for_cell(0.5, 40) > zoom_for_cell(2, 40) > zoom_for_cell(20, 40)
    assert 3 <= zoom_for_cell(10_000, 0) <= 20
    assert zoom_for_cell(0.0001, 0) == 20
