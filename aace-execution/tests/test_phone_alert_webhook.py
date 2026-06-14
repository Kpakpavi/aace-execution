"""Unit tests for the phone-alert webhook integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from aace_execution.integrations.phone_alert_webhook import (
    PhoneAlertResult,
    PhoneAlertWebhook,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _FakeListing:
    source: str
    price: float
    url: str


@dataclass
class _FakeOpportunity:
    opportunity_id: str = "opp-phone-1"
    product_key: str = "apple watch series 11 gps"
    sources: tuple = ("slickdeals", "techbargains")
    min_price: float = 50.0
    max_price: float = 200.0
    listings: list = None
    detected_at: datetime = datetime(2026, 6, 11, 5, 0, tzinfo=timezone.utc)


def _mk_opp(min_p: float = 50.0, max_p: float = 200.0, **kw) -> _FakeOpportunity:
    opp = _FakeOpportunity(min_price=min_p, max_price=max_p, **kw)
    opp.listings = [
        _FakeListing("slickdeals", min_p, f"https://slickdeals.net/{min_p}"),
        _FakeListing("techbargains", max_p, f"https://techbargains.com/{max_p}"),
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
    resp.json = MagicMock(return_value={"ok": True})
    client.post.return_value = resp
    return client


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_empty_url_rejected(self):
        with pytest.raises(ValueError):
            PhoneAlertWebhook(webhook_url="")

    def test_negative_min_net_rejected(self):
        with pytest.raises(ValueError):
            PhoneAlertWebhook(webhook_url="u", min_net_profit=-1)

    def test_negative_min_roi_rejected(self):
        with pytest.raises(ValueError):
            PhoneAlertWebhook(webhook_url="u", min_roi_percent=-1)

    def test_critical_below_min_rejected(self):
        with pytest.raises(ValueError):
            PhoneAlertWebhook(
                webhook_url="u", min_net_profit=100,
                critical_net_profit=50,
            )


# ---------------------------------------------------------------------------
# from_environment
# ---------------------------------------------------------------------------


class TestFromEnvironment:
    def test_disabled_without_url(self):
        assert PhoneAlertWebhook.from_environment(env={}) is None

    def test_disabled_when_url_blank(self):
        assert PhoneAlertWebhook.from_environment(
            env={"ZAPIER_WEBHOOK_URL": "   "}
        ) is None

    def test_builds_with_just_url(self):
        n = PhoneAlertWebhook.from_environment(env={
            "ZAPIER_WEBHOOK_URL": "https://hooks.zapier.com/abc",
        })
        assert n is not None
        assert n._min_net_profit == 50.0  # default
        assert n._min_roi_percent == 20.0  # default

    def test_picks_up_thresholds(self):
        n = PhoneAlertWebhook.from_environment(env={
            "ZAPIER_WEBHOOK_URL": "https://hooks.zapier.com/abc",
            "PHONE_ALERT_MIN_NET": "75",
            "PHONE_ALERT_MIN_ROI": "25",
            "PHONE_ALERT_CRITICAL_NET": "300",
        })
        assert n._min_net_profit == 75.0
        assert n._min_roi_percent == 25.0
        assert n._critical_net_profit == 300.0

    def test_bad_threshold_falls_back(self):
        n = PhoneAlertWebhook.from_environment(env={
            "ZAPIER_WEBHOOK_URL": "https://hooks.zapier.com/abc",
            "PHONE_ALERT_MIN_NET": "garbage",
        })
        assert n is not None
        assert n._min_net_profit == 50.0


# ---------------------------------------------------------------------------
# Threshold gating
# ---------------------------------------------------------------------------


class TestThresholdGating:
    def test_skips_below_net_floor(self):
        http = _stub_http()
        n = PhoneAlertWebhook(
            webhook_url="u", min_net_profit=100.0, min_roi_percent=0.0,
            http_client=http,
        )
        # Buy $50, resale $200 → eBay 13.25% = $26.50, ship $8
        # Net = 200 - 50 - 26.50 - 8 = 115.5 → wait, that PASSES 100 floor.
        # Use a tighter input: buy $50, resale $100 → net = 100-50-13.25-8 = 28.75
        result = n.send_alert(_mk_opp(min_p=50.0, max_p=100.0))
        assert result.status == "skipped"
        assert "net_below_floor" in (result.reason or "")
        http.post.assert_not_called()

    def test_skips_below_roi_floor(self):
        http = _stub_http()
        n = PhoneAlertWebhook(
            webhook_url="u", min_net_profit=0.0, min_roi_percent=500.0,
            http_client=http,
        )
        # 500% ROI is impossible at this scale
        result = n.send_alert(_mk_opp())
        assert result.status == "skipped"
        assert "roi_below_floor" in (result.reason or "")
        http.post.assert_not_called()

    def test_fires_when_both_thresholds_met(self):
        # Default opp: buy $50, resale $200, eBay fee $26.50, ship $8
        # Net = 115.5, ROI = 231%
        http = _stub_http()
        n = PhoneAlertWebhook(
            webhook_url="u", min_net_profit=50.0, min_roi_percent=20.0,
            http_client=http,
        )
        result = n.send_alert(_mk_opp())
        assert result.status == "delivered"
        http.post.assert_called_once()


# ---------------------------------------------------------------------------
# Payload shape (the Zapier contract)
# ---------------------------------------------------------------------------


class TestPayloadShape:
    def test_posts_to_configured_url(self):
        http = _stub_http()
        n = PhoneAlertWebhook(
            webhook_url="https://hooks.zapier.com/xyz",
            min_net_profit=0, min_roi_percent=0,
            http_client=http,
        )
        n.send_alert(_mk_opp())
        assert http.post.call_args[0][0] == "https://hooks.zapier.com/xyz"

    def test_payload_is_flat_with_top_level_fields(self):
        http = _stub_http()
        n = PhoneAlertWebhook(
            webhook_url="u", min_net_profit=0, min_roi_percent=0,
            http_client=http,
        )
        n.send_alert(_mk_opp())
        p = http.post.call_args[1]["json"]
        # Top-level keys Zapier needs to find
        for key in (
            "alert_type", "alert_priority", "product_name",
            "buy_price_usd", "buy_source", "buy_url",
            "resell_price_usd", "resell_source", "resell_url",
            "marketplace_fee_usd", "shipping_usd",
            "net_profit_usd", "roi_percent",
            "detected_at", "voice_script",
        ):
            assert key in p, f"missing top-level key {key!r}"

    def test_high_priority_when_below_critical_floor(self):
        # Buy $50, resale $200 → net $115.5 < critical floor 200
        http = _stub_http()
        n = PhoneAlertWebhook(
            webhook_url="u", min_net_profit=0, min_roi_percent=0,
            critical_net_profit=200.0,
            http_client=http,
        )
        n.send_alert(_mk_opp())
        assert http.post.call_args[1]["json"]["alert_priority"] == "high"

    def test_critical_priority_when_above_critical_floor(self):
        # Buy $50, resale $500 → eBay $66.25 + $8 ship → net 375.75
        http = _stub_http()
        n = PhoneAlertWebhook(
            webhook_url="u", min_net_profit=0, min_roi_percent=0,
            critical_net_profit=200.0,
            http_client=http,
        )
        n.send_alert(_mk_opp(min_p=50.0, max_p=500.0))
        assert http.post.call_args[1]["json"]["alert_priority"] == "critical"

    def test_voice_script_includes_product_and_money(self):
        http = _stub_http()
        n = PhoneAlertWebhook(
            webhook_url="u", min_net_profit=0, min_roi_percent=0,
            http_client=http,
        )
        n.send_alert(_mk_opp())
        script = http.post.call_args[1]["json"]["voice_script"]
        assert "Apple Watch Series 11 Gps" in script
        assert "$50" in script  # buy price
        assert "$200" in script  # resell price

    def test_buy_url_picks_cheapest_listing(self):
        http = _stub_http()
        n = PhoneAlertWebhook(
            webhook_url="u", min_net_profit=0, min_roi_percent=0,
            http_client=http,
        )
        opp = _mk_opp(min_p=50.0, max_p=200.0)
        n.send_alert(opp)
        p = http.post.call_args[1]["json"]
        assert p["buy_source"] == "slickdeals"
        assert "50.0" in p["buy_url"]

    def test_resell_url_picks_priciest_listing(self):
        http = _stub_http()
        n = PhoneAlertWebhook(
            webhook_url="u", min_net_profit=0, min_roi_percent=0,
            http_client=http,
        )
        opp = _mk_opp(min_p=50.0, max_p=200.0)
        n.send_alert(opp)
        p = http.post.call_args[1]["json"]
        assert p["resell_source"] == "techbargains"
        assert "200.0" in p["resell_url"]


# ---------------------------------------------------------------------------
# Failure tolerance
# ---------------------------------------------------------------------------


class TestFailureTolerance:
    def test_http_500_returns_failed(self):
        http = _stub_http(status=500)
        n = PhoneAlertWebhook(
            webhook_url="u", min_net_profit=0, min_roi_percent=0,
            http_client=http,
        )
        result = n.send_alert(_mk_opp())
        assert result.status == "failed"
        assert result.last_status_code == 500

    def test_connection_error_returns_failed(self):
        http = _stub_http(raises=ConnectionError("zap down"))
        n = PhoneAlertWebhook(
            webhook_url="u", min_net_profit=0, min_roi_percent=0,
            http_client=http,
        )
        result = n.send_alert(_mk_opp())
        assert result.status == "failed"
        assert "ConnectionError" in (result.reason or "")
