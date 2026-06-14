"""Daily email digest of AACE opportunities.

Sends one HTML email per day summarising the top N most profitable
cross-source matches AACE found in the last 24 hours. Designed for
manager visibility — the operator (and optionally the manager) wakes
up to a clean summary in their inbox.

Why this exists alongside the other channels:

* The ``agent_webhook`` and ``ntfy_notifier`` channels are real-time
  per-opportunity pings — good for "act now" alerts but noisy for a
  daily review.
* This module is the opposite — once per day, batched, ranked, with
  context. Better for stakeholders who want signal not noise.

Transport
---------
Uses Python stdlib ``smtplib`` + ``email.mime`` — no third-party
dependencies. Tested with Gmail SMTP (requires an app password, not
the user's regular Google password), but works with any SMTP server
that supports STARTTLS or implicit TLS.

Configuration (all via env, all optional — blank disables digest):

* ``EMAIL_SMTP_HOST``       — e.g. ``smtp.gmail.com``
* ``EMAIL_SMTP_PORT``       — e.g. ``465`` (SSL) or ``587`` (STARTTLS)
* ``EMAIL_USERNAME``        — SMTP auth username (usually the Gmail address)
* ``EMAIL_APP_PASSWORD``    — Gmail App Password (16-char, no spaces)
* ``EMAIL_FROM``            — sender (defaults to ``EMAIL_USERNAME``)
* ``EMAIL_TO``              — comma-separated recipient list
* ``EMAIL_DIGEST_TOP_N``    — how many deals to include (default 10)
* ``EMAIL_DIGEST_MIN_NET_PROFIT``  — filter floor (default 1.00 USD)
* ``EMAIL_DIGEST_MIN_ROI_PERCENT`` — filter floor (default 3.0)
* ``EMAIL_DIGEST_PLATFORM`` — fee/ROI math platform (default ``eBay``)
* ``EMAIL_DIGEST_SHIPPING`` — per-parcel shipping cost (default 8.00)
* ``EMAIL_DIGEST_LOOKBACK_HOURS`` — how far back to look (default 24)
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Iterable

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


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmailDigestResult:
    """Outcome of one digest send attempt."""

    status: str                     # "sent" | "skipped" | "failed" | "disabled"
    sent_at: datetime | None = None
    deal_count: int = 0             # how many opportunities included
    reason: str | None = None       # explanation for skipped/failed


@dataclass(frozen=True)
class _RankedRow:
    """One row of the digest, post-filter and ranked.

    Pure-data; no DB or SMTP coupling here so the formatter is
    trivially unit-testable.
    """

    product_key: str
    sources: str
    buy_price: float
    resale_price: float
    fee: float
    shipping: float
    net_profit: float
    roi_percent: float
    detected_at: datetime


# ---------------------------------------------------------------------------
# The digest itself
# ---------------------------------------------------------------------------


class EmailDigest:
    """Builds + sends the daily AACE summary email."""

    def __init__(
        self,
        *,
        smtp_host: str = "",
        smtp_port: int = 465,
        smtp_username: str = "",
        smtp_app_password: str = "",
        from_addr: str,
        to_addrs: list[str],
        top_n: int = 10,
        min_net_profit: float = 1.0,
        min_roi_percent: float = 3.0,
        default_platform: str = "eBay",
        default_shipping: float = 8.0,
        lookback_hours: int = 24,
        smtp_client_factory=None,    # injectable for tests
        # Mandrill transport (preferred when ``mandrill_api_key`` is set —
        # fewer moving parts than SMTP, cleaner deliverability story).
        # When set, SMTP fields above are optional.
        mandrill_api_key: str = "",
        mandrill_from_name: str = "AACE",
        mandrill_http_client=None,   # injectable for tests
    ) -> None:
        # Transport mode is decided here: Mandrill wins if an API key is
        # set; otherwise we require the full SMTP credential set. Tests
        # can inject either layer's transport.
        use_mandrill = bool(mandrill_api_key)

        if not use_mandrill:
            if not smtp_host:
                raise ValueError("smtp_host is required when Mandrill key is absent")
            if not (0 < smtp_port < 65536):
                raise ValueError("smtp_port must be in 1..65535")
            if not smtp_username:
                raise ValueError("smtp_username is required when Mandrill key is absent")
            if not smtp_app_password:
                raise ValueError("smtp_app_password is required when Mandrill key is absent")

        if not from_addr:
            raise ValueError("from_addr is required")
        if not to_addrs:
            raise ValueError("to_addrs must contain at least one address")
        if top_n < 1:
            raise ValueError("top_n must be >= 1")
        if min_net_profit < 0:
            raise ValueError("min_net_profit must be >= 0")
        if min_roi_percent < 0:
            raise ValueError("min_roi_percent must be >= 0")
        if lookback_hours < 1:
            raise ValueError("lookback_hours must be >= 1")

        # SMTP-side
        self._smtp_host = smtp_host
        self._smtp_port = int(smtp_port)
        self._smtp_username = smtp_username
        self._smtp_app_password = smtp_app_password
        self._smtp_client_factory = smtp_client_factory or _default_smtp_factory

        # Mandrill-side
        self._mandrill_api_key = mandrill_api_key
        self._mandrill_from_name = mandrill_from_name or "AACE"
        if mandrill_http_client is None:
            import requests
            mandrill_http_client = requests
        self._mandrill_http = mandrill_http_client
        self._use_mandrill = use_mandrill

        # Shared
        self._from_addr = from_addr
        self._to_addrs = list(to_addrs)
        self._top_n = int(top_n)
        self._min_net_profit = float(min_net_profit)
        self._min_roi_percent = float(min_roi_percent)
        self._default_platform = default_platform
        self._default_shipping = float(default_shipping)
        self._lookback_hours = int(lookback_hours)

    # ------------------------------------------------------------------
    # Construction from env
    # ------------------------------------------------------------------

    @classmethod
    def from_environment(cls, env: dict[str, str] | None = None):
        """Build from env vars. Returns ``None`` if the digest is not
        configured in this environment (most fields missing). Returning
        ``None`` instead of raising keeps local-dev workflows simple.
        """
        import os
        env = env if env is not None else os.environ

        host = env.get("EMAIL_SMTP_HOST", "").strip()
        username = env.get("EMAIL_USERNAME", "").strip()
        password = env.get("EMAIL_APP_PASSWORD", "").strip()
        to_raw = env.get("EMAIL_TO", "").strip()
        mandrill_key = env.get("MANDRILL_API_KEY", "").strip()
        mandrill_from_name = env.get(
            "MANDRILL_FROM_NAME", "AACE"
        ).strip() or "AACE"

        # The digest can run via Mandrill OR SMTP. Recipients + from-addr
        # are always required. The chosen transport must also be fully
        # configured.
        if not to_raw:
            logger.info("email_digest_disabled_missing_to")
            return None
        if not mandrill_key and not (host and username and password):
            logger.info("email_digest_disabled_no_transport")
            return None

        # Parse port. Default 465 (implicit SSL) — Gmail's recommended.
        try:
            port = int(env.get("EMAIL_SMTP_PORT", "465").strip() or "465")
        except ValueError:
            logger.warning(
                "email_smtp_port_invalid",
                extra={
                    "env_var": "EMAIL_SMTP_PORT",
                    "value": env.get("EMAIL_SMTP_PORT"),
                    "default": 465,
                },
            )
            port = 465

        # from_addr defaults to the SMTP username when SMTP is configured;
        # if only Mandrill is set, EMAIL_FROM must be supplied explicitly
        # (Mandrill won't know what your sender address is).
        from_addr = (
            env.get("EMAIL_FROM", "").strip()
            or username
            or env.get("MANDRILL_FROM_EMAIL", "").strip()
        )
        if not from_addr:
            logger.info("email_digest_disabled_missing_from")
            return None
        to_addrs = [
            addr.strip() for addr in to_raw.split(",") if addr.strip()
        ]

        def _f(key: str, default: float) -> float:
            val = env.get(key, "").strip()
            if not val:
                return default
            try:
                return float(val)
            except ValueError:
                logger.warning(
                    "email_digest_env_bad_number",
                    extra={"env_var": key, "value": val, "default": default},
                )
                return default

        def _i(key: str, default: int) -> int:
            val = env.get(key, "").strip()
            if not val:
                return default
            try:
                return int(val)
            except ValueError:
                logger.warning(
                    "email_digest_env_bad_int",
                    extra={"env_var": key, "value": val, "default": default},
                )
                return default

        return cls(
            smtp_host=host,
            smtp_port=port,
            smtp_username=username,
            smtp_app_password=password,
            from_addr=from_addr,
            to_addrs=to_addrs,
            top_n=_i("EMAIL_DIGEST_TOP_N", 10),
            min_net_profit=_f("EMAIL_DIGEST_MIN_NET_PROFIT", 1.0),
            min_roi_percent=_f("EMAIL_DIGEST_MIN_ROI_PERCENT", 3.0),
            default_platform=env.get(
                "EMAIL_DIGEST_PLATFORM", "eBay"
            ).strip() or "eBay",
            default_shipping=_f("EMAIL_DIGEST_SHIPPING", 8.0),
            lookback_hours=_i("EMAIL_DIGEST_LOOKBACK_HOURS", 24),
            mandrill_api_key=mandrill_key,
            mandrill_from_name=mandrill_from_name,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_digest(
        self,
        opportunities: Iterable[dict[str, Any]],
        *,
        now: datetime | None = None,
    ) -> EmailDigestResult:
        """Build + send the digest from an iterable of opportunity dicts.

        Each dict should expose the keys produced by the
        ``worker_opportunities`` table — see :func:`_row_to_ranked` for
        the exact field names used.

        Never raises into the caller — SMTP failures return an
        :class:`EmailDigestResult` with ``status="failed"`` and a reason.
        """
        now = now or datetime.now(timezone.utc)

        try:
            ranked = self._filter_and_rank(opportunities)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "email_digest_rank_failed",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )
            return EmailDigestResult(
                status="failed",
                reason=f"rank_error:{type(exc).__name__}",
            )

        if not ranked:
            return EmailDigestResult(
                status="skipped",
                reason="no_qualifying_opportunities",
            )

        # Build subject + bodies once. SMTP wraps in MIMEMultipart;
        # Mandrill takes the strings directly via JSON.
        subject = (
            f"AACE — {len(ranked)} profitable deals in the last "
            f"{self._lookback_hours}h"
        )
        try:
            plain = self._build_plain_text(ranked, now=now)
            html = self._build_html(ranked, now=now)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "email_digest_build_failed",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )
            return EmailDigestResult(
                status="failed",
                reason=f"build_error:{type(exc).__name__}",
            )

        transport = "mandrill" if self._use_mandrill else "smtp"
        try:
            if self._use_mandrill:
                self._send_via_mandrill(
                    subject=subject, html=html, text=plain,
                )
            else:
                msg = self._compose_mime(
                    subject=subject, html=html, text=plain,
                )
                self._send_via_smtp(msg)
        except Exception as exc:  # noqa: BLE001 — never crash worker
            logger.warning(
                "email_digest_send_failed",
                extra={
                    "transport": transport,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return EmailDigestResult(
                status="failed",
                reason=f"{transport}_error:{type(exc).__name__}",
            )

        logger.info(
            "email_digest_sent",
            extra={
                "transport": transport,
                "deal_count": len(ranked),
                "to": self._to_addrs,
            },
        )
        return EmailDigestResult(
            status="sent",
            sent_at=now,
            deal_count=len(ranked),
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

    def _filter_and_rank(
        self, opportunities: Iterable[dict[str, Any]]
    ) -> list[_RankedRow]:
        out: list[_RankedRow] = []
        for opp in opportunities:
            try:
                row = self._row_to_ranked(opp)
            except (KeyError, TypeError, ValueError):
                # Defensive — bad row shape shouldn't kill the digest.
                continue
            if row is None:
                continue
            if row.net_profit < self._min_net_profit:
                continue
            if row.roi_percent < self._min_roi_percent:
                continue
            out.append(row)
        out.sort(key=lambda r: r.net_profit, reverse=True)
        return out[: self._top_n]

    def _row_to_ranked(self, opp: dict[str, Any]) -> _RankedRow | None:
        buy = float(opp.get("min_price") or 0)
        resale = float(opp.get("max_price") or 0)
        if buy <= 0 or resale <= 0:
            return None
        fee, net, roi = self._calc_profit(buy, resale)
        detected = opp.get("detected_at")
        if isinstance(detected, str):
            try:
                detected = datetime.fromisoformat(
                    detected.replace("Z", "+00:00")
                )
            except ValueError:
                detected = None
        return _RankedRow(
            product_key=str(opp.get("product_key") or "unknown"),
            sources=str(opp.get("sources") or "?"),
            buy_price=buy,
            resale_price=resale,
            fee=fee,
            shipping=self._default_shipping,
            net_profit=net,
            roi_percent=roi,
            detected_at=detected or datetime.now(timezone.utc),
        )

    def _compose_mime(
        self, *, subject: str, html: str, text: str
    ) -> MIMEMultipart:
        """Wrap pre-built bodies in a MIME multipart message for SMTP."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from_addr
        msg["To"] = ", ".join(self._to_addrs)
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        return msg

    def _build_plain_text(
        self, ranked: list[_RankedRow], *, now: datetime
    ) -> str:
        lines = [
            f"AACE Daily Digest — {now.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            f"Top {len(ranked)} profitable opportunities on "
            f"{self._default_platform} after fees + "
            f"${self._default_shipping:.2f} shipping.",
            "",
        ]
        for i, row in enumerate(ranked, 1):
            lines.extend([
                f"{i}. {row.product_key.title()}",
                f"   Sources:  {row.sources}",
                f"   Buy:      ${row.buy_price:,.2f}",
                f"   Resell:   ${row.resale_price:,.2f}",
                f"   Fee:      ${row.fee:,.2f}  ({self._default_platform})",
                f"   Shipping: ${row.shipping:,.2f}",
                f"   NET:      ${row.net_profit:,.2f}  ({row.roi_percent:.1f}% ROI)",
                "",
            ])
        return "\n".join(lines)

    def _build_html(
        self, ranked: list[_RankedRow], *, now: datetime
    ) -> str:
        """Inline-styled HTML table. No external CSS — every email
        client requires inline styles for reliable rendering.
        """
        header_cell = (
            'style="padding:8px 12px;background:#1E2761;color:#fff;'
            'font-family:Arial,sans-serif;font-size:13px;text-align:left;"'
        )
        cell = (
            'style="padding:8px 12px;font-family:Arial,sans-serif;'
            'font-size:13px;border-bottom:1px solid #E5E7EB;"'
        )
        cell_right = (
            'style="padding:8px 12px;font-family:Arial,sans-serif;'
            'font-size:13px;border-bottom:1px solid #E5E7EB;text-align:right;"'
        )
        net_cell = (
            'style="padding:8px 12px;font-family:Arial,sans-serif;'
            'font-size:13px;border-bottom:1px solid #E5E7EB;text-align:right;'
            'background:#E6F4EA;color:#1B7F3A;font-weight:bold;"'
        )

        rows_html = []
        for i, row in enumerate(ranked, 1):
            rows_html.append(
                f"<tr>"
                f"<td {cell}>{i}</td>"
                f"<td {cell}>{_html_escape(row.product_key.title())}</td>"
                f"<td {cell}>{_html_escape(row.sources)}</td>"
                f"<td {cell_right}>${row.buy_price:,.2f}</td>"
                f"<td {cell_right}>${row.resale_price:,.2f}</td>"
                f"<td {cell_right}>${row.fee:,.2f}</td>"
                f"<td {net_cell}>${row.net_profit:,.2f}<br>"
                f"<span style='font-weight:normal;font-size:11px;'>"
                f"{row.roi_percent:.1f}% ROI</span></td>"
                f"</tr>"
            )

        return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:24px;background:#F9FAFB;font-family:Arial,sans-serif;color:#1A1A1A;">
  <div style="max-width:780px;margin:auto;background:#FFFFFF;border-radius:8px;
              border:1px solid #E5E7EB;overflow:hidden;">
    <div style="padding:20px 24px;background:#1E2761;color:#FFFFFF;">
      <h1 style="margin:0;font-size:20px;">AACE — Daily Profit Digest</h1>
      <p style="margin:6px 0 0;font-size:13px;opacity:0.9;">
        {_html_escape(now.strftime("%A, %B %d %Y · %H:%M UTC"))}
      </p>
    </div>
    <div style="padding:20px 24px;">
      <p style="font-size:14px;margin-top:0;">
        Top <strong>{len(ranked)}</strong> profitable opportunities found by AACE
        in the last <strong>{self._lookback_hours} hours</strong>, ranked by
        net profit on <strong>{_html_escape(self._default_platform)}</strong>
        after the published seller fee
        (<strong>{_PLATFORM_FEES.get(self._default_platform, 0.0)*100:.2f}%</strong>)
        and <strong>${self._default_shipping:.2f}</strong> shipping.
      </p>
      <table cellspacing="0" cellpadding="0" border="0"
             style="width:100%;border-collapse:collapse;margin-top:12px;">
        <thead>
          <tr>
            <th {header_cell}>#</th>
            <th {header_cell}>Product</th>
            <th {header_cell}>Sources</th>
            <th {header_cell} style="text-align:right;">Buy</th>
            <th {header_cell} style="text-align:right;">Resell</th>
            <th {header_cell} style="text-align:right;">Fee</th>
            <th {header_cell} style="text-align:right;">Net / ROI</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows_html)}
        </tbody>
      </table>
      <p style="margin-top:20px;font-size:12px;color:#6B7280;">
        Resale prices are sourced from the resale-comps client
        (Keepa / SerpAPI / mock fallback). Fees reflect each marketplace&rsquo;s
        published 2026 seller terms; real per-listing fees may vary by category.
      </p>
    </div>
  </div>
</body></html>"""

    _MANDRILL_URL = "https://mandrillapp.com/api/1.0/messages/send.json"

    def _send_via_mandrill(
        self, *, subject: str, html: str, text: str
    ) -> None:
        """Send via Mandrill's REST API.

        Mandrill expects:
            POST https://mandrillapp.com/api/1.0/messages/send.json
            {
              "key": "<MANDRILL_API_KEY>",
              "message": {
                "from_email": "...", "from_name": "AACE",
                "to": [{"email": "...", "type": "to"}, ...],
                "subject": "...",
                "html": "<...>", "text": "..."
              }
            }

        See https://mailchimp.com/developer/transactional/api/messages/send-new-message/

        Raises on any non-2xx response or transport failure; the caller
        (``send_digest``) wraps this in a try/except and returns a
        :class:`EmailDigestResult` with ``status="failed"``.
        """
        payload = {
            "key": self._mandrill_api_key,
            "message": {
                "from_email": self._from_addr,
                "from_name": self._mandrill_from_name,
                "to": [
                    {"email": addr, "type": "to"} for addr in self._to_addrs
                ],
                "subject": subject,
                "html": html,
                "text": text,
                # Bookkeeping headers — show up in Mandrill's UI so we
                # can tell digest emails apart from any other Mandrill
                # traffic on the same account.
                "tags": ["aace", "daily-digest"],
            },
        }
        response = self._mandrill_http.post(
            self._MANDRILL_URL,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        # Mandrill returns a list with per-recipient delivery results.
        # If every entry has status != "sent"/"queued", treat as failure
        # so we get a useful log line.
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            body = None
        if isinstance(body, list):
            statuses = [r.get("status") for r in body if isinstance(r, dict)]
            if statuses and not any(
                s in ("sent", "queued", "scheduled") for s in statuses
            ):
                raise RuntimeError(
                    f"Mandrill rejected all recipients: {statuses}"
                )

    def _send_via_smtp(self, msg: MIMEMultipart) -> None:
        """Send via SMTP. Uses implicit TLS on port 465 (Gmail default),
        STARTTLS on port 587, plain SMTP otherwise.
        """
        client = self._smtp_client_factory(
            host=self._smtp_host, port=self._smtp_port
        )
        try:
            if self._smtp_port == 587:
                client.ehlo()
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            client.login(self._smtp_username, self._smtp_app_password)
            client.send_message(msg)
        finally:
            try:
                client.quit()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_smtp_factory(*, host: str, port: int):
    """Open an SMTP connection appropriate for the given port.

    Port 465 -> implicit TLS via ``smtplib.SMTP_SSL``.
    Anything else -> plain ``smtplib.SMTP`` (caller is expected to
    upgrade with STARTTLS if needed).
    """
    if port == 465:
        return smtplib.SMTP_SSL(
            host=host, port=port,
            context=ssl.create_default_context(),
            timeout=30,
        )
    return smtplib.SMTP(host=host, port=port, timeout=30)


def _html_escape(text: str) -> str:
    """Tiny stand-in for ``html.escape`` — kept inline so this module
    has zero ``html`` import overhead and is trivially auditable."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
