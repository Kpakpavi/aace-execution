"""Unit tests for the AACE worker.

Worker is tested with mocked connectors, mocked scorer, mocked webhook —
no real network, no real scheduler, no real DB.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from aace_execution.connectors.base import ConnectorError, NormalizedListing
from aace_execution.integrations.agent_webhook import WebhookDeliveryResult
from aace_execution.pipeline.opportunity_scorer import OpportunityScorer
from aace_execution.worker import Worker, _build_webhook_payload, _listing_summary
from aace_execution.pipeline.opportunity_scorer import ScoredOpportunity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)


_SHARED_TITLE = "Apple MacBook Air M3 256GB"


def _mk_listing(
    source: str,
    price: float,
    *,
    lid_suffix: str = "a",
    title: str = _SHARED_TITLE,
) -> NormalizedListing:
    return NormalizedListing(
        source=source,
        listing_id=f"{source}:{lid_suffix}",
        external_id=lid_suffix,
        product_key="apple macbook air m3 256gb",
        title=title,
        url=f"https://{source}.example.com/{lid_suffix}",
        price=price,
        currency="USD",
        observed_at=_NOW,
    )


class _StubConnector:
    """Tiny fake connector that returns fixed listings (or raises)."""

    def __init__(self, name: str, listings=None, error: Exception | None = None):
        self.name = name
        self._listings = listings or []
        self._error = error
        self.run_called = 0

    def run(self):
        self.run_called += 1
        if self._error is not None:
            raise self._error
        return list(self._listings)


def _stub_webhook(result_status: str = "delivered"):
    """Fake AgentWebhookClient with a controllable send() result."""
    client = MagicMock()

    def _send(payload):
        return WebhookDeliveryResult(
            status=result_status,
            opportunity_id=payload.opportunity_id,
            attempts=1,
            last_status_code=200 if result_status == "delivered" else None,
            last_error=None,
            delivered_at=_NOW if result_status == "delivered" else None,
        )

    client.send = MagicMock(side_effect=_send)
    return client


def _permissive_scorer() -> OpportunityScorer:
    return OpportunityScorer(min_absolute_spread=0.0, min_percent_spread=0.0)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_zero_connectors_rejected(self):
        with pytest.raises(ValueError):
            Worker(
                connectors=[],
                scorer=_permissive_scorer(),
                webhook_client=_stub_webhook(),
            )


# ---------------------------------------------------------------------------
# Empty / no-match scenarios
# ---------------------------------------------------------------------------


class TestEmptyAndNoMatch:
    def test_no_listings_no_calls_to_webhook(self):
        connectors = [_StubConnector("slickdeals"), _StubConnector("dealnews")]
        webhook = _stub_webhook()
        worker = Worker(
            connectors=connectors,
            scorer=_permissive_scorer(),
            webhook_client=webhook,
        )
        result = worker.run_once()
        assert result.listings_fetched == 0
        assert result.match_groups == 0
        assert result.scored_opportunities == 0
        assert webhook.send.call_count == 0

    def test_single_source_listings_yield_no_match(self):
        # Both listings from one source -> matcher drops them.
        connectors = [
            _StubConnector(
                "slickdeals",
                listings=[
                    _mk_listing("slickdeals", 100.0, lid_suffix="a"),
                    _mk_listing("slickdeals", 110.0, lid_suffix="b"),
                ],
            ),
            _StubConnector("dealnews"),
        ]
        webhook = _stub_webhook()
        worker = Worker(
            connectors=connectors,
            scorer=_permissive_scorer(),
            webhook_client=webhook,
        )
        result = worker.run_once()
        assert result.listings_fetched == 2
        assert result.match_groups == 0
        assert webhook.send.call_count == 0


# ---------------------------------------------------------------------------
# Happy path: cross-source match -> score -> webhook
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_match_and_score_and_deliver(self):
        connectors = [
            _StubConnector(
                "slickdeals",
                listings=[_mk_listing("slickdeals", 100.0, lid_suffix="a")],
            ),
            _StubConnector(
                "dealnews",
                listings=[_mk_listing("dealnews", 130.0, lid_suffix="b")],
            ),
        ]
        webhook = _stub_webhook("delivered")
        worker = Worker(
            connectors=connectors,
            scorer=_permissive_scorer(),
            webhook_client=webhook,
        )
        result = worker.run_once()
        assert result.listings_fetched == 2
        assert result.match_groups == 1
        assert result.scored_opportunities == 1
        assert webhook.send.call_count == 1
        assert len(result.delivery_results) == 1
        assert result.delivery_results[0].status == "delivered"

    def test_per_source_counts_recorded(self):
        connectors = [
            _StubConnector(
                "slickdeals",
                listings=[
                    _mk_listing("slickdeals", 100.0, lid_suffix="a"),
                    _mk_listing("slickdeals", 200.0, lid_suffix="b"),
                ],
            ),
            _StubConnector(
                "dealnews",
                listings=[_mk_listing("dealnews", 130.0, lid_suffix="c")],
            ),
        ]
        webhook = _stub_webhook()
        worker = Worker(
            connectors=connectors,
            scorer=_permissive_scorer(),
            webhook_client=webhook,
        )
        result = worker.run_once()
        assert result.per_source_counts == {"slickdeals": 2, "dealnews": 1}


# ---------------------------------------------------------------------------
# Connector error tolerance
# ---------------------------------------------------------------------------


class TestConnectorErrors:
    def test_connector_error_does_not_kill_tick(self):
        # Slickdeals raises, DealNews succeeds, no cross-source match,
        # but the tick must still complete cleanly.
        connectors = [
            _StubConnector("slickdeals", error=ConnectorError("boom")),
            _StubConnector(
                "dealnews",
                listings=[_mk_listing("dealnews", 100.0, lid_suffix="x")],
            ),
        ]
        webhook = _stub_webhook()
        worker = Worker(
            connectors=connectors,
            scorer=_permissive_scorer(),
            webhook_client=webhook,
        )
        result = worker.run_once()
        assert result.listings_fetched == 1
        assert "slickdeals" in result.per_source_errors
        assert "ConnectorError" in result.per_source_errors["slickdeals"]
        assert result.per_source_counts == {"dealnews": 1}

    def test_unexpected_exception_captured_too(self):
        connectors = [
            _StubConnector("slickdeals", error=RuntimeError("unexpected")),
            _StubConnector("dealnews"),
        ]
        webhook = _stub_webhook()
        worker = Worker(
            connectors=connectors,
            scorer=_permissive_scorer(),
            webhook_client=webhook,
        )
        result = worker.run_once()
        assert "slickdeals" in result.per_source_errors
        assert "RuntimeError" in result.per_source_errors["slickdeals"]


# ---------------------------------------------------------------------------
# Score-based filtering
# ---------------------------------------------------------------------------


class TestScoreFiltering:
    def test_below_threshold_match_is_not_shipped(self):
        # 1% spread, below default 5% threshold.
        connectors = [
            _StubConnector(
                "slickdeals",
                listings=[_mk_listing("slickdeals", 100.0, lid_suffix="a")],
            ),
            _StubConnector(
                "dealnews",
                listings=[_mk_listing("dealnews", 101.0, lid_suffix="b")],
            ),
        ]
        webhook = _stub_webhook()
        worker = Worker(
            connectors=connectors,
            scorer=OpportunityScorer(),  # default thresholds
            webhook_client=webhook,
        )
        result = worker.run_once()
        assert result.match_groups == 1
        assert result.scored_opportunities == 0
        assert webhook.send.call_count == 0


# ---------------------------------------------------------------------------
# Webhook dedup -> recorded in result
# ---------------------------------------------------------------------------


class TestWebhookDedup:
    def test_deduped_result_recorded(self):
        connectors = [
            _StubConnector(
                "slickdeals",
                listings=[_mk_listing("slickdeals", 100.0, lid_suffix="a")],
            ),
            _StubConnector(
                "dealnews",
                listings=[_mk_listing("dealnews", 130.0, lid_suffix="b")],
            ),
        ]
        webhook = _stub_webhook("deduped")
        worker = Worker(
            connectors=connectors,
            scorer=_permissive_scorer(),
            webhook_client=webhook,
        )
        result = worker.run_once()
        assert result.delivery_results[0].status == "deduped"


# ---------------------------------------------------------------------------
# Payload conversion helpers
# ---------------------------------------------------------------------------


class TestPayloadHelpers:
    def test_listing_summary_includes_core_fields(self):
        listing = _mk_listing("slickdeals", 99.99)
        summary = _listing_summary(listing)
        assert summary["source"] == "slickdeals"
        assert summary["price"] == 99.99
        assert summary["currency"] == "USD"
        assert summary["url"].startswith("https://")
        assert "observed_at" in summary

    def test_build_webhook_payload_from_opportunity(self):
        opp = ScoredOpportunity(
            opportunity_id="opp-test",
            product_key="apple macbook",
            listings=[_mk_listing("slickdeals", 799.0), _mk_listing("dealnews", 899.0)],
            sources=["dealnews", "slickdeals"],
            min_price=799.0,
            max_price=899.0,
            absolute_spread=100.0,
            percent_spread=0.1112,
            score=0.222,
            detected_at=_NOW,
        )
        payload = _build_webhook_payload(opp)
        assert payload.opportunity_id == "opp-test"
        assert payload.product_key == "apple macbook"
        assert payload.score == 0.222
        assert payload.sources == ["dealnews", "slickdeals"]
        assert len(payload.listings) == 2
        assert payload.metadata["min_price"] == 799.0
        assert payload.metadata["max_price"] == 899.0
        assert payload.metadata["absolute_spread"] == 100.0
