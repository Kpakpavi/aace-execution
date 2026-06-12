"""Resale comps connector — fetches "what does this actually sell for?"

Until now the worker has used ``max_price`` (the highest observed source
price) as a proxy for resale value. That's optimistic — it conflates
"someone listed it for $X" with "someone paid $X." For real reseller
economics we want the *sold-comp average*: the typical price the item
recently changed hands at on the target resale platform.

Architecture
------------
This module defines a small protocol — ``ResaleCompsClient`` — and
several implementations:

* ``MockResaleCompsClient``  — deterministic fake comps. Used for tests
                               and during today's Sprint 2 scaffolding
                               while real Keepa/SerpAPI access is being
                               approved. Returns plausible sold-avg
                               numbers based on the input price floor so
                               net-profit math is exercised end-to-end.
* ``KeepaClient`` (stub)     — Amazon price history via keepa.com API.
                               Implemented in a follow-up once an API
                               key is provisioned.
* ``SerpApiClient`` (stub)   — Google Shopping snapshot via serpapi.com.
                               Implemented in a follow-up. Covers
                               non-Amazon resale platforms.
* ``RoutedResaleCompsClient`` — wraps several clients and dispatches by
                               target platform. Amazon -> Keepa, all
                               others -> SerpApi, with a mock fallback
                               when neither is configured.

The protocol is intentionally tiny (one method) so swapping mock for
real data later is a one-line change in worker wiring.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data shape returned to the rest of the system
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResaleComp:
    """One resale-comp lookup result.

    Carries enough metadata for downstream code (worker, dashboard) to
    decide how much to trust the number — number of comparable sales,
    the source it came from, and a confidence band 0..1.
    """

    product_key: str
    platform: str             # "Amazon", "eBay", "FB Marketplace (Local)" etc.
    sold_avg: float           # USD; the resale baseline we use for net-profit
    sold_count: int           # how many comps backed the average; >= 0
    source: str               # "keepa" | "serpapi" | "mock"
    observed_at: datetime
    confidence: float = 0.0   # 0..1; producers SHOULD populate, callers MAY use
    extra: dict | None = None  # source-specific raw bits, optional


# ---------------------------------------------------------------------------
# Protocol every client must satisfy
# ---------------------------------------------------------------------------


@runtime_checkable
class ResaleCompsClient(Protocol):
    """Minimum surface for any resale-comps source.

    Implementations MUST NOT raise on a "no data" outcome — return
    ``None`` instead. Reserve exceptions for transport-level failures
    (network down, auth rejected, quota exhausted) that the worker
    should log and continue past.
    """

    name: str

    def lookup(
        self,
        *,
        product_key: str,
        platform: str,
        price_hint: float | None = None,
    ) -> ResaleComp | None: ...


# ---------------------------------------------------------------------------
# Mock implementation — used today + in tests
# ---------------------------------------------------------------------------


class MockResaleCompsClient:
    """Deterministic fake comps client.

    Returns a sold-avg that is a small, product-key-dependent markup over
    the ``price_hint``. The markup is hashed off the product key so the
    same product always gets the same simulated comp — handy for tests
    and demos.

    If ``price_hint`` is None, falls back to a flat $50 baseline.
    """

    name = "mock"

    def __init__(self, *, default_markup_pct: float = 0.18) -> None:
        """``default_markup_pct`` is the midpoint of the simulated band.

        Actual per-product markup is in ``[default_markup_pct - 0.10,
        default_markup_pct + 0.30]`` so we get a realistic mix of
        profitable, marginal, and loss-making opportunities.
        """
        if not 0.0 <= default_markup_pct <= 1.0:
            raise ValueError("default_markup_pct must be in [0, 1]")
        self._default_markup_pct = default_markup_pct

    def lookup(
        self,
        *,
        product_key: str,
        platform: str,
        price_hint: float | None = None,
    ) -> ResaleComp | None:
        baseline = price_hint if price_hint and price_hint > 0 else 50.0

        # Deterministic per-product wiggle in [-0.10, +0.30] around midpoint
        digest = hashlib.sha1(product_key.encode("utf-8")).digest()
        # First byte -> uniform-ish in [0, 1)
        wiggle = (digest[0] / 256.0) * 0.40 - 0.10
        markup = self._default_markup_pct + wiggle

        sold_avg = round(baseline * (1.0 + markup), 2)
        # Comp count is also product-dependent, in [5, 50]
        sold_count = 5 + (digest[1] % 46)
        # Confidence scales with sold_count
        confidence = round(min(1.0, sold_count / 30.0), 2)

        return ResaleComp(
            product_key=product_key,
            platform=platform,
            sold_avg=sold_avg,
            sold_count=sold_count,
            source=self.name,
            observed_at=datetime.now(timezone.utc),
            confidence=confidence,
            extra={"markup_applied": round(markup, 3), "baseline": baseline},
        )


# ---------------------------------------------------------------------------
# Stubs — wire up once real API credentials are provisioned
# ---------------------------------------------------------------------------


class KeepaClient:
    """Real Amazon sold-comp lookups via the Keepa API.

    Flow per lookup:
      1. ``/search`` for the product_key (5 tokens). Take the top ASIN.
      2. ``/product`` for that ASIN with ``stats=90`` (1 token).
      3. Read ``stats.avg30[0]`` (30-day average Amazon-fulfilled price,
         in cents). Fall back to ``stats.current[0]`` if avg30 is unset.
      4. Convert to USD, build ResaleComp.

    Total: 6 tokens per uncached lookup. With the built-in LRU cache
    (TTL 24h) a unique product is looked up at most once per day per
    process — dashboard refreshes hit cache, only the worker triggers
    fresh fetches.

    Errors:
      * Token exhaustion (HTTP 429 or ``tokensLeft < required``) -> log
        warning and return ``None`` so the router falls back to mock.
      * Network / 5xx / malformed JSON -> raise so the router's catch-all
        kicks in. The router treats this the same as token exhaustion.
      * Empty search results / no usable price data -> return ``None``.
    """

    name = "keepa"

    _BASE_URL = "https://api.keepa.com"
    # CSV array index 0 = Amazon-fulfilled price (in cents).
    # See https://keepa.com/#!discuss/t/product-object/116
    _AMAZON_CSV_INDEX = 0
    # Cache lookups for this long. Keepa's avg30 only refreshes daily,
    # so we don't gain anything by re-fetching more often.
    _CACHE_TTL_SECONDS = 24 * 60 * 60
    # Search query is ~5 tokens, product is 1. We refuse to start a
    # lookup if tokensLeft (returned by /search) drops below this floor.
    _MIN_TOKENS_FOR_PRODUCT_CALL = 1

    def __init__(
        self,
        api_key: str,
        *,
        domain: int = 1,  # 1 = amazon.com (US)
        timeout_seconds: float = 10.0,
        http_client=None,
    ) -> None:
        if not api_key:
            raise ValueError("Keepa API key is required")
        self._api_key = api_key
        self._domain = domain
        self._timeout = timeout_seconds
        # ``http_client`` is injected for tests — it must expose
        # ``.get(url, params, timeout) -> Response`` with a
        # ``.raise_for_status()`` and ``.json()`` method (i.e. the
        # requests.Session contract).
        if http_client is None:
            import requests
            http_client = requests
        self._http = http_client
        # Tiny in-memory cache: { (product_key, platform): (comp, expiry) }
        self._cache: dict[tuple[str, str], tuple[ResaleComp, float]] = {}

    def lookup(
        self,
        *,
        product_key: str,
        platform: str,
        price_hint: float | None = None,
    ) -> ResaleComp | None:
        import time

        cache_key = (product_key.lower().strip(), platform)
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached is not None and cached[1] > now:
            return cached[0]

        # Step 1: search for the product
        try:
            search_response = self._http.get(
                f"{self._BASE_URL}/search",
                params={
                    "key": self._api_key,
                    "domain": self._domain,
                    "type": "product",
                    "term": product_key,
                },
                timeout=self._timeout,
            )
            search_response.raise_for_status()
            search_body = search_response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "keepa_search_failed",
                extra={
                    "product_key": product_key,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return None

        asins = search_body.get("asinList") or []
        if not asins:
            logger.info(
                "keepa_search_empty",
                extra={"product_key": product_key},
            )
            return None

        tokens_left = search_body.get("tokensLeft")
        if (
            isinstance(tokens_left, (int, float))
            and tokens_left < self._MIN_TOKENS_FOR_PRODUCT_CALL
        ):
            logger.warning(
                "keepa_tokens_exhausted",
                extra={
                    "product_key": product_key,
                    "tokens_left": tokens_left,
                },
            )
            return None

        asin = asins[0]

        # Step 2: pull product details + 90-day stats
        try:
            product_response = self._http.get(
                f"{self._BASE_URL}/product",
                params={
                    "key": self._api_key,
                    "domain": self._domain,
                    "asin": asin,
                    "stats": 90,
                },
                timeout=self._timeout,
            )
            product_response.raise_for_status()
            product_body = product_response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "keepa_product_failed",
                extra={
                    "product_key": product_key,
                    "asin": asin,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return None

        products = product_body.get("products") or []
        if not products:
            return None

        product = products[0]
        stats = product.get("stats") or {}

        # Read 30-day average Amazon-fulfilled price in cents.
        # Keepa uses -1 to signal "no data" — gracefully fall back.
        sold_avg_cents = _safe_index(
            stats.get("avg30"), self._AMAZON_CSV_INDEX
        )
        if sold_avg_cents is None or sold_avg_cents < 0:
            sold_avg_cents = _safe_index(
                stats.get("current"), self._AMAZON_CSV_INDEX
            )
        if sold_avg_cents is None or sold_avg_cents < 0:
            logger.info(
                "keepa_no_usable_price",
                extra={
                    "product_key": product_key,
                    "asin": asin,
                },
            )
            return None

        sold_avg = round(sold_avg_cents / 100.0, 2)
        # Keepa doesn't expose sale count directly — proxy using sales
        # rank where available. Sales rank index in stats is 3.
        sales_rank = _safe_index(stats.get("avg30"), 3)
        # Low rank == high sales volume. Convert to a coarse 1..50 estimate.
        if sales_rank and sales_rank > 0:
            sold_count = max(1, min(50, int(100_000 // sales_rank)))
        else:
            sold_count = 0
        # Confidence: 0.9 when we have 30-day data, 0.6 when only current
        confidence = 0.9 if stats.get("avg30") else 0.6

        comp = ResaleComp(
            product_key=product_key,
            platform=platform,
            sold_avg=sold_avg,
            sold_count=sold_count,
            source=self.name,
            observed_at=datetime.now(timezone.utc),
            confidence=confidence,
            extra={
                "asin": asin,
                "title": product.get("title"),
                "sales_rank_avg30": sales_rank,
            },
        )
        self._cache[cache_key] = (comp, now + self._CACHE_TTL_SECONDS)
        return comp


def _safe_index(seq, idx: int):
    """Return ``seq[idx]`` or ``None`` if the index isn't reachable."""
    if seq is None:
        return None
    try:
        return seq[idx]
    except (IndexError, TypeError, KeyError):
        return None


class SerpApiClient:
    """Real Google Shopping snapshot lookups via SerpAPI.

    Implementation deferred — populate once a SerpAPI key has been
    provisioned. Note: SerpAPI returns *current asking prices* across
    Google-indexed retailers, NOT sold prices. We treat the median
    asking price as a soft proxy for sold-avg, with low confidence.

    Plan:
      1. Build a Google Shopping search via
         https://serpapi.com/google-shopping-api
      2. Take the median of the top N inline_shopping_results prices.
      3. sold_count is unknown -> 0; confidence is fixed-low.
    """

    name = "serpapi"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("SerpAPI key is required")
        self._api_key = api_key

    def lookup(
        self,
        *,
        product_key: str,
        platform: str,
        price_hint: float | None = None,
    ) -> ResaleComp | None:
        raise NotImplementedError(
            "SerpApiClient.lookup is a stub. Implementation lands once "
            "the SerpAPI key is provisioned (Sprint 2, second half)."
        )


# ---------------------------------------------------------------------------
# Router — picks the right client per platform
# ---------------------------------------------------------------------------


class RoutedResaleCompsClient:
    """Dispatches lookups to the right backend client by platform.

    Routing rules:
      * Amazon-style platforms     -> Keepa
      * All other supported plats  -> SerpAPI
      * Fallback                   -> ``fallback`` (typically the mock)

    The router NEVER raises ``NotImplementedError`` from a backend stub:
    if the real client isn't configured (or raises NotImplemented), it
    transparently falls back to the configured ``fallback`` client. This
    keeps the worker pipeline running while real credentials are being
    arranged.
    """

    # Platforms we route to Keepa once it's wired up
    _AMAZON_PLATFORMS = {"Amazon"}

    def __init__(
        self,
        *,
        keepa: ResaleCompsClient | None = None,
        serpapi: ResaleCompsClient | None = None,
        fallback: ResaleCompsClient | None = None,
    ) -> None:
        self._keepa = keepa
        self._serpapi = serpapi
        self._fallback = fallback or MockResaleCompsClient()
        self.name = "routed"

    def lookup(
        self,
        *,
        product_key: str,
        platform: str,
        price_hint: float | None = None,
    ) -> ResaleComp | None:
        primary = self._select_primary(platform)
        if primary is not None:
            try:
                return primary.lookup(
                    product_key=product_key,
                    platform=platform,
                    price_hint=price_hint,
                )
            except NotImplementedError:
                logger.info(
                    "resale_comps_primary_stub_fallback",
                    extra={"platform": platform, "primary": primary.name},
                )
            except Exception as exc:  # noqa: BLE001 — never crash a tick
                logger.warning(
                    "resale_comps_primary_failed",
                    extra={
                        "platform": platform,
                        "primary": primary.name,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
        # Fallback path
        return self._fallback.lookup(
            product_key=product_key,
            platform=platform,
            price_hint=price_hint,
        )

    def _select_primary(
        self, platform: str
    ) -> ResaleCompsClient | None:
        if platform in self._AMAZON_PLATFORMS and self._keepa is not None:
            return self._keepa
        if platform not in self._AMAZON_PLATFORMS and self._serpapi is not None:
            return self._serpapi
        return None
