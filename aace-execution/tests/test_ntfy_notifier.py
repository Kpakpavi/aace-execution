"""Unit tests for the NTFY notifier integration."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from aace_execution.integrations.ntfy_notifier import NtfyNotifier


@dataclass
class _FakeListing:
    source: str
    price: float
    url: str


@dataclass
class _FakeOpportunity:
    opportunity_id: str = "opp-test-1"
    product_key: str = "apple watch series 11 gps"
    sources: tuple = ("slickdeals", "techbargains")
    min_price: float = 266.0
    max_price: float = 329.0
    listings: list = None


def _mk_opp(min_p: float = 266.0, max_p: float = 329.0, **kw) -> _FakeOpportunity:
    opp = _FakeOpportunity(min_price=min_p, max_price=max_p, **kw)
    opp.listings = [
        _FakeListing("slickdeals", min_p, "https://slickdeals.net/f/xyz"),
        _FakeListing("techbargains", max_p, "https://techbargains.com/abc"),
    ]
    return opp


def _stub_http(*, status: int = 200, raises: Exception | None = None):
    client = MagicMock()
    if raises is not None:
        client.post.side_effect = raises
        return client
    resp = MagicMock()
    resp.status_code = status
    if status >= 400:
        from requests.exceptions import HTTPError
        resp.raise_for_status.side_effect = HTTPError(
            f"HTTP {status}", response=resp
        )
    else:
        resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"id": "msg-123", "time": 0})
    client.post.return_value = resp
    return client


# ---------------------------------------------------------------------------
# Constructor + env loading
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_empty_topic_rejected(self):
        with pytest.raises(ValueError):
            NtfyNotifier(topic="")

    def test_empty_server_rejected(self):
        with pytest.raises(ValueError):
            NtfyNotifier(topic="t", server="")

    def test_negative_min_net_profit_rejected(self):
        with pytest.raises(ValueError):
            NtfyNotifier(topic="t", min_net_profit=-1.0)

    def test_negative_min_roi_rejected(self):
        with pytest.raises(ValueError):
            NtfyNotifier(topic="t", min_roi_percent=-5.0)

    def test_server_without_scheme_is_promoted_to_https(self):
        n = NtfyNotifier(topic="t", server="ntfy.example.com",
                         http_client=_stub_http())
        # Send anything and inspect the URL posted
        n._http = _stub_http()
        n.send_opportunity(_mk_opp())
        url_posted = n._http.post.call_args[0][0]
        assert url_posted.startswith("https://ntfy.example.com")

    def test_server_trailing_slash_stripped(self):
        n = NtfyNotifier(topic="t", server="https://ntfy.sh/")
        n._http = _stub_http()
        n.send_opportunity(_mk_opp())
        assert n._http.post.call_args[0][0] == "https://ntfy.sh"


# ---------------------------------------------------------------------------
# from_environment
# ---------------------------------------------------------------------------


class TestFromEnvironment:
    def test_returns_none_when_topic_missing(self):
        assert NtfyNotifier.from_environment(env={}) is None

    def test_returns_none_when_topic_blank(self):
        assert NtfyNotifier.from_environment(env={"NTFY_TOPIC": "   "}) is None

    def test_builds_with_just_topic(self):
        n = NtfyNotifier.from_environment(env={"NTFY_TOPIC": "aace-deals-xyz"})
        assert n is not None

    def test_uses_custom_server_when_set(self):
        n = NtfyNotifier.from_environment(env={
            "NTFY_TOPIC": "t",
            "NTFY_SERVER": "https://my-ntfy.example.com",
        })
        assert n is not None
        assert n._server == "https://my-ntfy.example.com"

    def test_bad_threshold_falls_back_to_default(self):
        n = NtfyNotifier.from_environment(env={
            "NTFY_TOPIC": "t",
            "NTFY_MIN_NET_PROFIT": "not_a_number",
        })
        assert n is not None  # didn't crash


# ---------------------------------------------------------------------------
# Threshold filtering
# ---------------------------------------------------------------------------


class TestThresholdFiltering:
    def test_skips_when_net_below_floor(self):
        http = _stub_http()
        n = NtfyNotifier(
            topic="t", min_net_profit=5.0, min_roi_percent=0.0,
            http_client=http,
        )
        # Buy $100, resale $110, eBay 13.25% = $14.58, ship $8
        # Net = 110 - 100 - 14.58 - 8 = -12.58
        result = n.send_opportunity(_mk_opp(min_p=100.0, max_p=110.0))
        assert result.status == "skipped"
        assert "net_below_floor" in (result.reason or "")
        http.post.assert_not_called()

    def test_skips_when_roi_below_floor(self):
        http = _stub_http()
        n = NtfyNotifier(
            topic="t", min_net_profit=0.0, min_roi_percent=10.0,
            http_client=http,
        )
        # Buy $200, resale $250, eBay 13.25% = $33.13, ship $8
        # Net = 8.87, ROI = 4.43%  → above net=0, below roi=10
        result = n.send_opportunity(_mk_opp(min_p=200.0, max_p=250.0))
        assert result.status == "skipped"
        assert "roi_below_floor" in (result.reason or "")
        http.post.assert_not_called()

    def test_delivers_when_both_thresholds_met(self):
        http = _stub_http()
        n = NtfyNotifier(
            topic="t", min_net_profit=5.0, min_roi_percent=3.0,
            http_client=http,
        )
        # Default opp: net ~ 11.41, ROI ~ 4.3% — passes both
        result = n.send_opportunity(_mk_opp())
        assert result.status == "delivered"
        http.post.assert_called_once()


# ---------------------------------------------------------------------------
# Publish payload shape
# ---------------------------------------------------------------------------


class TestPayloadShape:
    def test_publish_url_is_server_root(self):
        http = _stub_http()
        n = NtfyNotifier(
            topic="aace-deals-9f3k2q", server="https://ntfy.sh",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        n.send_opportunity(_mk_opp())
        # JSON publish goes to the server root, NOT the topic URL
        assert http.post.call_args[0][0] == "https://ntfy.sh"

    def test_payload_includes_topic(self):
        http = _stub_http()
        n = NtfyNotifier(
            topic="aace-deals-9f3k2q",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        n.send_opportunity(_mk_opp())
        payload = http.post.call_args[1]["json"]
        assert payload["topic"] == "aace-deals-9f3k2q"

    def test_payload_includes_title_and_message(self):
        http = _stub_http()
        n = NtfyNotifier(
            topic="t",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        n.send_opportunity(_mk_opp())
        payload = http.post.call_args[1]["json"]
        assert "title" in payload
        assert "message" in payload
        # Message body mentions the product
        assert "Apple Watch Series 11 Gps" in payload["message"]
        # Prices visible
        assert "266" in payload["message"]
        assert "329" in payload["message"]

    def test_high_margin_gets_high_priority_and_money_tag(self):
        # Buy $50, resale $200 → net 115.5 → priority 5 + moneybag tag
        http = _stub_http()
        n = NtfyNotifier(
            topic="t",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        n.send_opportunity(_mk_opp(min_p=50.0, max_p=200.0))
        payload = http.post.call_args[1]["json"]
        assert payload["priority"] == 5
        assert "moneybag" in payload["tags"]
        assert "💰" in payload["title"]

    def test_normal_margin_gets_medium_high_priority(self):
        http = _stub_http()
        n = NtfyNotifier(
            topic="t",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        n.send_opportunity(_mk_opp())  # net ~ 11
        payload = http.post.call_args[1]["json"]
        assert payload["priority"] == 4
        assert "moneybag" not in payload["tags"]

    def test_click_action_links_to_cheapest_source(self):
        http = _stub_http()
        n = NtfyNotifier(
            topic="t",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        n.send_opportunity(_mk_opp())  # slickdeals is cheapest at $266
        payload = http.post.call_args[1]["json"]
        assert payload["click"] == "https://slickdeals.net/f/xyz"

    def test_click_omitted_when_no_listings(self):
        http = _stub_http()
        n = NtfyNotifier(
            topic="t",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        opp = _mk_opp()
        opp.listings = []
        n.send_opportunity(opp)
        payload = http.post.call_args[1]["json"]
        assert "click" not in payload


# ---------------------------------------------------------------------------
# Failure tolerance — NEVER crash the worker
# ---------------------------------------------------------------------------


class TestFailureTolerance:
    def test_http_500_returns_failed(self):
        http = _stub_http(status=500)
        n = NtfyNotifier(
            topic="t",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        result = n.send_opportunity(_mk_opp())
        assert result.status == "failed"
        assert result.last_status_code == 500

    def test_connection_error_returns_failed(self):
        http = _stub_http(raises=ConnectionError("network is down"))
        n = NtfyNotifier(
            topic="t",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        result = n.send_opportunity(_mk_opp())
        assert result.status == "failed"
        assert "ConnectionError" in (result.reason or "")
