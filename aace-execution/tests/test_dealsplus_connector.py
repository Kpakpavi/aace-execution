"""Unit tests for the DealsPlus RSS connector.

Network is fully mocked — these run offline. Fixture mirrors the real
DealsPlus feed: community submissions, freebies without prices,
varying title formats.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aace_execution.connectors.base import ConnectorError
from aace_execution.connectors.dealsplus import DealsPlusConnector


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>DealsPlus - Frontpage</title>
    <link>https://www.dealsplus.com</link>
    <description>Community-curated deals</description>
    <item>
      <title>iRobot Roomba J7+ Self-Empty Robot Vacuum $449 + Free Shipping</title>
      <link>https://www.dealsplus.com/d/12001</link>
      <description>Big drop on a Roomba</description>
      <pubDate>Mon, 09 Jun 2026 15:00:00 GMT</pubDate>
      <guid isPermaLink="false">dp-12001</guid>
    </item>
    <item>
      <title>Free Coffee Sample from Brand X</title>
      <link>https://www.dealsplus.com/d/12002</link>
      <description>Submit form</description>
      <pubDate>Mon, 09 Jun 2026 14:30:00 GMT</pubDate>
      <guid isPermaLink="false">dp-12002</guid>
    </item>
    <item>
      <title>Nintendo Switch OLED + Mario Bundle $299.99 at Target</title>
      <link>https://www.dealsplus.com/d/12003</link>
      <description>Bundle deal</description>
      <pubDate>Mon, 09 Jun 2026 14:00:00 GMT</pubDate>
      <guid isPermaLink="false">dp-12003</guid>
    </item>
    <item>
      <title>Samsung 1TB SSD T7 Portable</title>
      <link>https://www.dealsplus.com/d/12004</link>
      <description><![CDATA[<p>Listed at $79.99 with free shipping</p>]]></description>
      <pubDate>Mon, 09 Jun 2026 13:00:00 GMT</pubDate>
      <guid isPermaLink="false">dp-12004</guid>
    </item>
    <item>
      <title>HP OfficeJet Pro Printer $129.95 + 200 free pages</title>
      <link>https://www.dealsplus.com/d/12005</link>
      <description>Office bundle</description>
      <pubDate>Mon, 09 Jun 2026 12:00:00 GMT</pubDate>
      <guid isPermaLink="false">dp-12005</guid>
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
        conn = DealsPlusConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        assert len(raw) == 5
        ids = [r.source_external_id for r in raw]
        assert ids == [
            "dp-12001", "dp-12002", "dp-12003", "dp-12004", "dp-12005",
        ]

    def test_fetch_sets_source_to_dealsplus(self):
        conn = DealsPlusConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        assert all(r.source == "dealsplus" for r in raw)

    def test_fetch_captures_title_and_url(self):
        conn = DealsPlusConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        assert "Roomba" in raw[0].title
        assert raw[0].url.endswith("/d/12001")

    def test_unparseable_feed_raises_connector_error(self, monkeypatch):
        import feedparser
        bad_feed = type("Feed", (), {})()
        bad_feed.bozo = 1
        bad_feed.entries = []
        monkeypatch.setattr(feedparser, "parse", lambda text: bad_feed)
        conn = DealsPlusConnector(http_client=_stub_http_client("anything"))
        with pytest.raises(ConnectorError):
            conn.fetch()

    def test_empty_feed_body_returns_no_listings(self):
        conn = DealsPlusConnector(http_client=_stub_http_client(""))
        raw = conn.fetch()
        assert raw == []

    def test_http_error_raises(self):
        client = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = RuntimeError("HTTP 503")
        client.get.return_value = resp
        conn = DealsPlusConnector(http_client=client)
        with pytest.raises(Exception):
            conn.fetch()


class TestNormalize:
    def test_normalize_extracts_simple_price(self):
        conn = DealsPlusConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        norm = conn.normalize(raw[0])  # Roomba $449
        assert norm is not None
        assert norm.price == 449.0
        assert norm.source == "dealsplus"

    def test_normalize_extracts_decimal_price(self):
        conn = DealsPlusConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        norm = conn.normalize(raw[2])  # Switch $299.99
        assert norm is not None
        assert norm.price == 299.99

    def test_normalize_skips_freebies(self):
        # "Free Coffee Sample" — no price anywhere
        conn = DealsPlusConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        assert conn.normalize(raw[1]) is None

    def test_normalize_falls_back_to_summary_for_price(self):
        # Samsung SSD: title has no $, summary has $79.99
        conn = DealsPlusConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        norm = conn.normalize(raw[3])
        assert norm is not None
        assert norm.price == 79.99

    def test_normalize_takes_first_price_when_multiple_present(self):
        # HP Printer: "$129.95 + 200 free pages" — "200" must not be
        # mistaken for a price; first $-sign wins.
        conn = DealsPlusConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raw = conn.fetch()
        norm = conn.normalize(raw[4])
        assert norm is not None
        assert norm.price == 129.95


class TestRunEndToEnd:
    def test_run_returns_only_priced_items(self):
        # 5 feed items, 4 priced, 1 freebie skipped
        conn = DealsPlusConnector(http_client=_stub_http_client(SAMPLE_FEED))
        out = conn.run()
        assert len(out) == 4
        prices = sorted(item.price for item in out)
        assert prices == [79.99, 129.95, 299.99, 449.0]

    def test_run_listing_ids_are_source_prefixed(self):
        conn = DealsPlusConnector(http_client=_stub_http_client(SAMPLE_FEED))
        out = conn.run()
        assert all(item.listing_id.startswith("dealsplus:") for item in out)
