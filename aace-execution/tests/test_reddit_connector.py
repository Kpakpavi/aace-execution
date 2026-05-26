"""Unit tests for the Reddit public-JSON connector.

Network is fully mocked — these run offline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from aace_execution.connectors.base import ConnectorError
from aace_execution.connectors.reddit import (
    DEFAULT_SUBS,
    RedditConnector,
    _extract_children,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PAYLOAD: dict = {
    "kind": "Listing",
    "data": {
        "after": "t3_xyz",
        "before": None,
        "children": [
            {
                "kind": "t3",
                "data": {
                    "id": "abc111",
                    "subreddit": "buildapcsales",
                    "title": "[SSD] Samsung 990 Pro 2TB $159.99",
                    "url": "https://www.example.com/deal/990pro",
                    "permalink": "/r/buildapcsales/comments/abc111/ssd/",
                    "selftext": "",
                    "created_utc": 1716412800.0,
                    "score": 102,
                    "num_comments": 35,
                },
            },
            {
                "kind": "t3",
                "data": {
                    "id": "abc222",
                    "subreddit": "GameDeals",
                    "title": "[Steam] Hades II - $24.99 (17% off)",
                    "url": "https://store.steampowered.com/app/example",
                    "permalink": "/r/GameDeals/comments/abc222/steam/",
                    "selftext": "",
                    "created_utc": 1716412900.0,
                    "score": 88,
                    "num_comments": 20,
                },
            },
            {
                "kind": "t3",
                "data": {
                    "id": "abc333",
                    "subreddit": "Frugal",
                    "title": "Daily thread - share your wins!",  # no $ price
                    "url": "https://www.reddit.com/r/Frugal/comments/abc333/",
                    "permalink": "/r/Frugal/comments/abc333/daily/",
                    "selftext": "Discuss your savings.",
                    "created_utc": 1716413000.0,
                    "score": 12,
                    "num_comments": 5,
                },
            },
            {
                "kind": "t3",
                "data": {
                    "id": "abc444",
                    "subreddit": "deals",
                    "title": 'LG OLED C3 65" 4K TV $1,299.99',
                    "url": "https://www.bestbuy.com/site/lg-oled",
                    "permalink": "/r/deals/comments/abc444/lg/",
                    "selftext": "",
                    "created_utc": 1716413100.0,
                    "score": 250,
                    "num_comments": 80,
                },
            },
        ],
    },
}


def _stub_http_client(payload):
    """Build a stand-in for an ``httpx.Client`` returning JSON."""
    resp = MagicMock()
    resp.json = MagicMock(return_value=payload)
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = MagicMock(return_value=resp)
    return client


# ---------------------------------------------------------------------------
# fetch()
# ---------------------------------------------------------------------------


class TestFetch:
    def test_fetch_returns_one_raw_listing_per_post(self):
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        raws = conn.fetch()
        assert len(raws) == 4

    def test_fetch_sets_source_to_reddit(self):
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        raws = conn.fetch()
        assert all(r.source == "reddit" for r in raws)

    def test_fetch_captures_external_id_from_post_id(self):
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        raws = conn.fetch()
        ids = {r.source_external_id for r in raws}
        assert ids == {"abc111", "abc222", "abc333", "abc444"}

    def test_fetch_prefers_external_url_over_permalink(self):
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        raws = conn.fetch()
        ssd = next(r for r in raws if "990 Pro" in r.title)
        assert ssd.url == "https://www.example.com/deal/990pro"

    def test_fetch_falls_back_to_permalink_when_no_external_url(self):
        payload = {
            "kind": "Listing",
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "id": "self1",
                            "subreddit": "deals",
                            "title": "Random $25 deal (self post)",
                            "url": "",  # empty
                            "permalink": "/r/deals/comments/self1/random/",
                        },
                    }
                ]
            },
        }
        conn = RedditConnector(http_client=_stub_http_client(payload))
        raws = conn.fetch()
        assert raws[0].url == "https://www.reddit.com/r/deals/comments/self1/random/"

    def test_fetch_uses_now_for_fetched_at(self):
        before = datetime.now(timezone.utc)
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        raws = conn.fetch()
        after = datetime.now(timezone.utc)
        assert all(before <= r.fetched_at <= after for r in raws)

    def test_fetch_builds_multi_sub_url(self):
        client = _stub_http_client(SAMPLE_PAYLOAD)
        conn = RedditConnector(
            subreddits=["deals", "buildapcsales", "GameDeals"],
            http_client=client,
        )
        conn.fetch()
        called_url = client.get.call_args[0][0]
        assert "r/deals+buildapcsales+GameDeals/new.json" in called_url
        assert "limit=" in called_url

    def test_fetch_uses_default_subs_when_none_provided(self):
        client = _stub_http_client(SAMPLE_PAYLOAD)
        conn = RedditConnector(http_client=client)
        conn.fetch()
        called_url = client.get.call_args[0][0]
        assert "+".join(DEFAULT_SUBS) in called_url


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_normalize_extracts_decimal_price(self):
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        raws = conn.fetch()
        ssd = next(r for r in raws if "990 Pro" in r.title)
        norm = conn.normalize(ssd)
        assert norm is not None
        assert norm.price == 159.99
        assert norm.currency == "USD"

    def test_normalize_extracts_price_with_thousands_separator(self):
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        raws = conn.fetch()
        tv = next(r for r in raws if "OLED" in r.title)
        norm = conn.normalize(tv)
        assert norm is not None
        assert norm.price == 1299.99

    def test_normalize_skips_posts_without_price(self):
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        raws = conn.fetch()
        discussion = next(r for r in raws if "Daily thread" in r.title)
        assert conn.normalize(discussion) is None

    def test_normalize_builds_source_prefixed_listing_id(self):
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        raws = conn.fetch()
        ssd = next(r for r in raws if "990 Pro" in r.title)
        norm = conn.normalize(ssd)
        assert norm is not None
        assert norm.listing_id == "reddit:abc111"

    def test_normalize_produces_lowercase_product_key(self):
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        raws = conn.fetch()
        ssd = next(r for r in raws if "990 Pro" in r.title)
        norm = conn.normalize(ssd)
        assert norm is not None
        assert norm.product_key == norm.product_key.lower()
        assert "samsung 990 pro" in norm.product_key

    def test_normalize_preserves_subreddit_in_extra(self):
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        raws = conn.fetch()
        ssd = next(r for r in raws if "990 Pro" in r.title)
        norm = conn.normalize(ssd)
        assert norm is not None
        assert norm.extra["raw"]["subreddit"] == "buildapcsales"


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


class TestRunEndToEnd:
    def test_run_returns_only_priced_items(self):
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        items = conn.run()
        # 4 posts, 1 is the no-price daily thread -> 3 normalized
        assert len(items) == 3
        assert all(item.price > 0 for item in items)

    def test_run_is_idempotent_when_payload_unchanged(self):
        conn = RedditConnector(http_client=_stub_http_client(SAMPLE_PAYLOAD))
        first = {item.listing_id for item in conn.run()}
        second = {item.listing_id for item in conn.run()}
        assert first == second


# ---------------------------------------------------------------------------
# Malformed payloads
# ---------------------------------------------------------------------------


class TestMalformedPayload:
    def test_fetch_raises_on_non_dict_payload(self):
        conn = RedditConnector(http_client=_stub_http_client(["not", "a", "dict"]))
        with pytest.raises(ConnectorError):
            conn.fetch()

    def test_fetch_raises_on_missing_data_object(self):
        conn = RedditConnector(http_client=_stub_http_client({"kind": "Listing"}))
        with pytest.raises(ConnectorError):
            conn.fetch()

    def test_fetch_raises_on_missing_children_array(self):
        conn = RedditConnector(http_client=_stub_http_client({"data": {}}))
        with pytest.raises(ConnectorError):
            conn.fetch()


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestExtractChildren:
    def test_returns_list_of_child_dicts(self):
        children = _extract_children(SAMPLE_PAYLOAD)
        assert len(children) == 4
        assert all(isinstance(c, dict) for c in children)

    def test_filters_non_dict_children(self):
        payload = {"data": {"children": [{"kind": "t3", "data": {}}, "junk", 42]}}
        assert len(_extract_children(payload)) == 1
