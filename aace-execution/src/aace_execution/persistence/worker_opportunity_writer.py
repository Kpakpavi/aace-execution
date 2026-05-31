"""Persists worker-scored opportunities to Postgres for the dashboard.

The v0.1.0 worker ships opportunities to the AI agent via webhook (the
earning path). This writer also logs each one to a dedicated
``worker_opportunities`` table so the existing Streamlit dashboard can
display what the worker is doing in real time.

Why a separate table from the existing ``opportunities`` table:
The existing schema is shaped around the 6-stage pipeline (pair_id,
discrepancy_rule_id, scoring_factors_applied, etc). The v0.1.0 worker
follows a simpler model — price spread on a token-matched cluster.
Mixing the two shapes would force ugly nulls. Separate table, separate
endpoint, no schema collision.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aace_execution.integrations.agent_webhook import WebhookDeliveryResult
from aace_execution.pipeline.opportunity_scorer import ScoredOpportunity

logger = logging.getLogger(__name__)


class WorkerOpportunityWriter:
    """Inserts ``ScoredOpportunity`` rows into ``worker_opportunities``.

    Injects a DB connection at construction so it's testable without a
    live Postgres (pass a mock with ``cursor()`` / ``commit()``).
    """

    def __init__(self, connection: Any) -> None:
        self._conn = connection

    def write(
        self,
        opportunity: ScoredOpportunity,
        delivery: WebhookDeliveryResult,
    ) -> None:
        """Insert a single opportunity row. Never raises — logs on failure."""
        try:
            listings_json = json.dumps(
                [_listing_dict(listing) for listing in opportunity.listings]
            )
            with self._conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO worker_opportunities (
                        opportunity_id, product_key, sources, source_count,
                        min_price, max_price, absolute_spread, percent_spread,
                        score, listings_json, delivery_status, detected_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    """,
                    (
                        opportunity.opportunity_id,
                        opportunity.product_key,
                        ",".join(opportunity.sources),
                        len(opportunity.sources),
                        opportunity.min_price,
                        opportunity.max_price,
                        opportunity.absolute_spread,
                        opportunity.percent_spread,
                        opportunity.score,
                        listings_json,
                        delivery.status,
                        opportunity.detected_at,
                    ),
                )
            self._conn.commit()
            logger.info(
                "worker_opportunity_persisted",
                extra={"opportunity_id": opportunity.opportunity_id},
            )
        except Exception as exc:  # noqa: BLE001 — intentional: never crash the tick
            logger.warning(
                "worker_opportunity_persist_failed",
                extra={
                    "opportunity_id": opportunity.opportunity_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )


def _listing_dict(listing: Any) -> dict[str, Any]:
    return {
        "source": listing.source,
        "listing_id": listing.listing_id,
        "title": listing.title,
        "url": listing.url,
        "price": listing.price,
        "currency": listing.currency,
        "observed_at": listing.observed_at.isoformat(),
    }
