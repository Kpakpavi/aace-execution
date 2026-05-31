"""Unit tests for the Ben's Bargains RSS connector. Network mocked."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from aace_execution.connectors.bensbargains import BensBargainsConnector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Ben's Bargains - Latest Headlines</title>
    <link>https://bensbargains.com</link>
    <description>Curated deals from Ben's Bargains</description>
    <item>
      <title>Apple AirPods Pro 2 USB-C $169 + Free Shipping</title>
      <link>https://bensbargains.com/deal/apple-airpods-pro-2-usbc</link>
      <description>Lowest price we've tracked.</description>
      <pubDate>Wed, 28 May 2026 14:00:00 GMT</pubDate>
      <guid isPermaLink="false">bb-airpods-1</guid>
    </item>
    <item>
      <title>Anker 737 Power Bank 24,000mAh $89.99 at Amazon</title>
      <link>https://bensbargains.com/deal/anker-737</link>
      <description>30% off list price.</description>
      <pubDate>Wed, 28 May 2026 13:00:00 GMT</pubDate>
      <guid isPermaLink="false">bb-anker-1</guid>
    </item>
    <item>
      <title>Free Trial of Disney+ for 7 Days</title>
      <link>https://bensbargains.com/deal/disney-trial</link>
      <description>No purchase required.</description>
      <pubDate>Wed, 28 May 2026 12:00:00 GMT</pubDate>
      <guid isPermaLink="false">bb-disney-1</guid>
    </item>
    <item>
      <title>Logitech MX Master 3S Wireless Mouse</title>
      <link>https://bensbargains.com/deal/logitech-mx</link>
      <description>Only $79.99 at Best Buy. Save $20.</description>
      <pubDate>Wed, 28 May 2026 11:00:00 GMT</pubDate>
      <guid isPermaLink="false">bb-logi-1</guid>
    </item>
    <item>
      <title>LG OLED C3 65" 4K TV $1,299.99 at Costco</title>
      <link>https://bensbargains.com/deal/lg-c3</link>
      <description>Best price ever seen on this set.</description>
      <pubDate>Wed, 28 May 2026 10:00:00 GMT</pubDate>
      <guid isPermaLink="false">bb-lg-1</guid>
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
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        assert len(raws) == 5

    def test_fetch_sets_source_to_bensbargains(self):
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        assert all(r.source == "bensbargains" for r in raws)

    def test_fetch_captures_external_id_from_guid(self):
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        ids = {r.source_external_id for r in raws}
        assert ids == {
            "bb-airpods-1",
            "bb-anker-1",
            "bb-disney-1",
            "bb-logi-1",
            "bb-lg-1",
        }

    def test_fetch_captures_title_and_url(self):
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        airpods = next(r for r in raws if "AirPods" in r.title)
        assert airpods.url == "https://bensbargains.com/deal/apple-airpods-pro-2-usbc"

    def test_fetch_uses_now_for_fetched_at(self):
        before = datetime.now(timezone.utc)
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        after = datetime.now(timezone.utc)
        assert all(before <= r.fetched_at <= after for r in raws)


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_normalize_extracts_price_from_title(self):
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        airpods = next(r for r in raws if "AirPods" in r.title)
        norm = conn.normalize(airpods)
        assert norm is not None
        assert norm.price == 169.0
        assert norm.currency == "USD"

    def test_normalize_extracts_price_with_thousands_separator(self):
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        tv = next(r for r in raws if "OLED" in r.title)
        norm = conn.normalize(tv)
        assert norm is not None
        assert norm.price == 1299.99

    def test_normalize_falls_back_to_summary_when_title_lacks_price(self):
        """Some items have price in description (e.g. Logitech here)."""
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        mouse = next(r for r in raws if "Logitech" in r.title)
        norm = conn.normalize(mouse)
        assert norm is not None
        assert norm.price == 79.99

    def test_normalize_skips_items_without_price_anywhere(self):
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        free_trial = next(r for r in raws if "Free Trial" in r.title)
        assert conn.normalize(free_trial) is None

    def test_normalize_builds_source_prefixed_listing_id(self):
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        airpods = next(r for r in raws if "AirPods" in r.title)
        norm = conn.normalize(airpods)
        assert norm is not None
        assert norm.listing_id == "bensbargains:bb-airpods-1"

    def test_normalize_produces_lowercase_product_key(self):
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        airpods = next(r for r in raws if "AirPods" in r.title)
        norm = conn.normalize(airpods)
        assert norm is not None
        assert "apple airpods pro" in norm.product_key
        assert norm.product_key == norm.product_key.lower()


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


class TestRunEndToEnd:
    def test_run_returns_only_priced_items(self):
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        items = conn.run()
        # 5 items: 4 priced (airpods, anker, logitech via desc, lg) + 1 free trial
        assert len(items) == 4
        assert all(item.price > 0 for item in items)

    def test_run_is_idempotent_when_feed_unchanged(self):
        conn = BensBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        first = {item.listing_id for item in conn.run()}
        second = {item.listing_id for item in conn.run()}
        assert first == second
