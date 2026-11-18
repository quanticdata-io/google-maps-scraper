# Contributing

Thanks for helping keep this scraper working.

## Setup

```bash
git clone https://github.com/quanticdata-io/google-maps-scraper
cd google-maps-scraper
uv venv && uv pip install -e ".[browser]" --group dev
playwright install chromium   # the browser tests are skipped without it
```

Plain pip works too: `pip install -e ".[browser]" pytest pytest-cov mypy ruff build twine`.

## Checks

CI runs these on Python 3.10 to 3.13, on Ubuntu and Windows, plus the browser tests on Ubuntu:

```bash
ruff check .
ruff format --check .
mypy
pytest
```

## Ground rules

- Tests never call Google or the QuanticData API. Use `httpx.MockTransport`, `tests/mock_api.py` or the synthetic site in `tests/test_browser.py`.
- Fixtures are synthetic: reduce real markup to the structure the parser needs and replace every business detail with fictional values (`.example` domains, 555 phone numbers).
- Selectors live in `src/gmaps_places/parsing.py` only, and prefer `data-item-id`, `aria-label` and `role` over generated class names.
- The API engine sends only fields documented by the collector's `input_schema` (`gmaps-places schema`). New fields arrive through `--param` first.
- The output columns (`gmaps_places.models.COLUMNS`) are a public contract: adding a column is a minor release, renaming or removing one is a major release.
- User-facing changes need a CHANGELOG entry under "Unreleased".

## Fixing a markup change

1. Reproduce with `--headful` and save the HTML of the place panel.
2. Reduce it to a synthetic fixture in `tests/fixtures/` and add a failing test in `tests/test_parsing.py`.
3. Update the parser until the whole suite passes.

## Releases

Bump the version in `pyproject.toml` and `src/gmaps_places/_version.py`, update the CHANGELOG and tag `vX.Y.Z`. The release workflow builds and publishes to PyPI through trusted publishing.
