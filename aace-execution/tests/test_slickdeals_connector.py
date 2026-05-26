"""Unit tests for the Slickdeals RSS connector.

Network is fully mocked — these run offline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.aace_execution.connectors.base import RawListing
from src.aace_execution.connectors.slickdeals import (
    SlickdealsConnector,
    _extract_price,
    _normalize_title,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Slickdeals - Frontpage</title>
    <link>https://slickdeals.net</link>
    <description>Frontpage deals</description>
    <item>
      <title>Apple MacBook Air 13" M3 8GB 256GB $799 + Free Shipping</title>
      <link>https://slickdeals.net/f/1234</link>
      <description>Great deal on MBA</description>
      <pubDate>Sun, 17 May 2026 14:00:00 GMT</pubDate>
      <guid isPermaLink="false">sd-1234</guid>
    </item>
    <item>
      <title>Sony WH-1000XM5 Headphones $278 (was $399)</title>
      <link>https://slickdeals.net/f/5678</link>
      <description>30% off</description>
      <pubDate>Sun, 17 May 2026 13:00:00 GMT</pubDate>
      <guid isPermaLink="false">sd-5678</guid>
    </item>
    <item>
      <title>Free Sample of Kraft Mac and Cheese</title>
      <link>https://slickdeals.net/f/9999</link>
      <description>Freebie</description>
      <pubDate>Sun, 17 May 2026 12:00:00 GMT</pubDate>
      <guid isPermaLink="false">sd-9999</guid>
    </item>
    <item>
      <title>LG OLED C3 65" 4K TV $1,299.99 at Best Buy</title>
      <link>https://slickdeals.net/f/4242</link>
      <description>Big screen, bigger discount</description>
      <pubDate>Sun, 17 May 2026 11:00:00 GMT</pubDate>
      <guid isPermaLink="false">sd-4242</guid>
    </item>
  </channel>
</rss>
"""


def _stub_http_client(text: str):
    """Build a stand-in for an ``httpx.Client``."""
    resp = MagicMock()
    resp.text = text
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = MagicMock(return_value=resp)
    return client


# ---------------------------------------------------------------------------
# fetch()
# ---------------------------------------------------------------------------


class TestFetch:
    def test_fetch_returns_one_raw_listing_per_feed_item(self):
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        assert len(raws) == 4

    def test_fetch_sets_source_to_slickdeals(self):
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        assert all(r.source == "slickdeals" for r in raws)

    def test_fetch_captures_external_id_from_guid(self):
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        ids = {r.source_external_id for r in raws}
        assert ids == {"sd-1234", "sd-5678", "sd-9999", "sd-4242"}

    def test_fetch_captures_title_and_url(self):
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        macbook = next(r for r in raws if "MacBook" in r.title)
        assert macbook.url == "https://slickdeals.net/f/1234"
        assert "$799" in macbook.title

    def test_fetch_uses_now_for_fetched_at(self):
        """Connectors are free to use wall-clock time (unlike pipeline workers)."""
        before = datetime.now(timezone.utc)
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        after = datetime.now(timezone.utc)
        assert all(before <= r.fetched_at <= after for r in raws)


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_normalize_extracts_simple_price(self):
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        macbook = next(r for r in raws if "MacBook" in r.title)
        norm = conn.normalize(macbook)
        assert norm is not None
        assert norm.price == 799.0
        assert norm.currency == "USD"

    def test_normalize_extracts_price_with_thousands_separator(self):
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        tv = next(r for r in raws if "OLED" in r.title)
        norm = conn.normalize(tv)
        assert norm is not None
        assert norm.price == 1299.99

    def test_normalize_takes_first_price_when_multiple_present(self):
        """'$278 (was $399)' → 278, not 399."""
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        headphones = next(r for r in raws if "Sony" in r.title)
        norm = conn.normalize(headphones)
        assert norm is not None
        assert norm.price == 278.0

    def test_normalize_skips_items_without_price(self):
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        freebie = next(r for r in raws if "Free Sample" in r.title)
        assert conn.normalize(freebie) is None

    def test_normalize_builds_source_prefixed_listing_id(self):
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        macbook = next(r for r in raws if "MacBook" in r.title)
        norm = conn.normalize(macbook)
        assert norm is not None
        assert norm.listing_id == "slickdeals:sd-1234"

    def test_normalize_produces_lowercase_product_key(self):
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        macbook = next(r for r in raws if "MacBook" in r.title)
        norm = conn.normalize(macbook)
        assert norm is not None
        assert "apple macbook air" in norm.product_key
        assert norm.product_key == norm.product_key.lower()

    def test_normalize_preserves_raw_payload_in_extra(self):
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        macbook = next(r for r in raws if "MacBook" in r.title)
        norm = conn.normalize(macbook)
        assert norm is not None
        assert norm.extra["raw"]["guid"] == "sd-1234"


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


class TestRunEndToEnd:
    def test_run_returns_only_priced_items(self):
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        items = conn.run()
        # 4 items in feed, 1 is the no-price freebie → 3 normalized
        assert len(items) == 3
        assert all(item.price > 0 for item in items)

    def test_run_is_idempotent_when_feed_unchanged(self):
        conn = SlickdealsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        first = {item.listing_id for item in conn.run()}
        second = {item.listing_id for item in conn.run()}
        assert first == second


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestExtractPrice:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("MacBook $799", 799.0),
            ("MacBook $799 + Free Shipping", 799.0),
            ("MacBook $1,299", 1299.0),
            ("MacBook $1,299.99", 1299.99),
            ("Headphones $278 (was $399)", 278.0),
            ("$ 49.99 deal", 49.99),
            ("Free thing", None),
            ("", None),
            ("no dollar sign mentioned", None),
        ],
    )
    def test_price_extraction(self, text, expected):
        assert _extract_price(text) == expected


class TestNormalizeTitle:
    def test_lowercases_and_strips_symbols(self):
        assert _normalize_title("Apple MacBook Air 13\" M3") == "apple macbook air 13 m3"

    def test_collapses_whitespace_and_punctuation(self):
        assert _normalize_title("Sony   WH-1000XM5!!") == "sony wh 1000xm5"

    def test_empty_string_yields_empty(self):
        assert _normalize_title("") == ""

    def test_only_symbols_yields_empty(self):
        assert _normalize_title("---") == ""
