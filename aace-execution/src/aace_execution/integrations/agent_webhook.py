"""Outbound webhook to the AI agent.

After the pipeline scores an opportunity, this module ships it to the
external AI agent that handles user-facing notifications (Slack, email,
SMS, etc — AACE itself does not do any of that; the agent owns it).

Wire contract:

    - POST to ``AGENT_WEBHOOK_URL`` (env)
    - JSON body, opportunity-shaped (see ``WebhookPayload``)
    - ``X-AACE-Signature: sha256=<hex>`` header — HMAC-SHA256 of the
      raw body bytes, signed with ``AGENT_WEBHOOK_SECRET``. The agent
      must verify this before trusting the payload.
    - Exponential backoff on transient failure (5xx, 429, network err)
    - Hard dedup: never send the same ``opportunity_id`` twice within
      24h. The dedup store is injectable — tests use an in-memory
      implementation; Day 5 will add a Postgres-backed one using the
      ``webhook_deliveries`` table.

Non-goals (intentional):

    - No async / queue. The scheduler tick sends synchronously.
    - No agent-side acknowledgement beyond HTTP 2xx.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WebhookPayload:
    """A scored opportunity ready to send to the agent.

    Built by the worker (Day 5) from a ``MatchGroup`` + the pipeline's
    scoring result. The shape here is the wire contract — changing
    fields requires an agent-side update.
    """

    opportunity_id: str            # globally unique; dedup key
    product_key: str
    sources: list[str]             # e.g. ["slickdeals", "dealnews"]
    listings: list[dict[str, Any]]  # one summary per source observation
    score: float                   # pipeline-assigned score, 0..1
    detected_at: datetime          # when the discrepancy was detected
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookDeliveryResult:
    """Outcome of a single ``send()`` call."""

    status: str                    # "delivered" | "deduped" | "failed"
    opportunity_id: str
    attempts: int
    last_status_code: int | None
    last_error: str | None
    delivered_at: datetime | None


# ---------------------------------------------------------------------------
# Dedup store
# ---------------------------------------------------------------------------


@runtime_checkable
class WebhookDedupStore(Protocol):
    """Tracks recent successful deliveries to avoid double-sending."""

    def was_recently_sent(
        self, opportunity_id: str, *, within_hours: int = 24
    ) -> bool: ...

    def mark_sent(
        self,
        opportunity_id: str,
        *,
        status_code: int,
        attempts: int,
        when: datetime | None = None,
    ) -> None: ...


class InMemoryWebhookDedupStore:
    """In-memory dedup. Used for tests and single-process dev.

    Day 5 will add a Postgres-backed implementation backed by the
    ``webhook_deliveries`` table; same interface, just persistent
    across restarts.
    """

    def __init__(self) -> None:
        self._sent: dict[str, datetime] = {}

    def was_recently_sent(
        self, opportunity_id: str, *, within_hours: int = 24
    ) -> bool:
        sent_at = self._sent.get(opportunity_id)
        if sent_at is None:
            return False
        age_seconds = (datetime.now(timezone.utc) - sent_at).total_seconds()
        return age_seconds < within_hours * 3600

    def mark_sent(
        self,
        opportunity_id: str,
        *,
        status_code: int,
        attempts: int,
        when: datetime | None = None,
    ) -> None:
        self._sent[opportunity_id] = when or datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


def sign_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 of ``body`` with ``secret``, hex-encoded.

    Returns the header value: ``"sha256=<hex>"``. The agent must
    recompute and constant-time-compare this on every inbound request.
    """
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class AgentWebhookClient:
    """Sends scored opportunities to the agent webhook.

    Lifecycle of a ``send()`` call:

        1. Check dedup. If already sent recently, return "deduped".
        2. Serialize + HMAC-sign the payload.
        3. HTTP POST. If 2xx, mark sent + return "delivered".
        4. Non-retryable 4xx (not 429): give up immediately, "failed".
        5. Retryable (5xx, 429, network): back off + retry.
        6. After ``max_attempts`` retries, return "failed".

    A failed delivery is NOT marked in the dedup store — the next
    scheduler tick should retry the same opportunity.
    """

    def __init__(
        self,
        webhook_url: str,
        webhook_secret: str,
        *,
        dedup_store: WebhookDedupStore | None = None,
        http_client: Any = None,
        max_attempts: int = 4,
        backoff_seconds: tuple[float, ...] = (1.0, 5.0, 30.0, 300.0),
        timeout_seconds: float = 30.0,
        sleep_fn: Callable[[float], None] = time.sleep,
        dedup_window_hours: int = 24,
    ) -> None:
        if not webhook_url:
            raise ValueError("webhook_url is required")
        if not webhook_secret:
            raise ValueError("webhook_secret is required")
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {max_attempts!r}")

        self._url = webhook_url
        self._secret = webhook_secret
        self._dedup: WebhookDedupStore = (
            dedup_store if dedup_store is not None else InMemoryWebhookDedupStore()
        )
        self._http = http_client  # may be None; built lazily from httpx
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._timeout = timeout_seconds
        self._sleep = sleep_fn
        self._dedup_window_hours = dedup_window_hours

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(self, payload: WebhookPayload) -> WebhookDeliveryResult:
        if self._dedup.was_recently_sent(
            payload.opportunity_id, within_hours=self._dedup_window_hours
        ):
            logger.info(
                "webhook_skip_deduped",
                extra={"opportunity_id": payload.opportunity_id},
            )
            return WebhookDeliveryResult(
                status="deduped",
                opportunity_id=payload.opportunity_id,
                attempts=0,
                last_status_code=None,
                last_error=None,
                delivered_at=None,
            )

        body = self._serialize(payload)
        headers = {
            "Content-Type": "application/json",
            "X-AACE-Signature": sign_payload(self._secret, body),
            "User-Agent": "AACE/0.1",
        }

        last_status_code: int | None = None
        last_error: str | None = None
        attempt = 0

        for attempt in range(1, self._max_attempts + 1):
            try:
                resp = self._post(body, headers)
                last_status_code = resp.status_code

                # Success
                if 200 <= resp.status_code < 300:
                    self._dedup.mark_sent(
                        payload.opportunity_id,
                        status_code=resp.status_code,
                        attempts=attempt,
                    )
                    logger.info(
                        "webhook_delivered",
                        extra={
                            "opportunity_id": payload.opportunity_id,
                            "attempts": attempt,
                            "status_code": resp.status_code,
                        },
                    )
                    return WebhookDeliveryResult(
                        status="delivered",
                        opportunity_id=payload.opportunity_id,
                        attempts=attempt,
                        last_status_code=resp.status_code,
                        last_error=None,
                        delivered_at=datetime.now(timezone.utc),
                    )

                # Non-retryable 4xx (everything except 429)
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    last_error = f"HTTP {resp.status_code} (non-retryable)"
                    break

                # Retryable: 5xx, 429
                last_error = f"HTTP {resp.status_code}"

            except Exception as exc:
                # Network / TLS / DNS errors all retryable
                last_error = f"{type(exc).__name__}: {exc}"

            # Sleep before the next attempt (skip after the last).
            if attempt < self._max_attempts:
                idx = min(attempt - 1, len(self._backoff) - 1)
                self._sleep(self._backoff[idx])

        logger.warning(
            "webhook_failed",
            extra={
                "opportunity_id": payload.opportunity_id,
                "attempts": attempt,
                "last_status_code": last_status_code,
                "last_error": last_error,
            },
        )
        return WebhookDeliveryResult(
            status="failed",
            opportunity_id=payload.opportunity_id,
            attempts=attempt,
            last_status_code=last_status_code,
            last_error=last_error,
            delivered_at=None,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _serialize(self, payload: WebhookPayload) -> bytes:
        """JSON-encode the payload deterministically.

        ``sort_keys=True`` keeps the body byte-stable across runs, which
        means the same payload always produces the same signature. That
        makes signature verification on the agent side trivially
        debuggable.
        """
        return json.dumps(
            dataclasses.asdict(payload),
            default=_json_default,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _post(self, body: bytes, headers: dict[str, str]) -> Any:
        if self._http is not None:
            return self._http.post(
                self._url,
                content=body,
                headers=headers,
                timeout=self._timeout,
            )
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "httpx is required to use AgentWebhookClient"
            ) from exc
        with httpx.Client(timeout=self._timeout) as client:
            return client.post(self._url, content=body, headers=headers)


def _json_default(obj: Any) -> Any:
    """JSON serializer for types ``json`` doesn't handle natively."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON-serializable"
    )
