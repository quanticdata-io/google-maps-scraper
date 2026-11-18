# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned

- Reviews export, once a reviews collector is published in the QuanticData catalog.
- Opening hours in the local parser.
- An asyncio variant of the local engine to search grid cells in parallel.

## [0.1.0] - 2026-11-18

### Added

- `gmaps-places` CLI with `search`, `schema` and `status` commands.
- `quanticdata` engine: runs the `google_maps_places` collector (rows inline, or a queued run polled until it settles), CSV export of a run, live input schema, typed errors for 401, 402, 422 and 429 with `Retry-After`.
- `local` engine (optional `[browser]` extra): headless Chromium via Playwright, consent screen handling, infinite-scroll results feed, place pages, proxy support, and grid search over a bounding box with de-duplication across cells.
- Parser isolated in `gmaps_places.parsing` and tested against synthetic HTML fixtures.
- Optional email enrichment from each place's own website (`--emails`).
- One output schema for both engines; CSV, JSON and JSONL writers with de-duplication and `--resume`.
- Local mock of the API (`tests/mock_api.py`) and end-to-end browser tests against a synthetic Maps-like site.

[Unreleased]: https://github.com/quanticdata-io/google-maps-scraper/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/quanticdata-io/google-maps-scraper/releases/tag/v0.1.0
