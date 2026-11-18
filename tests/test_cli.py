from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from gmaps_places.cli import main

from .mock_api import MockState, start

KEY = "qd_test_abc123"


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[MockState]:
    server, state, url = start()
    monkeypatch.setenv("QUANTICDATA_API_KEY", KEY)
    monkeypatch.setenv("QUANTICDATA_API_BASE", url)
    yield state
    server.shutdown()


def test_search_to_csv(api: MockState, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "pizza.csv"
    code = main(
        ["search", "pizza restaurants", "-l", "Brooklyn, NY", "-n", "3", "--country", "us", "-o", str(out)]
    )
    assert code == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["name"] for r in rows] == ["Example Place 1", "Example Place 2", "Example Place 3"]
    assert rows[0]["engine"] == "quanticdata"
    assert rows[0]["query"] == "pizza restaurants"
    method, path, body = api.requests[-1]
    assert (method, path) == ("POST", "/v1/scraper/collectors/google_maps_places/run")
    assert body == {
        "input": {"query": "pizza restaurants", "location": "Brooklyn, NY", "country": "us", "max_results": 3}
    }
    assert "3 places written" in capsys.readouterr().err


def test_search_background_to_jsonl_and_resume(api: MockState, tmp_path: Path) -> None:
    out = tmp_path / "p.jsonl"
    assert (
        main(
            [
                "search",
                "cafe",
                "-l",
                "Springfield",
                "-n",
                "2",
                "--background",
                "--poll-interval",
                "0",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    assert api.requests[-1][1].startswith("/v1/scraper/collectors/runs/")
    assert main(["search", "cafe", "-l", "Springfield", "-n", "4", "-o", str(out), "--resume"]) == 0
    names = [json.loads(line)["name"] for line in out.read_text(encoding="utf-8").splitlines()]
    assert names == ["Example Place 1", "Example Place 2", "Example Place 3", "Example Place 4"]


def test_search_json_stdout_with_param(api: MockState, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(["search", "cafe", "-l", "Springfield", "-n", "1", "-f", "json", "--param", "max_results=2"])
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 2  # --param overrides the documented field
    assert api.requests[-1][2]["input"]["max_results"] == 2


def test_invalid_input_exits_with_error(api: MockState, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["search", "", "-l", "Springfield"]) == 1
    assert "query and location are required" in capsys.readouterr().err


def test_bad_key(api: MockState, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("QUANTICDATA_API_KEY", "nope")
    assert main(["schema"]) == 1
    assert "Invalid or missing API key" in capsys.readouterr().err


def test_schema_and_status(api: MockState, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["required"] == ["query", "location"]
    assert main(["search", "x", "-l", "y", "-n", "2", "-f", "jsonl"]) == 0
    capsys.readouterr()
    assert main(["status", "run_0001"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "done"
    assert main(["status", "run_0001", "--csv"]) == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("rank,name")


def test_usage_errors(api: MockState, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["search", "x", "-l", "y", "--resume"]) == 2
    assert main(["search", "x", "-l", "y", "--engine", "quanticdata", "--grid", "1,2,3,4"]) == 2
    assert main(["search", "x", "-l", "y", "--param", "novalue"]) == 2
    err = capsys.readouterr().err
    assert "--resume needs --output" in err
    assert "--grid applies to the local engine" in err


def test_auto_engine_without_key_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    from gmaps_places import cli

    monkeypatch.delenv("QUANTICDATA_API_KEY", raising=False)
    assert cli._engine_name("auto") == "local"
    monkeypatch.setenv("QUANTICDATA_API_KEY", KEY)
    assert cli._engine_name("auto") == "quanticdata"
    assert cli._engine_name("local") == "local"
