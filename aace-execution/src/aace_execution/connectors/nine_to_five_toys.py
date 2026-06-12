"""9to5Toys RSS connector.

9to5Toys is a tech-focused deal aggregator (sister site of 9to5Mac) that
publishes 20-30+ deals per day in their public RSS feed. Strong overlap
with what AACE's matcher cares about: Apple, audio gear, refurbs, home
electronics. No API key, no auth — straight RSS over HTTPS.

Because 9to5Toys curates by editorial team rather than community votes,
their titles tend to be more structured ("Apple Watch Series 11 41mm
GPS hits $299") which makes price extraction more reliable than the
community-driven sources.
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

DEFAULT_RSS_URL = "https://9to5toys.com/feed/"
"""Public 9to5Toys RSS feed. Free, no auth."""

_USER_AGENT = "AACE/0.1 (+https://github.com/Kpakpavi/aace-execution)"


class NineToFiveToysConnector(BaseConnector):
    """Pulls 9to5Toys RSS and emits priced listings."""

    name = "9to5toys"

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
                "feedparser is required to use NineToFiveToysConnector "
                "(add 'feedparser' to your dependencies)"
            ) from exc

        feed = feedparser.parse(feed_text)
        if getattr(feed, "bozo", 0) and not feed.entries:
            raise ConnectorError(
                f"9to5toys RSS feed at {self._rss_url} is unparseable"
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
        # 9to5Toys puts price in title for most posts but lead-ins like
        # "Today's best deals roundup" may need the summary as fallback.
        price = _extract_price(raw.title)
        if price is None:
            summary = raw.raw_payload.get("summary") or ""
            price = _extract_price(summary)
        if price is None:
            logger.debug(
                "9to5toys_skip_no_price",
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
                "httpx is required to use NineToFiveToysConnector "
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
                f"9to5toys RSS fetch failed: {type(exc).__name__}: {exc}"
            ) from exc
