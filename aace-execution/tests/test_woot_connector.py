"""Unit tests for the Woot RSS connector.

Network is fully mocked — these run offline. Fixture mirrors the real
Woot RSS feed shape: price sometimes in the title, sometimes only in
the summary, occasional entries without parseable prices.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aace_execution.connectors.base import ConnectorError
from aace_execution.connectors.woot import WootConnector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Matches the real Woot RSS shape: price often appears in the title for
# main offers, but for some "woot-off" entries the title is bare and
# price lives in the summary/description.
SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Woot! - Deals</title>
    <link>https://www.woot.com</link>
    <description>Daily deals from Woot</description>
    <item>
      <title>Refurb iPad mini 6 256GB Wi-Fi $389</title>
      <link>https://www.woot.com/offers/refurb-ipad-mini-6</link>
      <description>One day only</description>
      <pubDate>Mon, 08 Jun 2026 14:00:00 GMT</pubDate>
      <guid isPermaLink="false">woot-7001</guid>
    </item>
    <item>
      <title>Apple Watch Series 11 GPS 45mm</title>
      <link>https://www.woot.com/offers/apple-watch-series-11</link>
      <description><![CDATA[<p>$329 from Woot today</p>]]></description>
      <pubDate>Mon, 08 Jun 2026 13:00:00 GMT</pubDate>
      <guid isPermaLink="false">woot-7002</guid>
    </item>
    <item>
      <title>Mystery Bag of Wires</title>
      <link>https://www.woot.com/offers/mystery-bag</link>
      <description>You'll see when it arrives</description>
      <pubDate>Mon, 08 Jun 2026 12:00:00 GMT</pubDate>
      <guid isPermaLink="false">woot-7003</guid>
    </item>
    <item>
      <title>Bose QuietComfort Ultra Headphones $329.99 (refurb)</title>
      <link>https://www.woot.com/offers/bose-qc-ultra</link>
      <description>Amazon-fulfilled refurbs</description>
      <pubDate>Mon, 08 Jun 2026 11:00:00 GMT</pubDate>
      <guid isPermaLink="false">woot-7004</guid>
    </item>
  </channel>
</rss>
"""


def _stub_http_client(text: str):
    """Build a stand-in for an httpx.Client returning the fixture body."""
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
        conn = WootConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        assert len(raw) == 4
        ids = [r.source_external_id for r in raw]
        assert ids == ["woot-7001", "woot-7002", "woot-7003", "woot-7004"]

    def test_fetch_carries_title_link_summary(self):
        conn = WootConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        first = raw[0]
        assert first.source == "woot"
        assert "iPad" in first.title
        assert first.url.endswith("/refurb-ipad-mini-6")
        assert first.raw_payload["guid"] == "woot-7001"

    def test_unparseable_feed_raises_connector_error(self, monkeypatch):
        # The connector raises ConnectorError when feedparser reports
        # bozo=1 AND zero entries. We patch feedparser.parse directly
        # so the test verifies the conditional rather than depending on
        # feedparser's (very forgiving) version-specific behavior.
        import feedparser

        bad_feed = type("Feed", (), {})()
        bad_feed.bozo = 1
        bad_feed.entries = []

        monkeypatch.setattr(feedparser, "parse", lambda text: bad_feed)

        conn = WootConnector(http_client=_stub_http_client("anything"))
        with pytest.raises(ConnectorError):
            conn.fetch()

    def test_empty_feed_body_returns_no_listings(self):
        # Empty body: feedparser treats it as "no items" without flagging
        # bozo. The connector should gracefully return an empty list —
        # an empty feed isn't an error, it's just "no deals right now."
        conn = WootConnector(http_client=_stub_http_client(""))
        raw = conn.fetch()
        assert raw == []

    def test_http_error_raises_connector_error(self):
        # Stub raises on .raise_for_status()
        client = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = RuntimeError("HTTP 503")
        client.get.return_value = resp
        conn = WootConnector(http_client=client)
        with pytest.raises(Exception):
            conn.fetch()


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_normalize_extracts_price_from_title(self):
        conn = WootConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        # iPad item: $389 in title
        norm = conn.normalize(raw[0])
        assert norm is not None
        assert norm.price == 389.0
        assert norm.source == "woot"
        assert norm.currency == "USD"
        assert "ipad" in norm.product_key

    def test_normalize_falls_back_to_summary_for_price(self):
        # Apple Watch item: price only in summary, not title
        conn = WootConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        norm = conn.normalize(raw[1])
        assert norm is not None
        assert norm.price == 329.0
        assert "apple" in norm.product_key
        assert "watch" in norm.product_key

    def test_normalize_skips_items_with_no_price(self):
        conn = WootConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        # Mystery bag has no parseable price anywhere
        assert conn.normalize(raw[2]) is None

    def test_normalize_handles_comma_separated_prices(self):
        # Synthesize a high-priced item like a TV ("$1,299.99")
        from aace_execution.connectors.base import RawListing
        from datetime import datetime, timezone

        raw = RawListing(
            source="woot",
            source_external_id="woot-bigtv",
            title='Sony 75" OLED Bravia $1,299.99',
            url="https://www.woot.com/offers/sony-bravia",
            raw_payload={"summary": ""},
            fetched_at=datetime.now(timezone.utc),
        )
        conn = WootConnector(http_client=_stub_http_client(""))
        norm = conn.normalize(raw)
        assert norm is not None
        assert norm.price == 1299.99


# ---------------------------------------------------------------------------
# Full run()
# ---------------------------------------------------------------------------


class TestRun:
    def test_run_returns_three_normalized_listings_skips_freebie(self):
        # 4 feed items, 3 have parseable prices -> 3 normalized listings.
        conn = WootConnector(http_client=_stub_http_client(SAMPLE_FEED))
        out = conn.run()
        assert len(out) == 3
        prices = sorted(item.price for item in out)
        assert prices == [329.0, 329.99, 389.0]
