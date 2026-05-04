"""Integration tests for PostgresWriter against a live PostgreSQL database.

Covers PERSISTENCE_WRITER_CONTRACT.md sections 7 and 9:
  - 7.1 / 9.4  pipeline_results write + finalized-row idempotency
  - 7.2        opportunities written only for OPPORTUNITY_* classifications
  - 7.3        alert_decisions written only when Stage 4 data is present
  - 7.4        audit_records append-only (one row per persist_execution call)
  - 7.5        persist_execution orchestration end-to-end
  - 9.x        PROCESSING_FAILURE row superseded by a later finalized result

Tests use the real connection from src/aace_execution/persistence/db.py and the
real PostgresWriter. No mocks. Each test isolates itself by using a unique
pipeline_execution_id derived from the test name; cleanup runs before each test.

Required env vars (loaded from .env): POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB,
POSTGRES_USER, POSTGRES_PASSWORD.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# postgres_writer.py imports its siblings as `aace_execution.*` (no `src.` prefix),
# so the test must make `src/` importable to satisfy those internal imports.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psycopg  # noqa: E402
import pytest  # type: ignore  # noqa: E402

from aace_execution.persistence.db import connect  # noqa: E402
from aace_execution.persistence.postgres_writer import PostgresWriter  # noqa: E402
from aace_execution.persistence.results import (  # noqa: E402
    ExecutionStatus,
    WriteStatus,
)


_REQUIRED_ENV = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)

# Skip the module entirely if the database isn't configured — keeps the suite
# usable on machines without a local PostgreSQL.
pytestmark = pytest.mark.skipif(
    any(not os.environ.get(name) for name in _REQUIRED_ENV),
    reason="PostgreSQL env vars not set; integration tests skipped.",
)


RESULT_TS = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)
PRODUCT_ID = "test-product-pgw"
PAIR_ID = "test-pair-pgw"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    """Open a real connection per test and close it at teardown."""
    connection = connect()
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def writer(conn: psycopg.Connection) -> PostgresWriter:
    return PostgresWriter(conn)


@pytest.fixture
def execution_id(request: pytest.FixtureRequest, conn: psycopg.Connection) -> str:
    """Deterministic per-test execution id, with rows cleared before the test runs."""
    pid = f"pgw-{request.node.name}"
    _clear_rows(conn, pid)
    return pid


# ---------------------------------------------------------------------------
# Payload builders (deterministic)
# ---------------------------------------------------------------------------


def _pipeline_result_params(
    pid: str,
    *,
    classification: str = "NO_OPPORTUNITY",
    stage_reached: str = "DISCREPANCY_DETECTION",
    failure_stage: str | None = None,
    failure_reason: str | None = None,
    retry_eligible: bool | None = False,
) -> dict:
    return {
        "pipeline_execution_id": pid,
        "product_id": PRODUCT_ID,
        "result_classification": classification,
        "stage_reached": stage_reached,
        "result_timestamp": RESULT_TS,
        "stage_outcome_summary": json.dumps({"reason": "deterministic"}),
        "retry_eligible": retry_eligible,
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
    }


def _audit_record_params(pid: str, *, classification: str = "NO_OPPORTUNITY") -> dict:
    return {
        "pipeline_execution_id": pid,
        "product_id": PRODUCT_ID,
        "result_classification": classification,
        "result_timestamp": RESULT_TS,
        "stage_outcome_summary": json.dumps({"reason": "deterministic"}),
        "discrepancy_rule_applied": None,
        "score": None,
        "scoring_factor_summary": None,
        "alert_decision": None,
        "failure_stage": None,
        "failure_reason": None,
        "early_exit_stage": None,
        "early_exit_reason": None,
    }


def _opportunity_params(pid: str, *, alert_decision: str = "ALERT_ELIGIBLE") -> dict:
    return {
        "pipeline_execution_id": pid,
        "product_id": PRODUCT_ID,
        "pair_id": PAIR_ID,
        "result_classification": "OPPORTUNITY_DETECTED",
        "discrepancy_rule_id": "rule-1",
        "discrepancy_source_a": "source-a",
        "discrepancy_source_b": "source-b",
        "price_a": Decimal("100.00"),
        "price_b": Decimal("105.00"),
        "absolute_difference": Decimal("5.00"),
        "percentage_difference": Decimal("5.00"),
        "score": Decimal("0.80"),
        "score_result_id": f"score-{pid}",
        "scoring_factors_applied": json.dumps({"factor": "deterministic"}),
        "score_range": json.dumps({"min": 0, "max": 1}),
        "alert_decision": alert_decision,
        "alert_decision_id": f"ad-{pid}",
        "suppression_reason": None,
        "opportunity_timestamp": RESULT_TS,
    }


def _alert_decision_params(pid: str) -> dict:
    return {
        "pipeline_execution_id": pid,
        "notification_type": "EMAIL",
        "alert_decision_id": f"ad-{pid}",
        "product_id": PRODUCT_ID,
        "pair_id": PAIR_ID,
        "score": Decimal("0.80"),
        "alert_threshold": Decimal("0.50"),
        "threshold_met": True,
        "decision_result": "ALERT_ELIGIBLE",
        "suppression_reason": None,
        "decision_basis": json.dumps({"basis": "score>=threshold"}),
        "duplicate_check_result": "NO_PRIOR_ALERT",
        "decision_reference_timestamp": RESULT_TS,
    }


# ---------------------------------------------------------------------------
# Direct DB helpers (kept narrow — only used to verify writer effects)
# ---------------------------------------------------------------------------


def _clear_rows(conn: psycopg.Connection, pid: str) -> None:
    """Delete any rows with this execution id, in FK-safe order."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM audit_records WHERE pipeline_execution_id = %s", (pid,))
        cur.execute(
            "DELETE FROM alert_decisions WHERE pipeline_execution_id = %s", (pid,)
        )
        cur.execute(
            "DELETE FROM opportunities WHERE pipeline_execution_id = %s", (pid,)
        )
        cur.execute(
            "DELETE FROM pipeline_results WHERE pipeline_execution_id = %s", (pid,)
        )
    conn.commit()


def _count(conn: psycopg.Connection, table: str, pid: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {table} WHERE pipeline_execution_id = %s", (pid,)
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _classification(conn: psycopg.Connection, pid: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT result_classification FROM pipeline_results"
            " WHERE pipeline_execution_id = %s",
            (pid,),
        )
        row = cur.fetchone()
    return None if row is None else str(row[0])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pipeline_result_and_audit_written(
    writer: PostgresWriter, conn: psycopg.Connection, execution_id: str
) -> None:
    """A first-time NO_OPPORTUNITY execution writes pipeline_results + audit_records."""
    outcome = writer.persist_execution(
        pipeline_result_params=_pipeline_result_params(execution_id),
        opportunity_params=None,
        alert_decision_params=None,
        audit_record_params=_audit_record_params(execution_id),
    )

    assert outcome.status is ExecutionStatus.ALL_WRITES_SUCCEEDED
    assert outcome.pipeline_result_write.status is WriteStatus.WRITTEN
    assert outcome.audit_record_write is not None
    assert outcome.audit_record_write.status is WriteStatus.WRITTEN
    assert outcome.opportunity_write is None
    assert outcome.alert_decision_write is None

    assert _count(conn, "pipeline_results", execution_id) == 1
    assert _count(conn, "audit_records", execution_id) == 1


def test_repeated_persist_execution_is_idempotent_for_pipeline_results(
    writer: PostgresWriter, conn: psycopg.Connection, execution_id: str
) -> None:
    """Re-running the same finalized execution does not insert a second pipeline row."""
    params = _pipeline_result_params(execution_id)
    audit = _audit_record_params(execution_id)

    first = writer.persist_execution(params, None, None, audit)
    second = writer.persist_execution(params, None, None, audit)

    assert first.pipeline_result_write.status is WriteStatus.WRITTEN
    assert second.pipeline_result_write.status is WriteStatus.ALREADY_EXISTS
    assert second.status is ExecutionStatus.ALL_WRITES_SUCCEEDED
    assert _count(conn, "pipeline_results", execution_id) == 1


def test_audit_records_are_append_only(
    writer: PostgresWriter, conn: psycopg.Connection, execution_id: str
) -> None:
    """Each persist_execution call appends a new audit row, even when the pipeline
    result already exists (ALREADY_EXISTS path)."""
    params = _pipeline_result_params(execution_id)
    audit = _audit_record_params(execution_id)

    writer.persist_execution(params, None, None, audit)
    writer.persist_execution(params, None, None, audit)
    writer.persist_execution(params, None, None, audit)

    assert _count(conn, "audit_records", execution_id) == 3
    assert _count(conn, "pipeline_results", execution_id) == 1


@pytest.mark.parametrize(
    "classification",
    ["OPPORTUNITY_DETECTED", "OPPORTUNITY_SCORED_NO_ALERT"],
)
def test_opportunity_written_for_opportunity_classifications(
    writer: PostgresWriter,
    conn: psycopg.Connection,
    execution_id: str,
    classification: str,
) -> None:
    """When opportunity_params is supplied, the row is written."""
    pipeline = _pipeline_result_params(
        execution_id,
        classification=classification,
        stage_reached="SCORING",
    )
    opportunity = _opportunity_params(
        execution_id,
        alert_decision="ALERT_ELIGIBLE"
        if classification == "OPPORTUNITY_DETECTED"
        else "NO_ALERT",
    )
    opportunity["result_classification"] = classification

    outcome = writer.persist_execution(
        pipeline_result_params=pipeline,
        opportunity_params=opportunity,
        alert_decision_params=None,
        audit_record_params=_audit_record_params(
            execution_id, classification=classification
        ),
    )

    assert outcome.status is ExecutionStatus.ALL_WRITES_SUCCEEDED
    assert outcome.opportunity_write is not None
    assert outcome.opportunity_write.status is WriteStatus.WRITTEN
    assert _count(conn, "opportunities", execution_id) == 1


def test_no_opportunity_row_when_opportunity_params_omitted(
    writer: PostgresWriter, conn: psycopg.Connection, execution_id: str
) -> None:
    """Caller controls whether opportunity is written. NO_OPPORTUNITY classification
    naturally omits opportunity_params, and no row should appear."""
    outcome = writer.persist_execution(
        pipeline_result_params=_pipeline_result_params(execution_id),
        opportunity_params=None,
        alert_decision_params=None,
        audit_record_params=_audit_record_params(execution_id),
    )

    assert outcome.opportunity_write is None
    assert _count(conn, "opportunities", execution_id) == 0


def test_alert_decision_written_when_stage4_data_present(
    writer: PostgresWriter, conn: psycopg.Connection, execution_id: str
) -> None:
    """OPPORTUNITY_DETECTED with Stage 4 alert data writes the alert_decisions row."""
    pipeline = _pipeline_result_params(
        execution_id,
        classification="OPPORTUNITY_DETECTED",
        stage_reached="ALERT_DECISION",
    )
    opportunity = _opportunity_params(execution_id, alert_decision="ALERT_ELIGIBLE")
    opportunity["result_classification"] = "OPPORTUNITY_DETECTED"

    outcome = writer.persist_execution(
        pipeline_result_params=pipeline,
        opportunity_params=opportunity,
        alert_decision_params=_alert_decision_params(execution_id),
        audit_record_params=_audit_record_params(
            execution_id, classification="OPPORTUNITY_DETECTED"
        ),
    )

    assert outcome.status is ExecutionStatus.ALL_WRITES_SUCCEEDED
    assert outcome.alert_decision_write is not None
    assert outcome.alert_decision_write.status is WriteStatus.WRITTEN
    assert _count(conn, "alert_decisions", execution_id) == 1


def test_alert_decision_skipped_when_stage4_absent(
    writer: PostgresWriter, conn: psycopg.Connection, execution_id: str
) -> None:
    """OPPORTUNITY_SCORED_NO_ALERT (no Stage 4 alert dispatch) writes no alert row."""
    pipeline = _pipeline_result_params(
        execution_id,
        classification="OPPORTUNITY_SCORED_NO_ALERT",
        stage_reached="SCORING",
    )
    opportunity = _opportunity_params(execution_id, alert_decision="NO_ALERT")
    opportunity["result_classification"] = "OPPORTUNITY_SCORED_NO_ALERT"

    outcome = writer.persist_execution(
        pipeline_result_params=pipeline,
        opportunity_params=opportunity,
        alert_decision_params=None,
        audit_record_params=_audit_record_params(
            execution_id, classification="OPPORTUNITY_SCORED_NO_ALERT"
        ),
    )

    assert outcome.alert_decision_write is None
    assert _count(conn, "alert_decisions", execution_id) == 0


def test_processing_failure_row_is_superseded_by_later_finalized_result(
    writer: PostgresWriter, conn: psycopg.Connection, execution_id: str
) -> None:
    """A PROCESSING_FAILURE row may be replaced by a finalized result on retry
    (PERSISTENCE_WRITER_CONTRACT.md §7.1: UPDATE path returns UPDATED)."""
    failure_params = _pipeline_result_params(
        execution_id,
        classification="PROCESSING_FAILURE",
        stage_reached="DISCREPANCY_DETECTION",
        failure_stage="DISCREPANCY_DETECTION",
        failure_reason="transient db blip",
        retry_eligible=True,
    )
    failure_audit = _audit_record_params(
        execution_id, classification="PROCESSING_FAILURE"
    )
    failure_audit["failure_stage"] = "DISCREPANCY_DETECTION"
    failure_audit["failure_reason"] = "transient db blip"

    first = writer.persist_execution(failure_params, None, None, failure_audit)
    assert first.pipeline_result_write.status is WriteStatus.WRITTEN
    assert _classification(conn, execution_id) == "PROCESSING_FAILURE"

    success_params = _pipeline_result_params(
        execution_id, classification="NO_OPPORTUNITY"
    )
    success_audit = _audit_record_params(execution_id, classification="NO_OPPORTUNITY")

    second = writer.persist_execution(success_params, None, None, success_audit)

    assert second.pipeline_result_write.status is WriteStatus.UPDATED
    assert second.status is ExecutionStatus.ALL_WRITES_SUCCEEDED
    assert _classification(conn, execution_id) == "NO_OPPORTUNITY"
    assert _count(conn, "pipeline_results", execution_id) == 1
    # Both calls produced an audit record (append-only).
    assert _count(conn, "audit_records", execution_id) == 2
