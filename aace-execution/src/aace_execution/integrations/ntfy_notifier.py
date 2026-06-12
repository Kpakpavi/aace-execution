"""ntfy.sh push notification integration.

Sends a mobile push notification (via the free public ntfy.sh server
or a self-hosted instance) for each profitable AACE opportunity.

Why ntfy.sh — and why it's a better fit than Telegram for AACE:
  * Zero signup, zero account. Subscribers pick a topic name in the
    ntfy app on phone and they're done; publishers POST to that topic.
  * No anti-spam classifier. Telegram's BotFather refuses new bots
    when its heuristics fire; ntfy has no such gating.
  * Cleartext JSON API — same testability story as Telegram.
  * Open source — can be self-hosted if/when we outgrow the free pool.

This module mirrors :mod:`telegram_notifier` exactly so the worker can
treat both as interchangeable secondary delivery channels.

To configure:
  * ``NTFY_TOPIC``               — required, the topic to publish to.
                                   Pick something unguessable since
                                   topics are public on the free server
                                   (e.g. ``aace-kpakpavi-deals-9f3k2q``).
  * ``NTFY_SERVER`` (optional)   — defaults to ``https://ntfy.sh``.
                                   Override for a self-hosted instance.
  * ``NTFY_MIN_NET_PROFIT`` (optional)  — float, default 1.00 USD
  * ``NTFY_MIN_ROI_PERCENT`` (optional) — float, default 3.0 (=3%)
  * ``NTFY_DEFAULT_PLATFORM`` (optional) — defaults to "eBay"
  * ``NTFY_DEFAULT_SHIPPING`` (optional) — defaults to 8.0 USD
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# Keep aligned with dashboard/app.py PLATFORM_FEES. Duplicated locally
# so this module can run without importing the Streamlit-side code.
_PLATFORM_FEES: dict[str, float] = {
    "eBay": 0.1325,
    "Amazon": 0.15,
    "StockX": 0.125,
    "Mercari": 0.129,
    "FB Marketplace (National)": 0.05,
    "FB Marketplace (Local)": 0.0,
}


@dataclass(frozen=True)
class NtfyDeliveryResult:
    """Outcome of one NTFY publish attempt."""

    status: str                  # "delivered" | "skipped" | "failed" | "disabled"
    opportunity_id: str | None
    reason: str | None = None
    last_status_code: int | None = None


class NtfyNotifier:
    """Posts AACE opportunities to a public or self-hosted ntfy.sh topic.

    Construction is via ``from_environment`` in the worker, or directly
    for tests. ``send_opportunity`` never raises — failures return a
    :class:`NtfyDeliveryResult` with status ``"failed"`` so the worker
    tick is unaffected.
    """

    def __init__(
        self,
        *,
        topic: str,
        server: str = "https://ntfy.sh",
        min_net_profit: float = 1.0,
        min_roi_percent: float = 3.0,
        default_platform: str = "eBay",
        default_shipping: float = 8.0,
        http_client: Any = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not topic:
            raise ValueError("topic is required")
        if not server:
            raise ValueError("server is required")
        if min_net_profit < 0:
            raise ValueError("min_net_profit must be >= 0")
        if min_roi_percent < 0:
            raise ValueError("min_roi_percent must be >= 0")

        self._topic = topic.strip()
        # Normalize — accept both "ntfy.sh" and "https://ntfy.sh"
        self._server = server.strip().rstrip("/")
        if "://" not in self._server:
            self._server = "https://" + self._server
        self._min_net_profit = float(min_net_profit)
        self._min_roi_percent = float(min_roi_percent)
        self._default_platform = default_platform
        self._default_shipping = float(default_shipping)
        self._timeout = timeout_seconds
        if http_client is None:
            import requests
            http_client = requests
        self._http = http_client

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_environment(cls, env: dict[str, str] | None = None):
        """Build from env vars. Returns ``None`` when ``NTFY_TOPIC`` is
        absent — that's the gentle "disabled in this environment" path.
        """
        import os
        env = env if env is not None else os.environ

        topic = env.get("NTFY_TOPIC", "").strip()
        if not topic:
            logger.info("ntfy_notifier_disabled_missing_topic")
            return None

        server = env.get("NTFY_SERVER", "https://ntfy.sh").strip() or "https://ntfy.sh"

        def _f(name: str, default: float) -> float:
            val = env.get(name, "").strip()
            if not val:
                return default
            try:
                return float(val)
            except ValueError:
                logger.warning(
                    "ntfy_env_bad_number",
                    extra={"name": name, "value": val, "default": default},
                )
                return default

        return cls(
            topic=topic,
            server=server,
            min_net_profit=_f("NTFY_MIN_NET_PROFIT", 1.0),
            min_roi_percent=_f("NTFY_MIN_ROI_PERCENT", 3.0),
            default_platform=env.get(
                "NTFY_DEFAULT_PLATFORM", "eBay"
            ).strip() or "eBay",
            default_shipping=_f("NTFY_DEFAULT_SHIPPING", 8.0),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_opportunity(self, opportunity: Any) -> NtfyDeliveryResult:
        """Send one ScoredOpportunity to the configured ntfy topic.

        Never raises. Return value tells the caller whether the push
        actually went out (``delivered``), was filtered out by the
        thresholds (``skipped``), or hit an error (``failed``).
        """
        opp_id = getattr(opportunity, "opportunity_id", None)

        try:
            buy = float(getattr(opportunity, "min_price", 0.0))
            resale = float(getattr(opportunity, "max_price", 0.0))
            fee, net, roi = self._calc_profit(buy, resale)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ntfy_calc_failed",
                extra={
                    "opportunity_id": opp_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return NtfyDeliveryResult(
                status="failed",
                opportunity_id=opp_id,
                reason="calc_error",
            )

        if net < self._min_net_profit:
            return NtfyDeliveryResult(
                status="skipped",
                opportunity_id=opp_id,
                reason=f"net_below_floor (${net} < ${self._min_net_profit})",
            )
        if roi < self._min_roi_percent:
            return NtfyDeliveryResult(
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
                self._server,
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning(
                "ntfy_send_failed",
                extra={
                    "opportunity_id": opp_id,
                    "status_code": status_code,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return NtfyDeliveryResult(
                status="failed",
                opportunity_id=opp_id,
                reason=f"{type(exc).__name__}",
                last_status_code=status_code,
            )

        logger.info(
            "ntfy_delivered",
            extra={
                "opportunity_id": opp_id,
                "topic": self._topic,
                "net_profit": net,
                "roi": roi,
            },
        )
        return NtfyDeliveryResult(
            status="delivered",
            opportunity_id=opp_id,
            last_status_code=200,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _calc_profit(self, buy: float, resale: float) -> tuple[float, float, float]:
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
        """Build the ntfy.sh JSON publish payload.

        See https://docs.ntfy.sh/publish/#publish-as-json
        """
        product_key = getattr(opportunity, "product_key", "") or "unknown product"
        sources = getattr(opportunity, "sources", []) or []
        sources_str = ", ".join(sources) if sources else "?"

        listings = getattr(opportunity, "listings", []) or []
        buy_url = None
        if listings:
            try:
                cheapest = min(
                    listings,
                    key=lambda listing: getattr(listing, "price", float("inf")),
                )
                buy_url = getattr(cheapest, "url", None)
            except Exception:  # noqa: BLE001
                buy_url = None

        # Priority + tags + title scale with margin size so the operator
        # gets richer mobile-notification context without opening the app.
        if net >= 20.0:
            title = "🔥💰 AACE Deal — Strong Margin"
            priority = 5  # max — bypasses Do Not Disturb on phone
            tags = ["fire", "moneybag"]
        else:
            title = "🔥 AACE Deal Found"
            priority = 4  # high — sound + vibrate
            tags = ["fire"]

        body_lines = [
            product_key.title(),
            "",
            f"Buy ${buy:.2f}  (cheapest of {sources_str})",
            f"Resell ${resale:.2f}  (best observed)",
            "",
            f"On {self._default_platform} after "
            f"{_PLATFORM_FEES.get(self._default_platform, 0.0)*100:.2f}% fee "
            f"+ ${self._default_shipping:.2f} ship:",
            f"Fee ${fee:.2f}",
            f"Net ${net:.2f}  |  ROI {roi:.1f}%",
        ]

        payload: dict = {
            "topic": self._topic,
            "title": title,
            "message": "\n".join(body_lines),
            "priority": priority,
            "tags": tags,
        }
        if buy_url:
            # Tapping the notification opens the deal in the browser.
            payload["click"] = buy_url
        return payload
