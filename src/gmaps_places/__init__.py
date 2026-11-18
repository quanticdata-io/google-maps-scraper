"""Google Maps places scraper with a QuanticData API engine and a local Playwright engine."""

from ._version import __version__
from .api import (
    AuthenticationError,
    InputError,
    PaymentRequiredError,
    QuanticDataClient,
    QuanticDataError,
    RateLimitError,
    RunTimeoutError,
)
from .engines import CollectorRunError, LocalEngine, LocalOptions, QuanticDataEngine
from .grid import BBox, cell_centers, parse_bbox
from .models import COLUMNS, Place
from .output import PlaceWriter

__all__ = [
    "COLUMNS",
    "AuthenticationError",
    "BBox",
    "CollectorRunError",
    "InputError",
    "LocalEngine",
    "LocalOptions",
    "PaymentRequiredError",
    "Place",
    "PlaceWriter",
    "QuanticDataClient",
    "QuanticDataEngine",
    "QuanticDataError",
    "RateLimitError",
    "RunTimeoutError",
    "__version__",
    "cell_centers",
    "parse_bbox",
]
