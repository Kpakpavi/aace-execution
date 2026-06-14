"""Phone-call alert integration.

For the most valuable opportunities AACE finds (above configurable net
profit + ROI floors), this notifier POSTs a JSON payload to a Zapier
webhook URL. The Zap on the receiving end calls Synthflow (or any other
AI-voice provider) and the AI rings the operator's phone with the deal
details read aloud.

Why this is a separate channel from the existing ``agent_webhook``:

* ``agent_webhook`` is the AACE-to-AI-agent contract — every scored
  opportunity goes through it, with HMAC signing and a strict payload
  shape. It's a system bus, not a notification.
* ``phone_alert_webhook`` is operator-facing, threshold-gated, and
  designed to land cleanly inside Zapier's "Trigger when a webhook
  fires" UI. Flat keys, no signing, no dedup — Zapier handles all of
  that better than we can.

Payload contract
----------------
The shape is intentionally flat and human-friendly so Zapier's
visual mapper finds every field at the top level. The
``voice_script`` field is pre-built so the receiving Zap can drop
it straight into Synthflow's "what should the AI say?" parameter
with no transformation.

    {
        "alert_type": "high_profit_deal",
        "alert_priority": "high" | "critical",
        "product_name": "Apple Watch Series 11 GPS",
        "platform": "eBay",
        "buy_price_usd": 266.00,
        "buy_source": "slickdeals",
        "buy_url": "https://slickdeals.net/...",
        "resell_price_usd": 329.00,
        "resell_source": "techbargains",
        "marketplace_fee_usd": 43.59,
        "shipping_usd": 8.00,
        "net_profit_usd": 11.41,
        "roi_percent": 4.3,
        "detected_at": "2026-06-11T05:00:00+00:00",
        "voice_script": "Hey, AACE just spotted a high-margin deal: ..."
    }

Config (all via env, all optional — absent URL disables the channel):

* ``ZAPIER_WEBHOOK_URL``        — required to enable
* ``PHONE_ALERT_MIN_NET``       — default 50.00 (USD)
* ``PHONE_ALERT_MIN_ROI``       — default 20.0 (percent)
* ``PHONE_ALERT_PLATFORM``      — fee/ROI math platform, default ``eBay``
* ``PHONE_ALERT_SHIPPING``      — default 8.00
* ``PHONE_ALERT_CRITICAL_NET``  — net floor for ``critical`` priority
                                   (vs ``high``), default 200.00
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


_PLATFORM_FEES: dict[str, float] = {
    "eBay": 0.1325,
    "Amazon": 0.15,
    "StockX": 0.125,
    "Mercari": 0.129,
    "FB Marketplace (National)": 0.05,
    "FB Marketplace (Local)": 0.0,
}


@dataclass(frozen=True)
class PhoneAlertResult:
    """Outcome of one phone-alert dispatch."""

    status: str                      # "delivered" | "skipped" | "failed" | "disabled"
    opportunity_id: str | None
    reason: str | None = None
    last_status_code: int | None = None


class PhoneAlertWebhook:
    """Triggers an AI voice call for high-margin opportunities.

    The transport is just an HTTP POST. The Zap on the receiving end
    is responsible for: (a) optional further filtering, (b) calling
    the Synthflow API to start the call, (c) handling retries on call
    failure.
    """

    def __init__(
        self,
        *,
        webhook_url: str,
        min_net_profit: float = 50.0,
        min_roi_percent: float = 20.0,
        critical_net_profit: float = 200.0,
        default_platform: str = "eBay",
        default_shipping: float = 8.0,
        http_client: Any = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not webhook_url:
            raise ValueError("webhook_url is required")
        if min_net_profit < 0:
            raise ValueError("min_net_profit must be >= 0")
        if min_roi_percent < 0:
            raise ValueError("min_roi_percent must be >= 0")
        if critical_net_profit < min_net_profit:
            raise ValueError(
                "critical_net_profit must be >= min_net_profit"
            )

        self._webhook_url = webhook_url
        self._min_net_profit = float(min_net_profit)
        self._min_roi_percent = float(min_roi_percent)
        self._critical_net_profit = float(critical_net_profit)
        self._default_platform = default_platform
        self._default_shipping = float(default_shipping)
        self._timeout = timeout_seconds
        if http_client is None:
            import requests
            http_client = requests
        self._http = http_client

    # ------------------------------------------------------------------
    # Construction from env
    # ------------------------------------------------------------------

    @classmethod
    def from_environment(cls, env: dict[str, str] | None = None):
        """Build from env vars. Returns ``None`` when no webhook URL is
        configured — the gentle "disabled in this environment" path."""
        import os
        env = env if env is not None else os.environ

        url = env.get("ZAPIER_WEBHOOK_URL", "").strip()
        if not url:
            logger.info("phone_alert_disabled_missing_url")
            return None

        def _f(name: str, default: float) -> float:
            val = env.get(name, "").strip()
            if not val:
                return default
            try:
                return float(val)
            except ValueError:
                logger.warning(
                    "phone_alert_env_bad_number",
                    extra={"env_var": name, "value": val, "default": default},
                )
                return default

        return cls(
            webhook_url=url,
            min_net_profit=_f("PHONE_ALERT_MIN_NET", 50.0),
            min_roi_percent=_f("PHONE_ALERT_MIN_ROI", 20.0),
            critical_net_profit=_f("PHONE_ALERT_CRITICAL_NET", 200.0),
            default_platform=env.get(
                "PHONE_ALERT_PLATFORM", "eBay"
            ).strip() or "eBay",
            default_shipping=_f("PHONE_ALERT_SHIPPING", 8.0),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_alert(self, opportunity: Any) -> PhoneAlertResult:
        """Dispatch one ScoredOpportunity to the Zapier webhook.

        Never raises. Filters out opportunities below the configured
        floors so the operator's phone doesn't ring for marginal deals.
        """
        opp_id = getattr(opportunity, "opportunity_id", None)

        try:
            buy = float(getattr(opportunity, "min_price", 0.0))
            resale = float(getattr(opportunity, "max_price", 0.0))
            fee, net, roi = self._calc_profit(buy, resale)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "phone_alert_calc_failed",
                extra={
                    "opportunity_id": opp_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return PhoneAlertResult(
                status="failed",
                opportunity_id=opp_id,
                reason="calc_error",
            )

        if net < self._min_net_profit:
            return PhoneAlertResult(
                status="skipped",
                opportunity_id=opp_id,
                reason=f"net_below_floor (${net} < ${self._min_net_profit})",
            )
        if roi < self._min_roi_percent:
            return PhoneAlertResult(
                status="skipped",
                opportunity_id=opp_id,
                reason=f"roi_below_floor ({roi}% < {self._min_roi_percent}%)",
            )

        payload = self._build_payload(
            opportunity=opportunity,
            buy=buy, resale=resale, fee=fee, net=net, roi=roi,
        )

        try:
            response = self._http.post(
                self._webhook_url,
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning(
                "phone_alert_send_failed",
                extra={
                    "opportunity_id": opp_id,
                    "status_code": status_code,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return PhoneAlertResult(
                status="failed",
                opportunity_id=opp_id,
                reason=f"{type(exc).__name__}",
                last_status_code=status_code,
            )

        logger.info(
            "phone_alert_delivered",
            extra={
                "opportunity_id": opp_id,
                "net_profit": net,
                "roi": roi,
                "priority": payload["alert_priority"],
            },
        )
        return PhoneAlertResult(
            status="delivered",
            opportunity_id=opp_id,
            last_status_code=200,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _calc_profit(
        self, buy: float, resale: float
    ) -> tuple[float, float, float]:
        fee_rate = _PLATFORM_FEES.get(self._default_platform, 0.0)
        fee = round(resale * fee_rate, 2)
        net = round(resale - buy - fee - self._default_shipping, 2)
        roi = round((net / buy) * 100, 1) if buy > 0 else 0.0
        return fee, net, roi

    def _build_payload(
        self,
        *,
        opportunity: Any,
        buy: float,
        resale: float,
        fee: float,
        net: float,
        roi: float,
    ) -> dict:
        """Build the flat JSON payload Zapier consumes."""
        product_key = getattr(opportunity, "product_key", "") or "unknown"
        product_name = product_key.title()
        sources = getattr(opportunity, "sources", []) or []
        listings = getattr(opportunity, "listings", []) or []

        # Find cheapest (buy side) and most expensive (resell side)
        # listings so we can attach URLs the AI voice script can mention.
        buy_source = ""
        buy_url = ""
        resell_source = ""
        resell_url = ""
        if listings:
            try:
                cheapest = min(
                    listings,
                    key=lambda lst: getattr(lst, "price", float("inf")),
                )
                buy_source = getattr(cheapest, "source", "") or ""
                buy_url = getattr(cheapest, "url", "") or ""
            except Exception:  # noqa: BLE001
                pass
            try:
                priciest = max(
                    listings,
                    key=lambda lst: getattr(lst, "price", float("-inf")),
                )
                resell_source = getattr(priciest, "source", "") or ""
                resell_url = getattr(priciest, "url", "") or ""
            except Exception:  # noqa: BLE001
                pass

        priority = (
            "critical" if net >= self._critical_net_profit else "high"
        )

        detected_at = getattr(opportunity, "detected_at", None)
        if isinstance(detected_at, datetime):
            detected_at_iso = detected_at.isoformat()
        elif detected_at:
            detected_at_iso = str(detected_at)
        else:
            detected_at_iso = datetime.now(timezone.utc).isoformat()

        voice_script = self._build_voice_script(
            product_name=product_name,
            buy=buy, buy_source=buy_source,
            resell=resale, resell_source=resell_source,
            net=net, roi=roi,
            platform=self._default_platform,
            priority=priority,
        )

        return {
            "alert_type": "high_profit_deal",
            "alert_priority": priority,
            "product_name": product_name,
            "product_key": product_key,
            "platform": self._default_platform,
            "buy_price_usd": round(buy, 2),
            "buy_source": buy_source,
            "buy_url": buy_url,
            "resell_price_usd": round(resale, 2),
            "resell_source": resell_source,
            "resell_url": resell_url,
            "marketplace_fee_usd": round(fee, 2),
            "shipping_usd": round(self._default_shipping, 2),
            "net_profit_usd": round(net, 2),
            "roi_percent": round(roi, 1),
            "sources": list(sources),
            "detected_at": detected_at_iso,
            "voice_script": voice_script,
        }

    @staticmethod
    def _build_voice_script(
        *,
        product_name: str,
        buy: float, buy_source: str,
        resell: float, resell_source: str,
        net: float, roi: float,
        platform: str,
        priority: str,
    ) -> str:
        """Render the script the AI voice agent reads aloud during the
        call. Plain English, no markup, ~15-20 seconds of speech."""
        opener = (
            "Heads up — AACE just found a critical-margin deal."
            if priority == "critical"
            else "Hi, this is AACE with a high-margin deal."
        )
        buy_clause = (
            f"You can buy it for ${buy:,.2f}"
            + (f" on {buy_source}." if buy_source else ".")
        )
        resell_clause = (
            f"It's listed for ${resell:,.2f}"
            + (f" on {resell_source}" if resell_source else "")
            + f", and after {platform} fees and shipping you net "
            + f"${net:,.2f}, which is a {roi:.0f}% return on the buy price."
        )
        closer = "Want me to mark this as actioned in the dashboard?"
        return f"{opener} The product is {product_name}. {buy_clause} {resell_clause} {closer}"
