"""Telegram notification integration.

Sends a formatted, Markdown-styled message to a Telegram chat for each
profitable AACE opportunity. Designed to complement (not replace) the
``agent_webhook`` channel: both fire per scored opportunity and either
can fail without affecting the other.

Why Telegram (vs Slack / email / SMS):
  * Telegram bot creation is free, no business account needed
  * Bot API is plain HTTPS — no SDK lock-in
  * Push notifications arrive on phone within seconds
  * Cleartext API means easy debug — no opaque webhook signatures
  * Markdown formatting renders inline in the chat

This module intentionally:
  * NEVER raises into the worker tick (errors return False)
  * Computes its own net-profit + ROI from the payload metadata, so it
    can independently apply a "interesting enough to ping" threshold
    that may differ from the webhook's
  * Uses the Bot API ``sendMessage`` endpoint with parse_mode=MarkdownV2

To configure:
  * ``TELEGRAM_BOT_TOKEN`` — from @BotFather
  * ``TELEGRAM_CHAT_ID``   — your personal chat ID (or a group/channel)
  * ``TELEGRAM_MIN_NET_PROFIT`` (optional) — float, default 1.00 USD
  * ``TELEGRAM_MIN_ROI_PERCENT`` (optional) — float, default 3.0 (=3%)
  * ``TELEGRAM_DEFAULT_PLATFORM`` (optional) — defaults to "eBay";
    used only to compute fee/ROI for the notification message
  * ``TELEGRAM_DEFAULT_SHIPPING`` (optional) — defaults to 8.0 USD
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — keep aligned with dashboard/app.py PLATFORM_FEES
# ---------------------------------------------------------------------------

# Headline seller fee for each platform we model. These are the same
# numbers the dashboard surfaces in the Best Profit Opportunities panel,
# duplicated here so this module can run without importing the
# Streamlit-side code.
_PLATFORM_FEES: dict[str, float] = {
    "eBay": 0.1325,
    "Amazon": 0.15,
    "StockX": 0.125,
    "Mercari": 0.129,
    "FB Marketplace (National)": 0.05,
    "FB Marketplace (Local)": 0.0,
}

# MarkdownV2 reserves these characters — they MUST be escaped with a
# backslash to render as literal text, or Telegram returns HTTP 400.
# See https://core.telegram.org/bots/api#markdownv2-style
_MD_V2_RESERVED = r"_*[]()~`>#+-=|{}.!"


# ---------------------------------------------------------------------------
# Delivery result (mirrors WebhookDeliveryResult so worker code can treat
# both channels uniformly)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TelegramDeliveryResult:
    status: str                      # "delivered" | "skipped" | "failed" | "disabled"
    opportunity_id: str | None       # echoed for log correlation; None if disabled
    reason: str | None = None        # human-readable explanation for skipped/failed
    last_status_code: int | None = None


# ---------------------------------------------------------------------------
# The notifier itself
# ---------------------------------------------------------------------------


class TelegramNotifier:
    """Posts AACE opportunities to a Telegram chat.

    Construct with explicit credentials for tests, or use
    :meth:`from_environment` for the production path.

    Filtering:
      * Skips opportunities whose computed net profit is below
        ``min_net_profit`` OR whose ROI is below ``min_roi_percent``.
      * Returns ``status="skipped"`` for filtered-out items so the
        caller can distinguish "didn't try" from "tried and failed."
    """

    _BASE_URL = "https://api.telegram.org"

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        min_net_profit: float = 1.0,
        min_roi_percent: float = 3.0,
        default_platform: str = "eBay",
        default_shipping: float = 8.0,
        http_client: Any = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not bot_token:
            raise ValueError("bot_token is required")
        if not chat_id:
            raise ValueError("chat_id is required")
        if min_net_profit < 0:
            raise ValueError("min_net_profit must be >= 0")
        if min_roi_percent < 0:
            raise ValueError("min_roi_percent must be >= 0")

        self._bot_token = bot_token
        self._chat_id = str(chat_id)
        self._min_net_profit = float(min_net_profit)
        self._min_roi_percent = float(min_roi_percent)
        self._default_platform = default_platform
        self._default_shipping = float(default_shipping)
        self._timeout = timeout_seconds
        # ``http_client`` mirrors the contract used by KeepaClient:
        # ``.post(url, json=..., timeout=...) -> Response`` with
        # ``.raise_for_status()`` and ``.json()``.
        if http_client is None:
            import requests
            http_client = requests
        self._http = http_client

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_environment(cls, env: dict[str, str] | None = None):
        """Build from process env vars. Returns ``None`` when disabled.

        Returning ``None`` (instead of raising) is the gentle path —
        local-dev environments without Telegram configured shouldn't
        force the worker to fail to start.
        """
        import os
        env = env if env is not None else os.environ

        token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat = env.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat:
            logger.info("telegram_notifier_disabled_missing_env")
            return None

        def _f(name: str, default: float) -> float:
            val = env.get(name, "").strip()
            if not val:
                return default
            try:
                return float(val)
            except ValueError:
                logger.warning(
                    "telegram_env_bad_number",
                    extra={"name": name, "value": val, "default": default},
                )
                return default

        return cls(
            bot_token=token,
            chat_id=chat,
            min_net_profit=_f("TELEGRAM_MIN_NET_PROFIT", 1.0),
            min_roi_percent=_f("TELEGRAM_MIN_ROI_PERCENT", 3.0),
            default_platform=env.get(
                "TELEGRAM_DEFAULT_PLATFORM", "eBay"
            ).strip() or "eBay",
            default_shipping=_f("TELEGRAM_DEFAULT_SHIPPING", 8.0),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_opportunity(self, opportunity: Any) -> TelegramDeliveryResult:
        """Send one ScoredOpportunity to Telegram.

        Never raises. The worker can treat this as an effect that may
        silently no-op (skipped / failed / disabled) without affecting
        the rest of the tick.
        """
        opp_id = getattr(opportunity, "opportunity_id", None)

        try:
            buy, resale = self._buy_and_resale(opportunity)
            fee, net, roi = self._calc_profit(buy, resale)
        except Exception as exc:  # noqa: BLE001 — never crash a tick
            logger.warning(
                "telegram_calc_failed",
                extra={
                    "opportunity_id": opp_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return TelegramDeliveryResult(
                status="failed",
                opportunity_id=opp_id,
                reason="calc_error",
            )

        # Apply thresholds — don't ping for marginal deals
        if net < self._min_net_profit:
            return TelegramDeliveryResult(
                status="skipped",
                opportunity_id=opp_id,
                reason=f"net_below_floor (${net} < ${self._min_net_profit})",
            )
        if roi < self._min_roi_percent:
            return TelegramDeliveryResult(
                status="skipped",
                opportunity_id=opp_id,
                reason=f"roi_below_floor ({roi}% < {self._min_roi_percent}%)",
            )

        text = self._format_message(
            opportunity=opportunity,
            buy=buy, resale=resale, fee=fee, net=net, roi=roi,
        )

        try:
            response = self._http.post(
                f"{self._BASE_URL}/bot{self._bot_token}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": True,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning(
                "telegram_send_failed",
                extra={
                    "opportunity_id": opp_id,
                    "status_code": status_code,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return TelegramDeliveryResult(
                status="failed",
                opportunity_id=opp_id,
                reason=f"{type(exc).__name__}",
                last_status_code=status_code,
            )

        logger.info(
            "telegram_delivered",
            extra={"opportunity_id": opp_id, "net_profit": net, "roi": roi},
        )
        return TelegramDeliveryResult(
            status="delivered",
            opportunity_id=opp_id,
            last_status_code=200,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _buy_and_resale(self, opportunity: Any) -> tuple[float, float]:
        """Pull buy + resale prices from a ScoredOpportunity.

        Buy = cheapest source price (``min_price``).
        Resale = best resale baseline we have. Prefers a resale comp
        if present in the opportunity's listings extra, falls back to
        ``max_price`` (the legacy proxy).
        """
        buy = float(getattr(opportunity, "min_price", 0.0))
        resale = float(getattr(opportunity, "max_price", 0.0))
        return buy, resale

    def _calc_profit(self, buy: float, resale: float) -> tuple[float, float, float]:
        """Fee, net profit, and ROI for the default resale platform.

        Mirrors dashboard ``calc_profit`` — duplicated here so this
        module doesn't import from the Streamlit-side code.
        """
        fee_rate = _PLATFORM_FEES.get(self._default_platform, 0.0)
        fee = round(resale * fee_rate, 2)
        net = round(resale - buy - fee - self._default_shipping, 2)
        roi = round((net / buy) * 100, 1) if buy > 0 else 0.0
        return fee, net, roi

    def _format_message(
        self,
        *,
        opportunity: Any,
        buy: float,
        resale: float,
        fee: float,
        net: float,
        roi: float,
    ) -> str:
        """Build the MarkdownV2 message body."""
        product_key = getattr(opportunity, "product_key", "")
        sources = getattr(opportunity, "sources", [])
        sources_str = ", ".join(sources) if sources else "?"

        listings = getattr(opportunity, "listings", [])
        # Cheapest source link gets first billing (buy-side)
        buy_url: str | None = None
        if listings:
            try:
                cheapest = min(listings, key=lambda l: getattr(l, "price", float("inf")))
                buy_url = getattr(cheapest, "url", None)
            except Exception:  # noqa: BLE001
                buy_url = None

        # Headline emoji — single 🔥 for >$5 net, fire+money for >$20 net
        if net >= 20.0:
            headline = "🔥💰 *AACE Deal — Strong Margin*"
        else:
            headline = "🔥 *AACE Deal Found*"

        body_parts = [
            headline,
            "",
            f"*{_escape_md_v2(product_key.title())}*",
            "",
            f"Buy: ${_escape_md_v2(f'{buy:.2f}')} \\(cheapest of {_escape_md_v2(sources_str)}\\)",
            f"Resell: ${_escape_md_v2(f'{resale:.2f}')} \\(best observed\\)",
            "",
            f"On *{_escape_md_v2(self._default_platform)}* after "
            f"{_escape_md_v2(f'{_PLATFORM_FEES.get(self._default_platform, 0.0)*100:.2f}')}% fee "
            f"\\+ ${_escape_md_v2(f'{self._default_shipping:.2f}')} ship:",
            f"Fee: ${_escape_md_v2(f'{fee:.2f}')}",
            f"*Net: ${_escape_md_v2(f'{net:.2f}')} \\| ROI: {_escape_md_v2(f'{roi:.1f}')}%*",
        ]
        if buy_url:
            body_parts.append("")
            body_parts.append(
                f"[Open the deal]({_escape_md_v2_link(buy_url)})"
            )

        return "\n".join(body_parts)


# ---------------------------------------------------------------------------
# MarkdownV2 escaping helpers
# ---------------------------------------------------------------------------


def _escape_md_v2(text: str) -> str:
    """Backslash-escape every reserved MarkdownV2 character.

    Reserved chars: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    if not text:
        return ""
    out = []
    for ch in text:
        if ch in _MD_V2_RESERVED:
            out.append("\\")
        out.append(ch)
    return "".join(out)


def _escape_md_v2_link(url: str) -> str:
    """Escape only the characters that break inside a ``[...](url)`` link.

    Telegram's MarkdownV2 only requires escaping ``)`` and ``\\`` inside
    a link target; escaping every reserved char would break the URL.
    """
    return (url or "").replace("\\", "\\\\").replace(")", "\\)")
