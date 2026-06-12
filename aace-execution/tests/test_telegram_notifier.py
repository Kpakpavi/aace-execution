"""Unit tests for the Telegram notifier integration.

Mocks the HTTP layer with a fake client. No real Telegram API calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from aace_execution.integrations.telegram_notifier import (
    TelegramDeliveryResult,
    TelegramNotifier,
    _escape_md_v2,
    _escape_md_v2_link,
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
    """Minimal stand-in matching what worker passes to send_opportunity."""

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
    """Return a stand-in for ``requests`` exposing ``.post``."""
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
    def test_empty_token_rejected(self):
        with pytest.raises(ValueError):
            TelegramNotifier(bot_token="", chat_id="123")

    def test_empty_chat_id_rejected(self):
        with pytest.raises(ValueError):
            TelegramNotifier(bot_token="abc", chat_id="")

    def test_negative_min_net_profit_rejected(self):
        with pytest.raises(ValueError):
            TelegramNotifier(
                bot_token="abc", chat_id="1", min_net_profit=-1.0
            )

    def test_negative_min_roi_rejected(self):
        with pytest.raises(ValueError):
            TelegramNotifier(
                bot_token="abc", chat_id="1", min_roi_percent=-5.0
            )

    def test_constructs_with_valid_inputs(self):
        n = TelegramNotifier(
            bot_token="abc", chat_id="1",
            http_client=_stub_http(),
        )
        assert n is not None


# ---------------------------------------------------------------------------
# from_environment
# ---------------------------------------------------------------------------


class TestFromEnvironment:
    def test_returns_none_when_token_missing(self):
        assert TelegramNotifier.from_environment(env={"TELEGRAM_CHAT_ID": "123"}) is None

    def test_returns_none_when_chat_id_missing(self):
        assert TelegramNotifier.from_environment(env={"TELEGRAM_BOT_TOKEN": "abc"}) is None

    def test_returns_none_when_both_blank(self):
        assert TelegramNotifier.from_environment(env={}) is None

    def test_builds_instance_when_both_set(self):
        n = TelegramNotifier.from_environment(env={
            "TELEGRAM_BOT_TOKEN": "abc",
            "TELEGRAM_CHAT_ID": "123",
        })
        assert n is not None

    def test_bad_threshold_falls_back_to_default(self):
        # Garbage in TELEGRAM_MIN_NET_PROFIT shouldn't crash, just default
        n = TelegramNotifier.from_environment(env={
            "TELEGRAM_BOT_TOKEN": "abc",
            "TELEGRAM_CHAT_ID": "123",
            "TELEGRAM_MIN_NET_PROFIT": "not_a_number",
        })
        assert n is not None  # didn't crash


# ---------------------------------------------------------------------------
# Threshold filtering
# ---------------------------------------------------------------------------


class TestThresholdFiltering:
    def test_skips_when_net_profit_below_floor(self):
        # Buy $100, resale $110, eBay 13.25% = $14.58 fee, $8 ship
        # Net = 110 - 100 - 14.58 - 8 = -12.58 → below floor
        http = _stub_http()
        n = TelegramNotifier(
            bot_token="abc", chat_id="1",
            min_net_profit=5.0, min_roi_percent=0.0,
            http_client=http,
        )
        result = n.send_opportunity(_mk_opp(min_p=100.0, max_p=110.0))
        assert result.status == "skipped"
        assert "net_below_floor" in (result.reason or "")
        http.post.assert_not_called()

    def test_skips_when_roi_below_floor(self):
        # Buy $200, resale $230, eBay 13.25% = $30.48 fee, $8 ship
        # Net = 230 - 200 - 30.48 - 8 = -8.48 → fails net first
        # Use buy $1000, resale $1050 instead — net = ~1.50, ROI ~0.15%
        # which passes net=1.0 floor but fails roi=3% floor
        http = _stub_http()
        n = TelegramNotifier(
            bot_token="abc", chat_id="1",
            min_net_profit=0.0,
            min_roi_percent=10.0,
            http_client=http,
        )
        # Buy $200, resale $250, eBay 13.25% = $33.13 fee, $8 ship
        # Net = 250 - 200 - 33.13 - 8 = 8.87, ROI = 4.43%
        # Above net=0 but below roi=10
        result = n.send_opportunity(_mk_opp(min_p=200.0, max_p=250.0))
        assert result.status == "skipped"
        assert "roi_below_floor" in (result.reason or "")
        http.post.assert_not_called()

    def test_delivers_when_both_thresholds_met(self):
        # Apple watch default: buy $266, resale $329
        # eBay 13.25% fee = $43.59, $8 ship
        # Net = 329 - 266 - 43.59 - 8 = 11.41, ROI = 4.3%
        http = _stub_http()
        n = TelegramNotifier(
            bot_token="abc", chat_id="1",
            min_net_profit=5.0,
            min_roi_percent=3.0,
            http_client=http,
        )
        result = n.send_opportunity(_mk_opp())
        assert result.status == "delivered"
        http.post.assert_called_once()


# ---------------------------------------------------------------------------
# Send mechanics
# ---------------------------------------------------------------------------


class TestSendMechanics:
    def test_posts_to_correct_telegram_url(self):
        http = _stub_http()
        n = TelegramNotifier(
            bot_token="my-token-xyz", chat_id="999",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        n.send_opportunity(_mk_opp())
        url = http.post.call_args[0][0]
        assert url == "https://api.telegram.org/botmy-token-xyz/sendMessage"

    def test_payload_includes_chat_id_and_parse_mode(self):
        http = _stub_http()
        n = TelegramNotifier(
            bot_token="t", chat_id="55555",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        n.send_opportunity(_mk_opp())
        payload = http.post.call_args[1]["json"]
        assert payload["chat_id"] == "55555"
        assert payload["parse_mode"] == "MarkdownV2"
        assert payload["disable_web_page_preview"] is True
        assert "text" in payload and len(payload["text"]) > 0

    def test_message_includes_product_and_numbers(self):
        http = _stub_http()
        n = TelegramNotifier(
            bot_token="t", chat_id="1",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        n.send_opportunity(_mk_opp())
        text = http.post.call_args[1]["json"]["text"]
        # MarkdownV2 escapes everything aggressively, so check fragments
        assert "Apple Watch Series 11 Gps" in text
        # Buy and resale prices visible
        assert "266" in text
        assert "329" in text

    def test_strong_margin_emoji_for_big_net(self):
        # Buy $50, resale $200, eBay fee 13.25% = $26.50, $8 ship
        # Net = 200 - 50 - 26.50 - 8 = 115.5 → strong margin emoji
        http = _stub_http()
        n = TelegramNotifier(
            bot_token="t", chat_id="1",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        n.send_opportunity(_mk_opp(min_p=50.0, max_p=200.0))
        text = http.post.call_args[1]["json"]["text"]
        assert "💰" in text  # money emoji for strong margin


# ---------------------------------------------------------------------------
# Failure tolerance — NEVER crash the worker tick
# ---------------------------------------------------------------------------


class TestFailureTolerance:
    def test_http_500_returns_failed_not_raised(self):
        http = _stub_http(status=500)
        n = TelegramNotifier(
            bot_token="t", chat_id="1",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        result = n.send_opportunity(_mk_opp())
        assert result.status == "failed"
        assert result.last_status_code == 500

    def test_connection_error_returns_failed_not_raised(self):
        http = _stub_http(raises=ConnectionError("no route"))
        n = TelegramNotifier(
            bot_token="t", chat_id="1",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        result = n.send_opportunity(_mk_opp())
        assert result.status == "failed"
        assert "ConnectionError" in (result.reason or "")

    def test_404_chat_not_found_returns_failed(self):
        # Common error: chat_id wrong, Telegram returns 400 "chat not found"
        http = _stub_http(status=400)
        n = TelegramNotifier(
            bot_token="t", chat_id="1",
            min_net_profit=0.0, min_roi_percent=0.0,
            http_client=http,
        )
        result = n.send_opportunity(_mk_opp())
        assert result.status == "failed"
        assert result.last_status_code == 400


# ---------------------------------------------------------------------------
# MarkdownV2 escaping
# ---------------------------------------------------------------------------


class TestMarkdownEscape:
    @pytest.mark.parametrize("ch", list("_*[]()~`>#+-=|{}.!"))
    def test_escapes_each_reserved_char(self, ch):
        assert _escape_md_v2(ch) == f"\\{ch}"

    def test_empty_string(self):
        assert _escape_md_v2("") == ""

    def test_leaves_alphanumerics_alone(self):
        assert _escape_md_v2("HelloWorld123") == "HelloWorld123"

    def test_escapes_real_product_title(self):
        # Real-world deal title with parens, dollar sign, periods
        raw = "Apple Watch Series 11 (GPS, 45mm) $329.99"
        escaped = _escape_md_v2(raw)
        # Each reserved char should be preceded by a backslash
        assert "\\(" in escaped
        assert "\\)" in escaped
        assert "\\." in escaped

    def test_link_escape_only_handles_closing_paren_and_backslash(self):
        # URLs may contain ?, =, &, but those don't need escaping
        # inside link parens — only \ and ) do.
        url = "https://example.com/path?a=1&b=2"
        assert _escape_md_v2_link(url) == url

    def test_link_escape_handles_paren_in_url(self):
        url = "https://example.com/path(test)"
        # Only the closing paren needs escaping
        assert _escape_md_v2_link(url) == "https://example.com/path(test\\)"
