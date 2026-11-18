"""Command line: ``gmaps-places search | schema | status``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator, Sequence
from typing import Any

from ._version import __version__
from .api import ENV_API_KEY, QuanticDataClient, QuanticDataError, RateLimitError
from .engines import LocalEngine, LocalOptions, QuanticDataEngine
from .enrich import EmailEnricher
from .grid import parse_bbox
from .models import Place
from .output import FORMATS, PlaceWriter, guess_format

EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _parse_params(items: Sequence[str]) -> dict[str, Any]:
    """``--param key=value``: JSON values (numbers, booleans, lists) are decoded, anything else is text."""
    out: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--param needs key=value, got {item!r}")
        key, raw = item.split("=", 1)
        try:
            out[key.strip()] = json.loads(raw)
        except json.JSONDecodeError:
            out[key.strip()] = raw
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gmaps-places",
        description="Google Maps places to CSV, JSON or JSONL, via the QuanticData API or a local browser.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="search places and export them")
    s.add_argument("query", help='what to look for, e.g. "pizza restaurants"')
    s.add_argument("-l", "--location", required=True, help='where, e.g. "Brooklyn, NY"')
    s.add_argument("-n", "--max-results", type=int, default=20, help="maximum places (default 20)")
    s.add_argument("-o", "--output", help="output file (default: stdout)")
    s.add_argument(
        "-f",
        "--format",
        choices=FORMATS,
        help="csv, json or jsonl (default: from the file extension, else csv)",
    )
    s.add_argument("--resume", action="store_true", help="keep the places already in --output and skip them")
    s.add_argument(
        "--engine",
        choices=("auto", "quanticdata", "local"),
        default="auto",
        help=f"auto = quanticdata when {ENV_API_KEY} is set, else local",
    )
    s.add_argument(
        "--emails",
        action="store_true",
        help="visit each place's website to collect public emails (off by default)",
    )

    api = s.add_argument_group("quanticdata engine")
    api.add_argument("--country", help="two-letter country code passed to the collector, e.g. us")
    api.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="any other field of the collector's input schema (see `gmaps-places schema`)",
    )
    api.add_argument("--background", action="store_true", help="queue the run and poll it (for large runs)")
    api.add_argument("--poll-interval", type=float, default=3.0)
    api.add_argument("--timeout", type=float, default=900.0, help="seconds to wait for a queued run")

    loc = s.add_argument_group("local engine")
    loc.add_argument(
        "--grid", metavar="S,W,N,E", help="bounding box to split into cells, one search per cell"
    )
    loc.add_argument("--cell-km", type=float, default=2.0, help="grid cell size in km (default 2)")
    loc.add_argument("--zoom", type=int, help="map zoom per cell (default: derived from --cell-km)")
    loc.add_argument(
        "--proxy", help="proxy URL for the browser and the email fetcher, e.g. http://user:pass@host:port"
    )
    loc.add_argument("--delay", type=float, default=1.0, help="seconds between place pages (default 1)")
    loc.add_argument("--headful", action="store_true", help="show the browser window")
    loc.add_argument(
        "--lang", default="en", help="interface language (default en; the parser expects English labels)"
    )
    loc.add_argument("--maps-url", default=None, help=argparse.SUPPRESS)  # tests: point at a local page

    sc = sub.add_parser("schema", help="print the live input schema of the google_maps_places collector")
    sc.add_argument(
        "--full", action="store_true", help="print the whole collector entry, not just input_schema"
    )

    st = sub.add_parser("status", help="show a queued or finished collector run")
    st.add_argument("run_id")
    st.add_argument("--csv", action="store_true", help="print the rows as CSV")
    return p


def _engine_name(choice: str) -> str:
    if choice != "auto":
        return choice
    return "quanticdata" if os.environ.get(ENV_API_KEY, "").strip() else "local"


def _search(args: argparse.Namespace) -> int:
    engine = _engine_name(args.engine)
    fmt = args.format or guess_format(args.output)
    if args.resume and not args.output:
        _log("--resume needs --output")
        return EXIT_USAGE
    if engine == "quanticdata" and args.grid:
        _log("--grid applies to the local engine; the collector pages past the first results by itself")
        return EXIT_USAGE

    places: Iterator[Place]
    client: QuanticDataClient | None = None
    if engine == "quanticdata":
        client = QuanticDataClient()

        def progress(run: dict[str, Any]) -> None:
            _log(f"run {run.get('run_id')}: {run.get('status')}, {run.get('count', 0)} rows")

        qd = QuanticDataEngine(
            client,
            background=args.background,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
            on_progress=progress,
        )
        places = qd.search(
            args.query,
            args.location,
            max_results=args.max_results,
            country=args.country,
            extra=_parse_params(args.param),
        )
    else:
        options = LocalOptions(headless=not args.headful, proxy=args.proxy, delay=args.delay, lang=args.lang)
        if args.maps_url:
            options.maps_url = args.maps_url
        local = LocalEngine(options, log=_log)
        places = local.search(
            args.query,
            args.location,
            max_results=args.max_results,
            bbox=parse_bbox(args.grid) if args.grid else None,
            cell_km=args.cell_km,
            zoom=args.zoom,
        )

    enricher = EmailEnricher(proxy=args.proxy) if args.emails else None
    writer = PlaceWriter(args.output, fmt, resume=args.resume)
    if writer.resumed:
        _log(f"resuming: {writer.resumed} places already in {args.output}")
    try:
        for place in places:
            if place.key() in writer.seen:
                writer.skipped += 1
                continue
            if enricher and place.website and not place.emails:
                place.emails = enricher.emails_for(place.website)
            writer.write(place)
    finally:
        writer.close()
        if enricher:
            enricher.close()
        if client:
            client.close()
    _log(f"{writer.written} places written ({writer.skipped} duplicates skipped) with the {engine} engine")
    return EXIT_OK


def _schema(args: argparse.Namespace) -> int:
    with QuanticDataClient() as client:
        collector = client.get_collector()
    print(
        json.dumps(
            collector if args.full else collector.get("input_schema", {}), indent=2, ensure_ascii=False
        )
    )
    return EXIT_OK


def _status(args: argparse.Namespace) -> int:
    with QuanticDataClient() as client:
        if args.csv:
            sys.stdout.write(client.get_run_csv(args.run_id))
        else:
            run = client.get_run(args.run_id)
            summary = {
                k: run.get(k) for k in ("run_id", "status", "count", "partial", "partial_reason", "error")
            }
            print(json.dumps(summary, indent=2, ensure_ascii=False))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "search":
            return _search(args)
        if args.command == "schema":
            return _schema(args)
        return _status(args)
    except RateLimitError as exc:
        wait = f" Retry in {exc.retry_after:.0f}s." if exc.retry_after else ""
        _log(f"error: {exc.message}{wait}")
        return EXIT_ERROR
    except QuanticDataError as exc:
        _log(f"error: {exc.message}")
        return EXIT_ERROR
    except (ValueError, RuntimeError) as exc:
        _log(f"error: {exc}")
        return EXIT_USAGE
    except KeyboardInterrupt:
        _log("interrupted: rerun the same command with --resume to continue")
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
