"""CSV, JSON and JSONL writers with de-duplication and resume."""

from __future__ import annotations

import csv
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import IO, Literal

from .models import COLUMNS, Place

Format = Literal["csv", "json", "jsonl"]
FORMATS: tuple[Format, ...] = ("csv", "json", "jsonl")


def guess_format(path: str | None, default: Format = "csv") -> Format:
    if path:
        suffix = Path(path).suffix.lower().lstrip(".")
        if suffix in FORMATS:
            return suffix
    return default


def read_existing(path: Path, fmt: Format) -> list[Place]:
    """Places already in an output file (empty when it does not exist)."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    text = path.read_text(encoding="utf-8")
    if fmt == "csv":
        return [Place.from_dict(dict(row)) for row in csv.DictReader(text.splitlines())]
    if fmt == "jsonl":
        return [Place.from_dict(json.loads(line)) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    return [Place.from_dict(item) for item in data] if isinstance(data, list) else []


class PlaceWriter:
    """Writes places as they arrive, skipping keys already seen.

    With ``resume=True`` an existing file is read first: its places are kept and
    their keys are skipped, so an interrupted run can be restarted with the
    same command.
    """

    def __init__(self, path: str | None, fmt: Format, *, resume: bool = False) -> None:
        self.path = Path(path) if path else None
        self.fmt = fmt
        self.seen: set[str] = set()
        self.written = 0
        self.skipped = 0
        self._json_items: list[Place] = []
        existing: list[Place] = []
        if self.path and resume:
            existing = read_existing(self.path, fmt)
            self.seen = {p.key() for p in existing}
        self.resumed = len(existing)

        self._fh: IO[str]
        if self.path is None:
            self._fh = sys.stdout
        elif fmt == "json":
            # JSON is one document: it is written to a temporary file and moved
            # into place on close, so an interrupted run never truncates the file.
            self._json_items = existing
            self._fh = self.path.with_name(self.path.name + ".partial").open(
                "w", encoding="utf-8", newline=""
            )
        else:
            mode = "a" if existing else "w"
            self._fh = self.path.open(mode, encoding="utf-8", newline="")
        self._csv: csv.DictWriter[str] | None = None
        if fmt == "csv":
            self._csv = csv.DictWriter(self._fh, fieldnames=list(COLUMNS), extrasaction="ignore")
            if not existing:
                self._csv.writeheader()

    def write(self, place: Place) -> bool:
        """Writes one place; returns ``False`` when it was a duplicate."""
        key = place.key()
        if key in self.seen:
            self.skipped += 1
            return False
        self.seen.add(key)
        self.written += 1
        if self.fmt == "csv":
            assert self._csv is not None
            self._csv.writerow(place.to_row())
        elif self.fmt == "jsonl":
            self._fh.write(json.dumps(place.to_dict(), ensure_ascii=False) + "\n")
        else:
            self._json_items.append(place)
        self._fh.flush()
        return True

    def write_all(self, places: Iterable[Place]) -> None:
        for p in places:
            self.write(p)

    def close(self) -> None:
        if self.fmt == "json":
            json.dump([p.to_dict() for p in self._json_items], self._fh, ensure_ascii=False, indent=2)
            self._fh.write("\n")
        if self._fh is not sys.stdout:
            self._fh.close()
            if self.fmt == "json" and self.path is not None:
                os.replace(self.path.with_name(self.path.name + ".partial"), self.path)
        else:
            self._fh.flush()

    def __enter__(self) -> PlaceWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
