"""DealsPlus RSS connector.

DealsPlus is a community-curated deal aggregator. Users submit deals,
others vote, and the platform surfaces the most-upvoted to the
frontpage feed. Lower signal-to-noise than editorial sites (some
referral spam, occasional freebies without prices), but the AACE
matcher filters those out at the price-extraction step.

No API key, no auth — public RSS feed over HTTPS.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aace_execution.connectors._helpers import _extract_price, _normalize_title
from aace_execution.connectors.base import (
    BaseConnector,
    ConnectorError,
    NormalizedListing,
    RawListing,
)

logger = logging.getLogger(__name__)

DEFAULT_RSS_URL = "https://www.dealsplus.com/deals.rss"
"""Public DealsPlus frontpage RSS. If this 404s, try /front.rss or
/popular.rss as alternates — the connector accepts a custom URL via
the constructor for that case."""

_USER_AGENT = "AACE/0.1 (+https://github.com/Kpakpavi/aace-execution)"


class DealsPlusConnector(BaseConnector):
    """Pulls DealsPlus frontpage RSS and emits priced listings."""

    name = "dealsplus"

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
                "feedparser is required to use DealsPlusConnector "
                "(add 'feedparser' to your dependencies)"
            ) from exc

        feed = feedparser.parse(feed_text)
        if getattr(feed, "bozo", 0) and not feed.entries:
            raise ConnectorError(
                f"dealsplus RSS feed at {self._rss_url} is unparseable"
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
        # DealsPlus titles vary widely (community submitters). Check
        # title first, then fall back to summary if needed.
        price = _extract_price(raw.title)
        if price is None:
            summary = raw.raw_payload.get("summary") or ""
            price = _extract_price(summary)
        if price is None:
            logger.debug(
                "dealsplus_skip_no_price",
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
        if self._http is not None:
            resp = self._http.get(url, timeout=self._timeout)
            resp.raise_for_status()
            return resp.text
        try:
            import httpx
        except ImportError as exc:
            raise ConnectorError(
                "httpx is required to use DealsPlusConnector "
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
                f"dealsplus RSS fetch failed: {type(exc).__name__}: {exc}"
            ) from exc
