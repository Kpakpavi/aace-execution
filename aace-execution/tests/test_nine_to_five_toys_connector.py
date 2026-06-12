"""Unit tests for the 9to5Toys RSS connector.

Network is fully mocked — these run offline. Fixture mirrors the real
9to5Toys feed shape: editorial titles with prices, occasional roundup
posts without prices in the title, items with comma-separated prices.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aace_execution.connectors.base import ConnectorError
from aace_execution.connectors.nine_to_five_toys import NineToFiveToysConnector


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>9to5Toys</title>
    <link>https://9to5toys.com</link>
    <description>Daily deals on Apple gear and tech</description>
    <item>
      <title>Apple Watch Series 11 41mm GPS hits new low at $329 shipped</title>
      <link>https://9to5toys.com/apple-watch-series-11-329</link>
      <description>Best price yet</description>
      <pubDate>Mon, 09 Jun 2026 14:00:00 GMT</pubDate>
      <guid isPermaLink="false">9to5-100101</guid>
    </item>
    <item>
      <title>Sony WH-1000XM6 Wireless Headphones $328 (Reg. $399)</title>
      <link>https://9to5toys.com/sony-wh-1000xm6</link>
      <description>Flagship noise-canceling</description>
      <pubDate>Mon, 09 Jun 2026 13:00:00 GMT</pubDate>
      <guid isPermaLink="false">9to5-100102</guid>
    </item>
    <item>
      <title>Today's best deals roundup</title>
      <link>https://9to5toys.com/roundup</link>
      <description><![CDATA[<p>Includes deal at $49.99 today</p>]]></description>
      <pubDate>Mon, 09 Jun 2026 12:00:00 GMT</pubDate>
      <guid isPermaLink="false">9to5-100103</guid>
    </item>
    <item>
      <title>LG 65" OLED C4 4K TV $1,499.99 at Best Buy</title>
      <link>https://9to5toys.com/lg-oled-c4-65</link>
      <description>Massive savings</description>
      <pubDate>Mon, 09 Jun 2026 11:00:00 GMT</pubDate>
      <guid isPermaLink="false">9to5-100104</guid>
    </item>
    <item>
      <title>Coming soon: spring sales preview</title>
      <link>https://9to5toys.com/spring-preview</link>
      <description>No prices yet</description>
      <pubDate>Mon, 09 Jun 2026 10:00:00 GMT</pubDate>
      <guid isPermaLink="false">9to5-100105</guid>
    </item>
  </channel>
</rss>
"""


def _stub_http_client(text: str):
    resp = MagicMock()
    resp.text = text
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = MagicMock(return_value=resp)
    return client


class TestFetch:
    def test_fetch_returns_one_raw_listing_per_feed_item(self):
        conn = NineToFiveToysConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        assert len(raw) == 5
        ids = [r.source_external_id for r in raw]
        assert ids == [
            "9to5-100101", "9to5-100102", "9to5-100103",
            "9to5-100104", "9to5-100105",
        ]

    def test_fetch_sets_source_to_9to5toys(self):
        conn = NineToFiveToysConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        assert all(r.source == "9to5toys" for r in raw)

    def test_fetch_captures_title_and_url(self):
        conn = NineToFiveToysConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        assert "Apple Watch" in raw[0].title
        assert raw[0].url.endswith("/apple-watch-series-11-329")

    def test_unparseable_feed_raises_connector_error(self, monkeypatch):
        import feedparser
        bad_feed = type("Feed", (), {})()
        bad_feed.bozo = 1
        bad_feed.entries = []
        monkeypatch.setattr(feedparser, "parse", lambda text: bad_feed)
        conn = NineToFiveToysConnector(http_client=_stub_http_client("anything"))
        with pytest.raises(ConnectorError):
            conn.fetch()

    def test_empty_feed_body_returns_no_listings(self):
        conn = NineToFiveToysConnector(http_client=_stub_http_client(""))
        raw = conn.fetch()
        assert raw == []

    def test_http_error_raises(self):
        client = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = RuntimeError("HTTP 503")
        client.get.return_value = resp
        conn = NineToFiveToysConnector(http_client=client)
        with pytest.raises(Exception):
            conn.fetch()


class TestNormalize:
    def test_normalize_extracts_price_from_title(self):
        conn = NineToFiveToysConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        # Apple Watch: $329 in title
        norm = conn.normalize(raw[0])
        assert norm is not None
        assert norm.price == 329.0
        assert norm.source == "9to5toys"

    def test_normalize_extracts_decimal_price(self):
        conn = NineToFiveToysConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        # LG TV: $1,499.99 - tests comma separator + decimal
        norm = conn.normalize(raw[3])
        assert norm is not None
        assert norm.price == 1499.99

    def test_normalize_falls_back_to_summary_for_price(self):
        # Roundup post: no price in title, $49.99 in summary
        conn = NineToFiveToysConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        norm = conn.normalize(raw[2])
        assert norm is not None
        assert norm.price == 49.99

    def test_normalize_skips_items_with_no_price_anywhere(self):
        # "Coming soon" post: no price in title or summary
        conn = NineToFiveToysConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        assert conn.normalize(raw[4]) is None

    def test_normalize_takes_first_price_when_was_present(self):
        # Sony headphones: "$328 (Reg. $399)" -> should take $328
        conn = NineToFiveToysConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        norm = conn.normalize(raw[1])
        assert norm is not None
        assert norm.price == 328.0


class TestRunEndToEnd:
    def test_run_returns_only_priced_items(self):
        # 5 feed items, 4 have parseable prices (including summary
        # fallback for the roundup), 1 ("Coming soon") is skipped.
        conn = NineToFiveToysConnector(http_client=_stub_http_client(SAMPLE_FEED))
        out = conn.run()
        assert len(out) == 4
        prices = sorted(item.price for item in out)
        assert prices == [49.99, 328.0, 329.0, 1499.99]

    def test_run_listing_ids_are_source_prefixed(self):
        conn = NineToFiveToysConnector(http_client=_stub_http_client(SAMPLE_FEED))
        out = conn.run()
        assert all(item.listing_id.startswith("9to5toys:") for item in out)
