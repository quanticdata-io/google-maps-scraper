"""Use the package from Python instead of the CLI.

Run against the local mock (no key, no network):

    python tests/mock_api.py &
    export QUANTICDATA_API_KEY=qd_test_123 QUANTICDATA_API_BASE=http://127.0.0.1:4011/v1
    python examples/library_usage.py
"""

from __future__ import annotations

from gmaps_places import PlaceWriter, QuanticDataClient, QuanticDataEngine


def main() -> None:
    with QuanticDataClient() as client:  # reads QUANTICDATA_API_KEY and QUANTICDATA_API_BASE
        engine = QuanticDataEngine(client)
        places = engine.search("coffee shops", "Austin, TX", max_results=5, country="us")
        with PlaceWriter("coffee.jsonl", "jsonl", resume=True) as writer:
            for place in places:
                writer.write(place)
                print(f"{place.rank:>3}  {place.name}  {place.rating or '-'}  {place.phone or ''}")
        print(f"{writer.written} new places in coffee.jsonl")


if __name__ == "__main__":
    main()
