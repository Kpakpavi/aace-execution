"""Connector framework.

Contract:

    A connector fetches listings from one deal source and normalizes them
    into ``NormalizedListing`` records the rest of the system understands.
    Cross-source matching, discrepancy detection, scoring, and alerting
    are NOT a connector's responsibility — that's the pipeline.

Two-step lifecycle:

    1. ``fetch()`` -> list[RawListing]        # source-shaped, untrusted
    2. ``normalize(raw)`` -> NormalizedListing | None

Use ``run()`` to do both in one pass, with per-item error tolerance
(one bad item must not lose the whole batch).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    """Raised when a connector cannot fetch from its source.

    Per-item normalization failures must NOT raise this — they're
    swallowed and skipped inside ``BaseConnector.run()``.
    """


@dataclass(frozen=True)
class RawListing:
    """An untrusted, source-shaped listing returned by ``fetch()``.

    Carries enough context to (a) normalize, (b) trace, and (c) replay.
    """

    source: str
    source_external_id: str
    title: str
    url: str
    raw_payload: dict[str, Any]
    fetched_at: datetime


@dataclass(frozen=True)
class NormalizedListing:
    """A connector's normalized output.

    Maps cleanly onto the pipeline's ``Listing`` + ``Observation`` pair
    (see ``aace_execution.api.models``).

    Fields used by the cross-source matcher:
        ``product_key``  — coarse identity (normalized title); next-day
                           work upgrades this to GTIN/UPC/ASIN where known.
        ``product_ref``  — strong identity if extractable; preferred over
                           ``product_key`` when present.
    """

    source: str
    listing_id: str            # source-prefixed, globally unique
    external_id: str           # source-local id (RSS guid, API id, etc.)
    product_key: str           # normalized title (lower, alphanum)
    title: str
    url: str
    price: float
    currency: str              # ISO 4217 (e.g. "USD")
    observed_at: datetime
    image_url: str | None = None
    product_ref: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Connector(Protocol):
    """Minimum surface every connector must implement."""

    name: str

    def fetch(self) -> list[RawListing]: ...

    def normalize(self, raw: RawListing) -> NormalizedListing | None: ...


class BaseConnector(ABC):
    """Convenience base class.

    Subclasses implement ``fetch()`` + ``normalize()``. ``run()`` ties
    them together with per-item exception tolerance and structured logs.
    """

    name: str = ""

    def run(self) -> list[NormalizedListing]:
        """Fetch + normalize in one pass.

        - A failed ``fetch()`` raises ``ConnectorError`` — bubble up.
        - Per-item normalization failures are logged at WARNING and skipped.
        - Items whose ``normalize()`` returns ``None`` are silently skipped
          (the connector decided they're not pipeline-usable).
        """
        try:
            raw_items = self.fetch()
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(
                f"connector {self.name!r} fetch failed: {type(exc).__name__}: {exc}"
            ) from exc

        out: list[NormalizedListing] = []
        for raw in raw_items:
            try:
                norm = self.normalize(raw)
            except Exception:
                logger.warning(
                    "connector_normalize_failed",
                    extra={
                        "connector": self.name,
                        "external_id": raw.source_external_id,
                        "title": raw.title,
                    },
                    exc_info=True,
                )
                continue
            if norm is not None:
                out.append(norm)

        logger.info(
            "connector_run_complete",
            extra={
                "connector": self.name,
                "raw_count": len(raw_items),
                "normalized_count": len(out),
            },
        )
        return out

    @abstractmethod
    def fetch(self) -> list[RawListing]: ...

    @abstractmethod
    def normalize(self, raw: RawListing) -> NormalizedListing | None: ...
