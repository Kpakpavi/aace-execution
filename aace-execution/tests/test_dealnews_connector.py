"""Unit tests for the DealNews RSS connector. Network mocked."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from aace_execution.connectors.dealnews import DealNewsConnector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>DealNews - Top Deals</title>
    <link>https://www.dealnews.com</link>
    <description>Top deals on DealNews</description>
    <item>
      <title>Apple MacBook Air 13" M3 8GB 256GB for $799 + free shipping</title>
      <link>https://www.dealnews.com/products/Apple/example-1</link>
      <description>Apple at example.com offers it for $799 with free shipping.</description>
      <pubDate>Mon, 25 May 2026 14:00:00 GMT</pubDate>
      <guid isPermaLink="false">dn-aaaa</guid>
    </item>
    <item>
      <title>Sony WH-1000XM5 Headphones for $278 (was $399)</title>
      <link>https://www.dealnews.com/products/Sony/example-2</link>
      <description>Save 30% off list.</description>
      <pubDate>Mon, 25 May 2026 13:00:00 GMT</pubDate>
      <guid isPermaLink="false">dn-bbbb</guid>
    </item>
    <item>
      <title>Pictek RGB Gaming Mouse</title>
      <link>https://www.dealnews.com/products/Pictek/example-3</link>
      <description>Pictek offers it for $9.99 with code SAVE20.</description>
      <pubDate>Mon, 25 May 2026 12:00:00 GMT</pubDate>
      <guid isPermaLink="false">dn-cccc</guid>
    </item>
    <item>
      <title>Enter to win a free 4K TV</title>
      <link>https://www.dealnews.com/products/Contest/example-4</link>
      <description>No purchase necessary.</description>
      <pubDate>Mon, 25 May 2026 11:00:00 GMT</pubDate>
      <guid isPermaLink="false">dn-dddd</guid>
    </item>
    <item>
      <title>LG OLED C3 65" 4K TV $1,299.99 at Best Buy</title>
      <link>https://www.dealnews.com/products/LG/example-5</link>
      <description>Best Buy offers it for $1,299.99.</description>
      <pubDate>Mon, 25 May 2026 10:00:00 GMT</pubDate>
      <guid isPermaLink="false">dn-eeee</guid>
    </item>
  </channel>
</rss>
"""


def _stub_http_client(text: str):
    """Stand-in for an ``httpx.Client`` returning RSS text."""
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
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        assert len(raws) == 5

    def test_fetch_sets_source_to_dealnews(self):
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        assert all(r.source == "dealnews" for r in raws)

    def test_fetch_captures_external_id_from_guid(self):
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        ids = {r.source_external_id for r in raws}
        assert ids == {"dn-aaaa", "dn-bbbb", "dn-cccc", "dn-dddd", "dn-eeee"}

    def test_fetch_captures_title_and_url(self):
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        macbook = next(r for r in raws if "MacBook" in r.title)
        assert macbook.url == "https://www.dealnews.com/products/Apple/example-1"

    def test_fetch_captures_description_in_raw_payload(self):
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        mouse = next(r for r in raws if "Mouse" in r.title)
        assert "Pictek" in mouse.raw_payload["summary"]
        assert "$9.99" in mouse.raw_payload["summary"]

    def test_fetch_uses_now_for_fetched_at(self):
        before = datetime.now(timezone.utc)
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        after = datetime.now(timezone.utc)
        assert all(before <= r.fetched_at <= after for r in raws)


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_normalize_extracts_price_from_title(self):
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        macbook = next(r for r in raws if "MacBook" in r.title)
        norm = conn.normalize(macbook)
        assert norm is not None
        assert norm.price == 799.0
        assert norm.currency == "USD"

    def test_normalize_extracts_thousands_separator(self):
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        tv = next(r for r in raws if "OLED" in r.title)
        norm = conn.normalize(tv)
        assert norm is not None
        assert norm.price == 1299.99

    def test_normalize_takes_first_price_when_was_present(self):
        """'$278 (was $399)' -> 278, not 399."""
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        headphones = next(r for r in raws if "Sony" in r.title)
        norm = conn.normalize(headphones)
        assert norm is not None
        assert norm.price == 278.0

    def test_normalize_falls_back_to_summary_when_title_has_no_price(self):
        """Title says 'Pictek RGB Gaming Mouse'; price lives in <description>."""
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        mouse = next(r for r in raws if "Mouse" in r.title)
        norm = conn.normalize(mouse)
        assert norm is not None
        assert norm.price == 9.99

    def test_normalize_skips_items_without_price_anywhere(self):
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        contest = next(r for r in raws if "Enter to win" in r.title)
        assert conn.normalize(contest) is None

    def test_normalize_builds_source_prefixed_listing_id(self):
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        macbook = next(r for r in raws if "MacBook" in r.title)
        norm = conn.normalize(macbook)
        assert norm is not None
        assert norm.listing_id == "dealnews:dn-aaaa"

    def test_normalize_produces_lowercase_product_key(self):
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        macbook = next(r for r in raws if "MacBook" in r.title)
        norm = conn.normalize(macbook)
        assert norm is not None
        assert norm.product_key == norm.product_key.lower()
        assert "apple macbook air" in norm.product_key


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


class TestRunEndToEnd:
    def test_run_returns_only_priced_items(self):
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        items = conn.run()
        # 5 items, 1 is the no-price contest -> 4 normalized
        assert len(items) == 4
        assert all(item.price > 0 for item in items)

    def test_run_is_idempotent_when_feed_unchanged(self):
        conn = DealNewsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        first = {item.listing_id for item in conn.run()}
        second = {item.listing_id for item in conn.run()}
        assert first == second

    def test_run_cross_source_overlap_with_slickdeals(self):
        """Sanity check: DealNews and Slickdeals normalize the same product
        title to the same product_key. This is what makes cross-source
        matching possible at Day 3.
        """
        from aace_execution.connectors._helpers import _normalize_title

        sd_title = 'Apple MacBook Air 13" M3 8GB 256GB $799 + Free Shipping'
        dn_title = 'Apple MacBook Air 13" M3 8GB 256GB for $799 + free shipping'
        assert _normalize_title(sd_title)[:25] == _normalize_title(dn_title)[:25]
