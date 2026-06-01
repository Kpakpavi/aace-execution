"""Unit tests for the TechBargains RSS connector. Network mocked."""

from __future__ import annotations

from unittest.mock import MagicMock

from aace_execution.connectors.techbargains import TechBargainsConnector


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>TechBargains</title>
    <link>https://www.techbargains.com</link>
    <description>Hot tech deals</description>
    <item>
      <title>Apple AirPods Pro 2 USB-C $169 + Free Shipping</title>
      <link>https://www.techbargains.com/deal/airpods-pro-2</link>
      <description>Best price we've seen.</description>
      <pubDate>Wed, 28 May 2026 14:00:00 GMT</pubDate>
      <guid isPermaLink="false">tb-1</guid>
    </item>
    <item>
      <title>Dell XPS 13 Laptop Core i7 $1,099 at Dell</title>
      <link>https://www.techbargains.com/deal/dell-xps-13</link>
      <description>$300 off MSRP.</description>
      <pubDate>Wed, 28 May 2026 13:00:00 GMT</pubDate>
      <guid isPermaLink="false">tb-2</guid>
    </item>
    <item>
      <title>Free shipping all month at Newegg</title>
      <link>https://www.techbargains.com/deal/newegg-free-shipping</link>
      <description>Site-wide promo, no specific price.</description>
      <pubDate>Wed, 28 May 2026 12:00:00 GMT</pubDate>
      <guid isPermaLink="false">tb-3</guid>
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
    def test_returns_one_listing_per_item(self):
        conn = TechBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        assert len(raws) == 3

    def test_sets_source_to_techbargains(self):
        conn = TechBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        assert all(r.source == "techbargains" for r in raws)

    def test_captures_guid_as_external_id(self):
        conn = TechBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        ids = {r.source_external_id for r in raws}
        assert ids == {"tb-1", "tb-2", "tb-3"}


class TestNormalize:
    def test_extracts_price_from_title(self):
        conn = TechBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        airpods = next(r for r in raws if "AirPods" in r.title)
        norm = conn.normalize(airpods)
        assert norm is not None
        assert norm.price == 169.0

    def test_extracts_thousands_separator(self):
        conn = TechBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        dell = next(r for r in raws if "Dell" in r.title)
        norm = conn.normalize(dell)
        assert norm is not None
        assert norm.price == 1099.0

    def test_skips_items_without_price(self):
        conn = TechBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        promo = next(r for r in raws if "Free shipping" in r.title)
        assert conn.normalize(promo) is None

    def test_builds_source_prefixed_listing_id(self):
        conn = TechBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        raws = conn.fetch()
        airpods = next(r for r in raws if "AirPods" in r.title)
        norm = conn.normalize(airpods)
        assert norm is not None
        assert norm.listing_id == "techbargains:tb-1"


class TestRunEndToEnd:
    def test_run_returns_only_priced_items(self):
        conn = TechBargainsConnector(http_client=_stub_http_client(SAMPLE_FEED))
        items = conn.run()
        assert len(items) == 2  # airpods + dell; promo dropped
        assert all(item.price > 0 for item in items)
