"""Deal-platform connectors.

Each connector fetches listings from a single deal source (Slickdeals,
Reddit, eBay, Walmart, etc.) and normalizes them to a shared schema
the pipeline can consume.

See ``connectors/base.py`` for the contract every connector implements.
"""

from aace_execution.connectors.base import (
    BaseConnector,
    Connector,
    ConnectorError,
    NormalizedListing,
    RawListing,
)

__all__ = [
    "BaseConnector",
    "Connector",
    "ConnectorError",
    "NormalizedListing",
    "RawListing",
]
