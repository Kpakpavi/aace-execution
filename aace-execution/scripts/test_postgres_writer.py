"""Smoke test for PostgresWriter.persist_execution against a live PostgreSQL.

Builds a minimal deterministic NO_OPPORTUNITY pipeline result + audit payload,
calls persist_execution once, and prints the resulting ExecutionOutcome.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aace_execution.persistence.db import connect  # noqa: E402
from aace_execution.persistence.postgres_writer import PostgresWriter  # noqa: E402


PIPELINE_EXECUTION_ID = "test-exec-0001"
PRODUCT_ID = "test-product-0001"
RESULT_TIMESTAMP = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


def main() -> None:
    pipeline_result_params = {
        "pipeline_execution_id": PIPELINE_EXECUTION_ID,
        "product_id": PRODUCT_ID,
        "result_classification": "NO_OPPORTUNITY",
        "stage_reached": "DISCREPANCY_DETECTION",
        "result_timestamp": RESULT_TIMESTAMP,
        "stage_outcome_summary": json.dumps({"reason": "no_discrepancy"}),
        "retry_eligible": False,
        "failure_stage": None,
        "failure_reason": None,
    }

    audit_record_params = {
        "pipeline_execution_id": PIPELINE_EXECUTION_ID,
        "product_id": PRODUCT_ID,
        "result_classification": "NO_OPPORTUNITY",
        "result_timestamp": RESULT_TIMESTAMP,
        "stage_outcome_summary": json.dumps({"reason": "no_discrepancy"}),
        "discrepancy_rule_applied": None,
        "score": None,
        "scoring_factor_summary": None,
        "alert_decision": None,
        "failure_stage": None,
        "failure_reason": None,
        "early_exit_stage": None,
        "early_exit_reason": None,
    }

    conn = connect()
    try:
        writer = PostgresWriter(conn)
        outcome = writer.persist_execution(
            pipeline_result_params=pipeline_result_params,
            opportunity_params=None,
            alert_decision_params=None,
            audit_record_params=audit_record_params,
        )
        print(outcome)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
