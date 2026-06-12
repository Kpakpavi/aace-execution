"""Worker — the scheduled loop that ties AACE together.

Every interval (default 30 minutes):

    1. Run every registered connector to pull fresh listings.
    2. Cross-source match them via ``match_cross_source``.
    3. Score each group; drop those below threshold.
    4. Ship each scored opportunity to the agent webhook.

The worker is the only place in AACE that owns time-of-day (via the
scheduler) and the only place that talks to the outside world via the
webhook. Everything else is pure logic, easy to test offline.

Run with:

    python -m aace_execution.worker

Env vars:

    AGENT_WEBHOOK_URL        required
    AGENT_WEBHOOK_SECRET     required
    WORKER_INTERVAL_MINUTES  default 30
    SCORER_MIN_ABS_SPREAD    default 5.0  (dollars)
    SCORER_MIN_PCT_SPREAD    default 0.05 (5%)
    SCORER_PCT_MULTIPLIER    default 2.0
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from aace_execution.connectors.base import (
    BaseConnector,
    ConnectorError,
    NormalizedListing,
)
from aace_execution.integrations.agent_webhook import (
    AgentWebhookClient,
    WebhookDeliveryResult,
    WebhookPayload,
)
from aace_execution.pipeline.cross_source_matcher import (
    match_cross_source_by_tokens,
)
from aace_execution.pipeline.opportunity_scorer import (
    OpportunityScorer,
    ScoredOpportunity,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerRunResult:
    """Outcome of a single ``Worker.run_once()`` invocation."""

    listings_fetched: int
    per_source_counts: dict[str, int] = field(default_factory=dict)
    per_source_errors: dict[str, str] = field(default_factory=dict)
    match_groups: int = 0
    scored_opportunities: int = 0
    delivery_results: list[WebhookDeliveryResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class Worker:
    """Orchestrates fetch -> match -> score -> ship.

    Testable in isolation: all dependencies are injected, and ``run_once``
    swallows per-connector errors so one flaky source doesn't kill the
    tick.
    """

    def __init__(
        self,
        *,
        connectors: Sequence[BaseConnector],
        scorer: OpportunityScorer,
        webhook_client: AgentWebhookClient,
        similarity_threshold: float = 0.6,
        opportunity_writer: Any = None,
        telegram_notifier: Any = None,
        ntfy_notifier: Any = None,
    ) -> None:
        if not connectors:
            raise ValueError("at least one connector is required")
        self._connectors = list(connectors)
        self._scorer = scorer
        self._webhook = webhook_client
        self._similarity_threshold = similarity_threshold
        self._opportunity_writer = opportunity_writer
        # Optional secondary delivery channels. Both None by default
        # (disabled). The worker's primary contract is still the
        # webhook + writer pair; these are pure additive notifications.
        self._telegram = telegram_notifier
        self._ntfy = ntfy_notifier

    def run_once(self) -> WorkerRunResult:
        """One full tick. Never raises — errors are captured in the result."""
        all_listings: list[NormalizedListing] = []
        per_source_counts: dict[str, int] = {}
        per_source_errors: dict[str, str] = {}

        for connector in self._connectors:
            try:
                items = connector.run()
                all_listings.extend(items)
                per_source_counts[connector.name] = len(items)
                logger.info(
                    "worker_connector_ok",
                    extra={"connector": connector.name, "count": len(items)},
                )
            except ConnectorError as exc:
                per_source_errors[connector.name] = f"ConnectorError: {exc}"
                logger.warning(
                    "worker_connector_failed",
                    extra={"connector": connector.name, "error": str(exc)},
                )
            except Exception as exc:
                # Defensive — a connector should only raise ConnectorError,
                # but if anything else escapes we don't want to kill the tick.
                per_source_errors[connector.name] = (
                    f"{type(exc).__name__}: {exc}"
                )
                logger.exception(
                    "worker_connector_unexpected_error",
                    extra={"connector": connector.name},
                )

        groups = match_cross_source_by_tokens(
            all_listings,
            similarity_threshold=self._similarity_threshold,
        )

        scored: list[ScoredOpportunity] = []
        for group in groups:
            opp = self._scorer.score(group)
            if opp is not None:
                scored.append(opp)

        delivery_results: list[WebhookDeliveryResult] = []
        for opp in scored:
            payload = _build_webhook_payload(opp)
            try:
                result = self._webhook.send(payload)
                delivery_results.append(result)
                # Persist for the dashboard's "Live worker output" panel.
                if self._opportunity_writer is not None:
                    self._opportunity_writer.write(opp, result)
            except Exception as exc:
                # Webhook client should never raise — but defensive.
                logger.exception(
                    "worker_webhook_unexpected_error",
                    extra={"opportunity_id": opp.opportunity_id},
                )
                delivery_results.append(
                    WebhookDeliveryResult(
                        status="failed",
                        opportunity_id=opp.opportunity_id,
                        attempts=0,
                        last_status_code=None,
                        last_error=f"{type(exc).__name__}: {exc}",
                        delivered_at=None,
                    )
                )

            # Secondary delivery channels — Telegram and/or NTFY push
            # for the most interesting opportunities. Each fires
            # independently of the others: any one failing must NOT
            # roll back the webhook delivery, the DB row, or sibling
            # notifiers. Both notifiers swallow their own exceptions
            # and return a result object, so the try/except below is
            # purely defensive against a pathological stub in tests.
            if self._telegram is not None:
                try:
                    tg_result = self._telegram.send_opportunity(opp)
                    logger.info(
                        "worker_telegram_done",
                        extra={
                            "opportunity_id": opp.opportunity_id,
                            "status": tg_result.status,
                            "reason": tg_result.reason,
                        },
                    )
                except Exception:  # noqa: BLE001 — never crash a tick
                    logger.exception(
                        "worker_telegram_unexpected_error",
                        extra={"opportunity_id": opp.opportunity_id},
                    )

            if self._ntfy is not None:
                try:
                    ntfy_result = self._ntfy.send_opportunity(opp)
                    logger.info(
                        "worker_ntfy_done",
                        extra={
                            "opportunity_id": opp.opportunity_id,
                            "status": ntfy_result.status,
                            "reason": ntfy_result.reason,
                        },
                    )
                except Exception:  # noqa: BLE001 — never crash a tick
                    logger.exception(
                        "worker_ntfy_unexpected_error",
                        extra={"opportunity_id": opp.opportunity_id},
                    )

        result = WorkerRunResult(
            listings_fetched=len(all_listings),
            per_source_counts=per_source_counts,
            per_source_errors=per_source_errors,
            match_groups=len(groups),
            scored_opportunities=len(scored),
            delivery_results=delivery_results,
        )
        logger.info(
            "worker_tick_complete",
            extra={
                "listings_fetched": result.listings_fetched,
                "match_groups": result.match_groups,
                "scored": result.scored_opportunities,
                "delivered": sum(
                    1 for r in delivery_results if r.status == "delivered"
                ),
                "deduped": sum(
                    1 for r in delivery_results if r.status == "deduped"
                ),
                "failed": sum(
                    1 for r in delivery_results if r.status == "failed"
                ),
            },
        )
        return result


def _build_webhook_payload(opp: ScoredOpportunity) -> WebhookPayload:
    """Convert a ScoredOpportunity into the agent's webhook contract."""
    return WebhookPayload(
        opportunity_id=opp.opportunity_id,
        product_key=opp.product_key,
        sources=opp.sources,
        listings=[_listing_summary(listing) for listing in opp.listings],
        score=opp.score,
        detected_at=opp.detected_at,
        metadata={
            "min_price": opp.min_price,
            "max_price": opp.max_price,
            "absolute_spread": opp.absolute_spread,
            "percent_spread": opp.percent_spread,
        },
    )


def _listing_summary(listing: NormalizedListing) -> dict:
    """Compact dict of the fields the agent needs from each listing."""
    return {
        "source": listing.source,
        "listing_id": listing.listing_id,
        "title": listing.title,
        "url": listing.url,
        "price": listing.price,
        "currency": listing.currency,
        "observed_at": listing.observed_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Entry point — scheduled long-running process
# ---------------------------------------------------------------------------


def _build_default_worker() -> Worker:
    """Wire up connectors + scorer + webhook from environment."""
    # Imports are local so unit tests don't need feedparser/httpx etc.
    from aace_execution.connectors.bensbargains import BensBargainsConnector
    from aace_execution.connectors.dealnews import DealNewsConnector
    from aace_execution.connectors.nine_to_five_toys import (
        NineToFiveToysConnector,
    )
    from aace_execution.connectors.slickdeals import SlickdealsConnector
    from aace_execution.connectors.techbargains import TechBargainsConnector
    # NOTE: WootConnector and DealsPlusConnector are intentionally NOT in
    # the default connector list as of 2026-06-10. Their upstream RSS
    # feeds returned hard failures in production:
    #   * Woot:      HTTP 404 at https://www.woot.com/feed/rss
    #                Amazon-owned Woot appears to have deprecated public
    #                RSS. No obvious replacement endpoint.
    #   * DealsPlus: DNS failure on www.dealsplus.com — domain is gone,
    #                site is defunct.
    # The connector source files + tests are kept in-tree so they can
    # be re-enabled instantly if a working RSS endpoint is ever found.
    # To revive: add the import here and add the constructor below.

    webhook_url = os.environ.get("AGENT_WEBHOOK_URL")
    webhook_secret = os.environ.get("AGENT_WEBHOOK_SECRET")
    if not webhook_url or not webhook_secret:
        raise RuntimeError(
            "AGENT_WEBHOOK_URL and AGENT_WEBHOOK_SECRET must be set"
        )

    scorer = OpportunityScorer(
        min_absolute_spread=float(
            os.environ.get("SCORER_MIN_ABS_SPREAD", "5.0")
        ),
        min_percent_spread=float(
            os.environ.get("SCORER_MIN_PCT_SPREAD", "0.05")
        ),
        score_pct_multiplier=float(
            os.environ.get("SCORER_PCT_MULTIPLIER", "2.0")
        ),
    )

    webhook_client = AgentWebhookClient(
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
    )

    connectors: list[BaseConnector] = [
        SlickdealsConnector(),
        DealNewsConnector(),
        BensBargainsConnector(),
        TechBargainsConnector(),
        NineToFiveToysConnector(),
        # WootConnector(),       # disabled: upstream RSS returns 404
        # DealsPlusConnector(),  # disabled: upstream domain DNS-dead
    ]

    similarity_threshold = float(
        os.environ.get("MATCHER_SIMILARITY_THRESHOLD", "0.6")
    )

    # Optional dashboard wiring: if Postgres env vars are set, persist
    # each scored opportunity so the Streamlit dashboard can show it.
    opportunity_writer = None
    if os.environ.get("POSTGRES_HOST"):
        try:
            from aace_execution.persistence.db import connect
            from aace_execution.persistence.worker_opportunity_writer import (
                WorkerOpportunityWriter,
            )
            opportunity_writer = WorkerOpportunityWriter(connect())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "worker_opportunity_writer_disabled",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )

    # Optional Telegram notifier. Auto-disables if env vars are absent
    # so local dev environments don't need to know about it.
    telegram_notifier = None
    try:
        from aace_execution.integrations.telegram_notifier import (
            TelegramNotifier,
        )
        telegram_notifier = TelegramNotifier.from_environment()
        if telegram_notifier is not None:
            logger.info("worker_telegram_enabled")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "worker_telegram_init_failed",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )

    # Optional NTFY notifier. Same gentle-failure shape as Telegram —
    # absent NTFY_TOPIC in env means "this environment doesn't use it."
    ntfy_notifier = None
    try:
        from aace_execution.integrations.ntfy_notifier import NtfyNotifier
        ntfy_notifier = NtfyNotifier.from_environment()
        if ntfy_notifier is not None:
            logger.info("worker_ntfy_enabled")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "worker_ntfy_init_failed",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )

    return Worker(
        connectors=connectors,
        scorer=scorer,
        webhook_client=webhook_client,
        similarity_threshold=similarity_threshold,
        opportunity_writer=opportunity_writer,
        telegram_notifier=telegram_notifier,
        ntfy_notifier=ntfy_notifier,
    )


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    from aace_execution.observability import init_sentry
    init_sentry(service_name="aace-worker")

    interval_minutes = int(os.environ.get("WORKER_INTERVAL_MINUTES", "30"))
    if interval_minutes < 1:
        raise RuntimeError("WORKER_INTERVAL_MINUTES must be >= 1")

    worker = _build_default_worker()

    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError as exc:
        raise RuntimeError(
            "apscheduler is required to run the worker "
            "(add 'apscheduler' to your dependencies)"
        ) from exc

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        worker.run_once,
        trigger="interval",
        minutes=interval_minutes,
        next_run_time=datetime.now(timezone.utc),  # run immediately on boot
        id="aace_worker_tick",
        name="AACE worker tick",
        max_instances=1,
        coalesce=True,
    )

    def _graceful_shutdown(signum, _frame):
        logger.info("worker_received_signal", extra={"signum": signum})
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _graceful_shutdown)
    signal.signal(signal.SIGTERM, _graceful_shutdown)

    logger.info(
        "worker_starting",
        extra={"interval_minutes": interval_minutes},
    )
    scheduler.start()


if __name__ == "__main__":
    main()
