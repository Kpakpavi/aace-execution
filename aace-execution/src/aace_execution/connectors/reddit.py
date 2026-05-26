"""Reddit deals connector — credential-free.

Reddit publishes a public JSON endpoint for every subreddit and listing
that does NOT require OAuth or an API key. The only requirements are:

  1. A unique, descriptive ``User-Agent`` header.
  2. A polite call rate (Reddit caps unauthenticated traffic at
     ~10 req/min per IP; we hit one multi-sub URL per scheduler tick,
     so we're well under).

This connector pulls ``/r/{sub_a}+{sub_b}+.../new.json`` and emits one
``NormalizedListing`` per post that has a parseable USD price in its
title. Posts without a price (daily discussion threads, freebies, etc.)
are skipped — they can't enter a discrepancy-based pipeline.
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

DEFAULT_SUBS: tuple[str, ...] = (
    "deals",
    "buildapcsales",
    "GameDeals",
    "Frugal",
)
"""Default deal-focused subs. Override via constructor or env."""

DEFAULT_LIMIT = 50
"""Posts per request. Reddit caps at 100; 50 keeps the response small."""

_USER_AGENT = "AACE/0.1 (+https://github.com/Kpakpavi/aace-execution)"


class RedditConnector(BaseConnector):
    """Pulls /r/{subs}/new.json and emits priced listings.

    No OAuth, no API key — Reddit's public JSON endpoint works as long
    as the User-Agent is unique and the call rate is sane.
    """

    name = "reddit"

    def __init__(
        self,
        subreddits: list[str] | tuple[str, ...] | None = None,
        *,
        http_client: Any = None,
        timeout_seconds: float = 15.0,
        currency: str = "USD",
        limit: int = DEFAULT_LIMIT,
    ) -> None:
        self._subs = tuple(subreddits) if subreddits else DEFAULT_SUBS
        self._http = http_client
        self._timeout = timeout_seconds
        self._currency = currency
        self._limit = limit

    # ------------------------------------------------------------------
    # Connector contract
    # ------------------------------------------------------------------

    def fetch(self) -> list[RawListing]:
        url = self._build_url()
        payload = self._fetch_json(url)
        children = _extract_children(payload)
        now = datetime.now(timezone.utc)
        out: list[RawListing] = []
        for child in children:
            data = child.get("data") or {}
            post_id = data.get("id") or ""
            title = data.get("title") or ""
            permalink = data.get("permalink") or ""
            link_url = data.get("url") or ""
            # Prefer the external URL the OP linked to (the actual deal);
            # fall back to the reddit thread itself.
            display_url = link_url or (
                f"https://www.reddit.com{permalink}" if permalink else ""
            )
            out.append(
                RawListing(
                    source=self.name,
                    source_external_id=str(post_id),
                    title=title,
                    url=display_url,
                    raw_payload={
                        "id": post_id,
                        "subreddit": data.get("subreddit") or "",
                        "title": title,
                        "url": link_url,
                        "permalink": permalink,
                        "selftext": data.get("selftext") or "",
                        "created_utc": data.get("created_utc"),
                        "score": data.get("score"),
                        "num_comments": data.get("num_comments"),
                    },
                    fetched_at=now,
                )
            )
        return out

    def normalize(self, raw: RawListing) -> NormalizedListing | None:
        price = _extract_price(raw.title)
        if price is None:
            logger.debug(
                "reddit_skip_no_price",
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
    # HTTP / URL
    # ------------------------------------------------------------------

    def _build_url(self) -> str:
        return (
            f"https://www.reddit.com/r/{'+'.join(self._subs)}/new.json"
            f"?limit={self._limit}"
        )

    def _fetch_json(self, url: str) -> Any:
        """Fetch a Reddit JSON endpoint.

        Uses an injected ``http_client`` when present (for tests); otherwise
        creates a short-lived ``httpx.Client`` with the polite User-Agent.
        """
        if self._http is not None:
            resp = self._http.get(url, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        try:
            import httpx
        except ImportError as exc:
            raise ConnectorError(
                "httpx is required to use RedditConnector "
                "(add 'httpx' to your dependencies)"
            ) from exc
        try:
            with httpx.Client(
                timeout=self._timeout,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            raise ConnectorError(
                f"reddit fetch failed: {type(exc).__name__}: {exc}"
            ) from exc


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _extract_children(payload: Any) -> list[dict[str, Any]]:
    """Pull post records from a Reddit listing response.

    Reddit listing shape:
        { "kind": "Listing",
          "data": { "children": [ { "kind": "t3", "data": { ... } }, ... ] } }
    """
    if not isinstance(payload, dict):
        raise ConnectorError("reddit response is not a JSON object")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ConnectorError("reddit response missing 'data' object")
    children = data.get("children")
    if not isinstance(children, list):
        raise ConnectorError("reddit response missing 'children' array")
    return [c for c in children if isinstance(c, dict)]
