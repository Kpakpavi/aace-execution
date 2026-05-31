"""Unit tests for WorkerOpportunityWriter. DB connection mocked."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from aace_execution.connectors.base import NormalizedListing
from aace_execution.integrations.agent_webhook import WebhookDeliveryResult
from aace_execution.persistence.worker_opportunity_writer import (
    WorkerOpportunityWriter,
)
from aace_execution.pipeline.opportunity_scorer import ScoredOpportunity


_NOW = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)


def _mk_listing(source: str, price: float) -> NormalizedListing:
    return NormalizedListing(
        source=source,
        listing_id=f"{source}:1",
        external_id="1",
        product_key="test",
        title=f"{source} listing",
        url=f"https://{source}.example/1",
        price=price,
        currency="USD",
        observed_at=_NOW,
    )


def _mk_opportunity() -> ScoredOpportunity:
    return ScoredOpportunity(
        opportunity_id="opp-1",
        product_key="apple macbook",
        listings=[_mk_listing("slickdeals", 100.0), _mk_listing("dealnews", 130.0)],
        sources=["dealnews", "slickdeals"],
        min_price=100.0,
        max_price=130.0,
        absolute_spread=30.0,
        percent_spread=0.231,
        score=0.462,
        detected_at=_NOW,
    )


def _mk_delivery(status: str = "delivered") -> WebhookDeliveryResult:
    return WebhookDeliveryResult(
        status=status,
        opportunity_id="opp-1",
        attempts=1,
        last_status_code=200,
        last_error=None,
        delivered_at=_NOW,
    )


def _mk_connection():
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cursor)
    return conn, cursor


class TestWrite:
    def test_inserts_one_row(self):
        conn, cursor = _mk_connection()
        WorkerOpportunityWriter(conn).write(_mk_opportunity(), _mk_delivery())
        assert cursor.execute.call_count == 1
        assert conn.commit.call_count == 1

    def test_passes_all_opportunity_fields(self):
        conn, cursor = _mk_connection()
        WorkerOpportunityWriter(conn).write(_mk_opportunity(), _mk_delivery())
        sql, params = cursor.execute.call_args[0]
        assert "INSERT INTO worker_opportunities" in sql
        assert params[0] == "opp-1"
        assert params[1] == "apple macbook"
        assert params[2] == "dealnews,slickdeals"
        assert params[3] == 2  # source_count
        assert params[4] == 100.0
        assert params[5] == 130.0
        assert params[6] == 30.0
        assert params[7] == 0.231
        assert params[8] == 0.462
        assert params[10] == "delivered"

    def test_listings_serialized_as_json(self):
        conn, cursor = _mk_connection()
        WorkerOpportunityWriter(conn).write(_mk_opportunity(), _mk_delivery())
        params = cursor.execute.call_args[0][1]
        listings = json.loads(params[9])
        assert len(listings) == 2
        assert listings[0]["price"] == 100.0
        assert listings[0]["source"] == "slickdeals"

    def test_records_delivery_status(self):
        conn, cursor = _mk_connection()
        WorkerOpportunityWriter(conn).write(_mk_opportunity(), _mk_delivery("deduped"))
        params = cursor.execute.call_args[0][1]
        assert params[10] == "deduped"

    def test_db_error_is_swallowed_not_raised(self):
        """A flaky DB must not kill the worker tick."""
        conn, cursor = _mk_connection()
        cursor.execute.side_effect = RuntimeError("db boom")
        # Should not raise.
        WorkerOpportunityWriter(conn).write(_mk_opportunity(), _mk_delivery())
