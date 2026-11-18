from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from gmaps_places.models import COLUMNS, Place
from gmaps_places.output import PlaceWriter, guess_format, read_existing


def place(i: int, **kw: object) -> Place:
    base: dict[str, object] = {
        "name": f"Place {i}",
        "rank": i,
        "rating": 4.5,
        "reviews": 10 * i,
        "place_id": f"ChIJ{i}",
        "emails": ["a@shop.example"] if i == 1 else [],
    }
    base.update(kw)
    return Place(**base)  # type: ignore[arg-type]


def test_keys_prefer_stable_ids() -> None:
    assert place(1).key() == "pid:ChIJ1"
    assert Place(name="A", data_id="0x1:0x2").key() == "did:0x1:0x2"
    assert Place(name="A", place_id="ChIJ…", data_id="0x1:0x2").key() == "did:0x1:0x2"  # truncated id ignored
    assert Place(name="A", maps_url="https://m.example/place/A?x=1").key() == "url:https://m.example/place/A"
    assert Place(name=" A ", address="1 St").key() == "na:a|1 st"


def test_round_trip_through_csv_row() -> None:
    p = place(1, latitude=1.5, longitude=-2.25, website="shop.example")
    back = Place.from_dict(p.to_row())
    assert back.to_dict() == p.to_dict()


@pytest.mark.parametrize(
    ("path", "fmt"),
    [("a.csv", "csv"), ("a.JSON", "json"), ("a.jsonl", "jsonl"), ("a.txt", "csv"), (None, "csv")],
)
def test_guess_format(path: str | None, fmt: str) -> None:
    assert guess_format(path) == fmt


@pytest.mark.parametrize("fmt", ["csv", "json", "jsonl"])
def test_write_dedup_and_resume(tmp_path: Path, fmt: str) -> None:
    out = tmp_path / f"places.{fmt}"
    with PlaceWriter(str(out), fmt) as w:  # type: ignore[arg-type]
        assert w.write(place(1))
        assert w.write(place(2))
        assert not w.write(place(2, name="Same id, other name"))
    assert [p.name for p in read_existing(out, fmt)] == ["Place 1", "Place 2"]  # type: ignore[arg-type]

    with PlaceWriter(str(out), fmt, resume=True) as w:  # type: ignore[arg-type]
        assert w.resumed == 2
        assert not w.write(place(1))
        assert w.write(place(3))
        assert (w.written, w.skipped) == (1, 1)
    names = [p.name for p in read_existing(out, fmt)]  # type: ignore[arg-type]
    assert names == ["Place 1", "Place 2", "Place 3"]
    assert read_existing(out, fmt)[0].emails == ["a@shop.example"]  # type: ignore[arg-type]


def test_csv_has_stable_header(tmp_path: Path) -> None:
    out = tmp_path / "p.csv"
    with PlaceWriter(str(out), "csv") as w:
        w.write(place(1))
    with out.open(encoding="utf-8") as fh:
        reader = csv.reader(fh)
        assert tuple(next(reader)) == COLUMNS
        row = next(reader)
    assert row[COLUMNS.index("emails")] == "a@shop.example"


def test_json_is_written_atomically(tmp_path: Path) -> None:
    out = tmp_path / "p.json"
    out.write_text("[]", encoding="utf-8")
    w = PlaceWriter(str(out), "json", resume=True)
    w.write(place(1))
    assert json.loads(out.read_text(encoding="utf-8")) == []  # untouched until close
    w.close()
    assert [d["name"] for d in json.loads(out.read_text(encoding="utf-8"))] == ["Place 1"]
    assert not (tmp_path / "p.json.partial").exists()


def test_stdout_writer(capsys: pytest.CaptureFixture[str]) -> None:
    with PlaceWriter(None, "jsonl") as w:
        w.write(place(1))
    line = capsys.readouterr().out.strip()
    assert json.loads(line)["name"] == "Place 1"
