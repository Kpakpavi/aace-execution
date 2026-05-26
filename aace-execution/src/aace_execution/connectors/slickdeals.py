"""Slickdeals frontpage RSS connector.

Slickdeals publishes a public RSS feed of community-curated deals on the
frontpage — no API key, no rate-limit auth, fully free. Each feed item
has a title (containing the deal price), a link to the discussion thread,
a guid, and a publication time.

This connector pulls that feed and emits one ``NormalizedListing`` per
item that has a parseable price. Items without a price (free samples,
giveaways, etc.) are skipped — they can't enter a discrepancy-based
pipeline.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from aace_execution.connectors.base import (
    BaseConnector,
    ConnectorError,
    NormalizedListing,
    RawListing,
)

logger = logging.getLogger(__name__)

DEFAULT_RSS_URL = (
    "https://slickdeals.net/newsearch.php"
    "?mode=frontpage&searcharea=deals&searchin=first&rss=1"
)
"""Public Slickdeals frontpage RSS feed. Free, no auth."""

_USER_AGENT = "AACE/0.1 (+https://github.com/Kpakpavi/aace-execution)"

# Match "$1,299", "$ 49.99", "$799" — captures the numeric portion.
_PRICE_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")

# Strip everything that isn't lowercase alphanumeric for a coarse product key.
_TITLE_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


class SlickdealsConnector(BaseConnector):
    """Pulls Slickdeals frontpage RSS and emits priced listings."""

    name = "slickdeals"

    def __init__(
        self,
        rss_url: str = DEFAULT_RSS_URL,
        *,
        http_client: Any = None,
        timeout_seconds: float = 15.0,
        currency: str = "USD",
    ) -> None:
        self._rss_url = rss_url
        self._http = http_client
        self._timeout = timeout_seconds
        self._currency = currency

    # ------------------------------------------------------------------
    # Connector contract
    # ------------------------------------------------------------------

    def fetch(self) -> list[RawListing]:
        feed_text = self._fetch_text(self._rss_url)
        try:
            import feedparser
        except ImportError as exc:
            raise ConnectorError(
                "feedparser is required to use SlickdealsConnector "
                "(add 'feedparser' to your dependencies)"
            ) from exc

        feed = feedparser.parse(feed_text)
        if getattr(feed, "bozo", 0) and not feed.entries:
            # Malformed and no usable entries — treat as fetch failure.
            raise ConnectorError(
                f"slickdeals RSS feed at {self._rss_url} is unparseable"
            )

        now = datetime.now(timezone.utc)
        out: list[RawListing] = []
        for entry in feed.entries:
            guid = (
                getattr(entry, "id", None)
                or getattr(entry, "guid", None)
                or getattr(entry, "link", None)
                or ""
            )
            title = getattr(entry, "title", "") or ""
            link = getattr(entry, "link", "") or ""
            out.append(
                RawListing(
                    source=self.name,
                    source_external_id=str(guid),
                    title=title,
                    url=link,
                    raw_payload={
                        "guid": guid,
                        "title": title,
                        "link": link,
                        "summary": getattr(entry, "summary", "") or "",
                        "published": getattr(entry, "published", "") or "",
                    },
                    fetched_at=now,
                )
            )
        return out

    def normalize(self, raw: RawListing) -> NormalizedListing | None:
        price = _extract_price(raw.title)
        if price is None:
            logger.debug(
                "slickdeals_skip_no_price",
                extra={"external_id": raw.source_external_id, "title": raw.title},
            )
            return None
        product_key = _normalize_title(raw.title)
        if not product_key:
            return None
        return NormalizedListing(
            source=self.name,
            listing_id=f"{self.name}:{raw.source_external_id}",
            external_id=raw.source_external_id,
            product_key=product_key,
            title=raw.title,
            url=raw.url,
            price=price,
            currency=self._currency,
            observed_at=raw.fetched_at,
            extra={"raw": dict(raw.raw_payload)},
        )

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _fetch_text(self, url: str) -> str:
        """Fetch RSS feed text.

        Uses an injected ``http_client`` when present (for tests). Otherwise
        creates a short-lived ``httpx.Client`` with a polite user-agent.
        """
        if self._http is not None:
            resp = self._http.get(url, timeout=self._timeout)
            resp.raise_for_status()
            return resp.text
        try:
            import httpx
        except ImportError as exc:
            raise ConnectorError(
                "httpx is required to use SlickdealsConnector "
                "(add 'httpx' to your dependencies)"
            ) from exc
        try:
            with httpx.Client(
                timeout=self._timeout,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/rss+xml"},
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as exc:
            raise ConnectorError(
                f"slickdeals RSS fetch failed: {type(exc).__name__}: {exc}"
            ) from exc


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _extract_price(text: str) -> float | None:
    """Pull the first plausible USD price out of a deal title.

    Examples:
        "MacBook Air $799 + Free Shipping"           -> 799.0
        "Big TV $1,299"                              -> 1299.0
        "Headphones $49.99 (was $129)"               -> 49.99
        "Free Sample of Soap"                        -> None
    """
    match = _PRICE_RE.search(text)
    if not match:
        return None
    cleaned = match.group(1).replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_title(title: str) -> str:
    """Reduce a deal title to a coarse cross-source product key.

    This is intentionally lossy: lowercase, alphanumeric, single spaces.
    Day 3 work will add stronger keys (GTIN/UPC/ASIN extraction) on top
    of this fallback.
    """
    return _TITLE_NORMALIZE_RE.sub(" ", title.lower()).strip()
