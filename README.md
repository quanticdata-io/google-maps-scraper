# Google Maps Scraper

Export Google Maps places (name, category, address, phone, website, rating, review count, coordinates, place id) to CSV, JSON or JSONL, from the command line or from Python.

[![CI](https://github.com/quanticdata-io/google-maps-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/quanticdata-io/google-maps-scraper/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/gmaps-places-scraper.svg)](https://pypi.org/project/gmaps-places-scraper/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Two engines behind one command and one output schema:

| | `quanticdata` engine | `local` engine |
| --- | --- | --- |
| How it works | Runs the `google_maps_places` collector of the [QuanticData API](https://quanticdata.io/docs/) | Drives headless Chromium on your machine with Playwright |
| Needs | An API key (`QUANTICDATA_API_KEY`) | `pip install 'gmaps-places-scraper[browser]'` and `playwright install chromium` |
| Maintenance | Kept working server-side when Google changes its pages | Depends on Google's page markup: it can break until the selectors are updated here |
| Volume | Up to the collector's per-run cap, paged server-side | Grid mode (`--grid`) splits an area into cells to go past the per-search cap |
| Blocks and captchas | Handled by the service | Your IP; use `--proxy` for long runs |
| Cost | Billed per delivered place, see [pricing](https://quanticdata.io/pricing/) | Free, your bandwidth and time |

With `--engine auto` (the default) the tool uses the `quanticdata` engine when `QUANTICDATA_API_KEY` is set, and the `local` engine otherwise.

## Install

```bash
pip install gmaps-places-scraper              # API engine only (depends on httpx)
pip install 'gmaps-places-scraper[browser]'   # adds the local engine
playwright install chromium                   # once, for the local engine
```

Python 3.10 or later. The command is `gmaps-places` (also `python -m gmaps_places`).

## Quickstart

With an API key:

```bash
export QUANTICDATA_API_KEY=qd_live_your_key
gmaps-places search "pizza restaurants" --location "Brooklyn, NY" --country us -n 50 -o pizza.csv
```

Without a key, in a local browser:

```bash
gmaps-places search "pizza restaurants" --location "Brooklyn, NY" -n 50 -o pizza.csv --engine local
```

Try the CLI with no key and no network against the bundled mock of the API (from a clone of this repository):

```bash
python tests/mock_api.py &        # QuanticData mock API listening on http://127.0.0.1:4011/v1
export QUANTICDATA_API_KEY=qd_test_123 QUANTICDATA_API_BASE=http://127.0.0.1:4011/v1
gmaps-places search "pizza restaurants" -l "Brooklyn, NY" -n 3 -o pizza.csv
gmaps-places schema
```

## Output

Every engine writes the same columns, in this order:

`rank, name, category, address, phone, website, rating, reviews, latitude, longitude, place_id, data_id, maps_url, emails, query, location, found_by, engine, scraped_at`

- The format comes from the file extension (`.csv`, `.json`, `.jsonl`) or `--format`. Without `-o` the rows go to stdout.
- Places are de-duplicated by place id, then data id, then Maps URL, then name and address.
- `--resume` keeps the places already in the output file and skips them, so an interrupted run can be restarted with the same command. CSV and JSONL are written row by row; JSON is written when the run ends (prefer JSONL for long runs).
- In CSV, `emails` is a `;`-separated list.

## Commands

```text
gmaps-places search QUERY --location WHERE [options]
gmaps-places schema [--full]          # live input schema of the google_maps_places collector
gmaps-places status RUN_ID [--csv]    # a queued or finished collector run
```

Common `search` options:

| Option | Meaning |
| --- | --- |
| `-n, --max-results` | Maximum places (default 20) |
| `-o, --output`, `-f, --format`, `--resume` | Output file, format, resume |
| `--engine auto\|quanticdata\|local` | Engine choice |
| `--emails` | Visit each place's own website (homepage and up to three contact pages) and collect public email addresses. Off by default |

`quanticdata` engine options:

| Option | Meaning |
| --- | --- |
| `--country` | Two-letter country code passed to the collector |
| `--param KEY=VALUE` | Any other field of the collector's input schema (`gmaps-places schema` lists them); values are read as JSON when they parse |
| `--background` | Queue the run and poll it, for large runs (`--poll-interval`, `--timeout`) |

`local` engine options:

| Option | Meaning |
| --- | --- |
| `--grid S,W,N,E` | Bounding box split into cells of `--cell-km` (default 2 km); one search per cell, results merged |
| `--zoom` | Map zoom per cell (default: derived from the cell size) |
| `--proxy URL` | `http://user:pass@host:port`, used by the browser and by `--emails` (the browser does not support SOCKS5 with a password). HTTP proxy strings generated for a [QuanticData](https://quanticdata.io/) proxy plan work as they are |
| `--delay` | Seconds between place pages (default 1) |
| `--headful` | Show the browser window |
| `--lang` | Interface language (default `en`; the parser reads English labels) |

## Python

```python
from gmaps_places import PlaceWriter, QuanticDataClient, QuanticDataEngine

with QuanticDataClient() as client:  # QUANTICDATA_API_KEY, QUANTICDATA_API_BASE
    engine = QuanticDataEngine(client)
    with PlaceWriter("coffee.jsonl", "jsonl", resume=True) as writer:
        for place in engine.search("coffee shops", "Austin, TX", max_results=50, country="us"):
            writer.write(place)
```

```python
from gmaps_places import LocalEngine, LocalOptions, parse_bbox

engine = LocalEngine(LocalOptions(proxy="http://user:pass@host:port", delay=1.5))
for place in engine.search(
    "dentist", "", max_results=200, bbox=parse_bbox("30.20,-97.80,30.32,-97.68"), cell_km=3
):
    print(place.name, place.phone)
```

More in [`examples/`](examples/).

## How the API engine calls QuanticData

Only documented endpoints, with `Authorization: Bearer $QUANTICDATA_API_KEY`:

| Call | Endpoint |
| --- | --- |
| Run | `POST /v1/scraper/collectors/google_maps_places/run` with `{"input": {"query", "location", "country", "max_results", ...}}` |
| Poll a queued run | `GET /v1/scraper/collectors/runs/{runId}` until `done` or `failed` |
| CSV of a run | `GET /v1/scraper/collectors/runs/{runId}?format=csv` |
| Input schema | `GET /v1/scraper/collectors/google_maps_places` |

Short runs answer with the rows; long ones answer 202 and are polled. HTTP 429 is retried after `Retry-After` when the wait is short; a run is never started twice by the client. A 402 means the free tier and the balance cannot cover the run; a 422 means the input cannot succeed as sent. Identical input sent again inside the dedup window returns the existing run without a new charge.

## When the local engine breaks

Google changes its Maps markup from time to time. All selectors live in [`src/gmaps_places/parsing.py`](src/gmaps_places/parsing.py) and prefer stable hooks (`data-item-id`, `aria-label`, `role`) over generated class names. To fix a break: save the HTML of a place panel (`page.content()`), reduce it to a synthetic fixture in `tests/fixtures/`, add a failing test, update the parser. Pull requests with a fixture are very welcome.

## Responsible use

- Collect public business information only, and use it lawfully: data protection law (for example the GDPR) applies to personal data such as names or emails of sole traders, and so do anti-spam rules for any outreach.
- Keep the request rate low (`--delay`), do not overload the services you read, and respect the terms that apply to you.
- `--emails` reads only each business's own website. Leave it off unless you have a lawful reason to process contact data.

## Development

```bash
uv venv && uv pip install -e ".[browser]" --group dev    # or: pip install -e ".[browser]" pytest pytest-cov mypy ruff build twine
playwright install chromium                              # for the browser tests (skipped without it)
ruff check . && ruff format --check . && mypy && pytest
```

Tests never call the QuanticData API or Google: the API engine runs against `httpx.MockTransport` and the local mock server in `tests/mock_api.py`; the local engine runs a real headless Chromium against a synthetic Maps-like site served on localhost. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
