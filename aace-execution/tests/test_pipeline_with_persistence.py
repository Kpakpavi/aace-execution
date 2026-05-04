"""End-to-end PipelineRunner test with real PostgreSQL persistence.

Runs one deterministic pipeline execution against a live database using
PipelineRunner + injected PostgresWriter(connect()), then verifies rows
land in pipeline_results, audit_records, opportunities, and alert_decisions.

Required env vars (loaded from .env): POSTGRES_HOST, POSTGRES_PORT,
POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psycopg  # noqa: E402
import pytest  # type: ignore  # noqa: E402

from aace_execution.persistence.db import connect  # noqa: E402
from aace_execution.persistence.postgres_writer import PostgresWriter  # noqa: E402
from aace_execution.pipeline.pipeline_runner import PipelineRunner  # noqa: E402
from aace_execution.validators.input_validator import (  # noqa: E402
    InputValidator,
    ValidationContext,
)


_REQUIRED_ENV = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)

pytestmark = pytest.mark.skipif(
    any(not os.environ.get(name) for name in _REQUIRED_ENV),
    reason="PostgreSQL env vars not set; integration test skipped.",
)


REF_TS = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)
EXECUTION_ID = "pipeline-persist-it-0001"
PRODUCT_ID = "product-persist-it-0001"
ALLOWED_SOURCES = frozenset({"source_a", "source_b"})

_OPPORTUNITY_CLASSIFICATIONS = {
    "OPPORTUNITY_DETECTED",
    "OPPORTUNITY_SCORED_NO_ALERT",
}


def _pipeline_input() -> dict:
    return {
        "pipeline_execution_id": EXECUTION_ID,
        "product_id": PRODUCT_ID,
        "product_name": "Persistence IT Product",
        "freshness_reference_timestamp": REF_TS,
        "alert_threshold": 0.5,
        "opportunity_status": "ACTIVE",
        "eligible_opportunity_statuses": ["ACTIVE"],
        "notification_type": "EMAIL",
        "discrepancy_rule_set": {
            "rule_id": "rule-persist-it-001",
            "threshold_method": "ABSOLUTE",
            "absolute_threshold": 1.0,
        },
        "scoring_factor_set": {
            "scoring_factors": [
                {
                    "factor_name": "price_difference",
                    "factor_type": "absolute_difference",
                    "weight": 1.0,
                }
            ],
            "score_range": {"min": 0.0, "max": 100.0},
            "normalization_method": None,
            "tie_break_order": [],
        },
        "listings": [
            {
                "listing_id": "listing-a",
                "source": "source_a",
                "external_id": "ext-a",
                "price": 100.0,
                "product_ref": PRODUCT_ID,
            },
            {
                "listing_id": "listing-b",
                "source": "source_b",
                "external_id": "ext-b",
                "price": 110.0,
                "product_ref": PRODUCT_ID,
            },
        ],
        "observations": [
            {
                "observation_id": "obs-a",
                "listing_ref": "listing-a",
                "source": "source_a",
                "observed_price": 100.0,
                "normalized_price": 100.0,
                "observed_at": REF_TS,
            },
            {
                "observation_id": "obs-b",
                "listing_ref": "listing-b",
                "source": "source_b",
                "observed_price": 110.0,
                "normalized_price": 110.0,
                "observed_at": REF_TS,
            },
        ],
        "duplicate_check_result": "NO_PRIOR_ALERT",
    }


def _validator_factory(pipeline_input: dict) -> InputValidator:
    context = ValidationContext(
        pipeline_execution_id=pipeline_input["pipeline_execution_id"],
        freshness_reference_timestamp=pipeline_input["freshness_reference_timestamp"],
        freshness_window_seconds=3600,
        allowed_sources=ALLOWED_SOURCES,
        validated_at=pipeline_input["freshness_reference_timestamp"],
    )
    return InputValidator(context)


def _clear_rows(conn: psycopg.Connection, pid: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM audit_records WHERE pipeline_execution_id = %s", (pid,))
        cur.execute("DELETE FROM alert_decisions WHERE pipeline_execution_id = %s", (pid,))
        cur.execute("DELETE FROM opportunities WHERE pipeline_execution_id = %s", (pid,))
        cur.execute("DELETE FROM pipeline_results WHERE pipeline_execution_id = %s", (pid,))
    conn.commit()


def _count(conn: psycopg.Connection, table: str, pid: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {table} WHERE pipeline_execution_id = %s", (pid,)
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    connection = connect()
    try:
        _clear_rows(connection, EXECUTION_ID)
        yield connection
    finally:
        connection.close()


def test_pipeline_runner_persists_full_execution(conn: psycopg.Connection) -> None:
    writer = PostgresWriter(conn)
    runner = PipelineRunner(
        input_validator_factory=_validator_factory,
        postgres_writer=writer,
    )

    result = runner.run(_pipeline_input())

    assert result.failure_stage is None
    assert result.failure_reason is None
    assert result.pipeline_execution_id == EXECUTION_ID
    assert result.product_id == PRODUCT_ID
    assert result.result in _OPPORTUNITY_CLASSIFICATIONS | {"ALERT_ELIGIBLE"}

    assert _count(conn, "pipeline_results", EXECUTION_ID) == 1
    assert _count(conn, "audit_records", EXECUTION_ID) == 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT result_classification FROM pipeline_results "
            "WHERE pipeline_execution_id = %s",
            (EXECUTION_ID,),
        )
        row = cur.fetchone()
    assert row is not None
    stored_classification = row[0]

    if stored_classification in _OPPORTUNITY_CLASSIFICATIONS:
        assert _count(conn, "opportunities", EXECUTION_ID) == 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT alert_decision_id FROM opportunities "
            "WHERE pipeline_execution_id = %s",
            (EXECUTION_ID,),
        )
        opp_row = cur.fetchone()

    has_stage4_decision = opp_row is not None and opp_row[0]
    if has_stage4_decision:
        assert _count(conn, "alert_decisions", EXECUTION_ID) >= 1
