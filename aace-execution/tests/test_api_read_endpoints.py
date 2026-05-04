"""Integration tests for the FastAPI read endpoints.

Seeds deterministic rows directly into pipeline_results, opportunities, and
alert_decisions, then exercises the HTTP layer via FastAPI's TestClient.

Requires PostgreSQL env vars (POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB,
POSTGRES_USER, POSTGRES_PASSWORD); skipped otherwise.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psycopg  # noqa: E402
import pytest  # type: ignore  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from aace_execution.api.main import app  # noqa: E402
from aace_execution.persistence.db import connect  # noqa: E402


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


BASE_TS = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)

EXEC_A = "api-read-it-exec-a"
EXEC_B = "api-read-it-exec-b"
EXEC_MISSING = "api-read-it-exec-missing"

PRODUCT_A = "api-read-it-product-a"
PRODUCT_B = "api-read-it-product-b"

SEEDED_EXECUTIONS = (EXEC_A, EXEC_B)


def _delete_seeded(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for exec_id in (*SEEDED_EXECUTIONS, EXEC_MISSING):
            cur.execute(
                "DELETE FROM alert_decisions WHERE pipeline_execution_id = %s",
                (exec_id,),
            )
            cur.execute(
                "DELETE FROM opportunities WHERE pipeline_execution_id = %s",
                (exec_id,),
            )
            cur.execute(
                "DELETE FROM pipeline_results WHERE pipeline_execution_id = %s",
                (exec_id,),
            )
    conn.commit()


def _seed(conn: psycopg.Connection) -> None:
    ts_a = BASE_TS
    ts_b = BASE_TS + timedelta(hours=1)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_results ("
            "pipeline_execution_id, product_id, result_classification, "
            "stage_reached, result_timestamp, stage_outcome_summary, "
            "retry_eligible, failure_stage, failure_reason"
            ") VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
            (
                EXEC_A,
                PRODUCT_A,
                "OPPORTUNITY_DETECTED",
                "RESULT_ASSEMBLY",
                ts_a,
                json.dumps(
                    [
                        {"stage": "INPUT_VALIDATION", "classification": "VALID"},
                        {
                            "stage": "RESULT_ASSEMBLY",
                            "classification": "OPPORTUNITY_DETECTED",
                        },
                    ]
                ),
                None,
                None,
                None,
            ),
        )
        cur.execute(
            "INSERT INTO pipeline_results ("
            "pipeline_execution_id, product_id, result_classification, "
            "stage_reached, result_timestamp, stage_outcome_summary, "
            "retry_eligible, failure_stage, failure_reason"
            ") VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
            (
                EXEC_B,
                PRODUCT_B,
                "OPPORTUNITY_SCORED_NO_ALERT",
                "RESULT_ASSEMBLY",
                ts_b,
                json.dumps(
                    [
                        {"stage": "INPUT_VALIDATION", "classification": "VALID"},
                        {
                            "stage": "RESULT_ASSEMBLY",
                            "classification": "OPPORTUNITY_SCORED_NO_ALERT",
                        },
                    ]
                ),
                None,
                None,
                None,
            ),
        )

        cur.execute(
            "INSERT INTO opportunities ("
            "pipeline_execution_id, product_id, pair_id, result_classification, "
            "discrepancy_rule_id, discrepancy_source_a, discrepancy_source_b, "
            "price_a, price_b, absolute_difference, percentage_difference, "
            "score, score_result_id, scoring_factors_applied, score_range, "
            "alert_decision, alert_decision_id, suppression_reason, "
            "opportunity_timestamp"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s::jsonb, %s::jsonb, %s, %s, %s, %s)",
            (
                EXEC_A,
                PRODUCT_A,
                "pair-a",
                "OPPORTUNITY_DETECTED",
                "rule-a",
                "source_a",
                "source_b",
                100.0,
                110.0,
                10.0,
                0.1,
                42.0,
                "score-a",
                json.dumps([]),
                json.dumps({"min": 0.0, "max": 100.0}),
                "ALERT_ELIGIBLE",
                "alert-a",
                None,
                ts_a,
            ),
        )
        cur.execute(
            "INSERT INTO opportunities ("
            "pipeline_execution_id, product_id, pair_id, result_classification, "
            "discrepancy_rule_id, discrepancy_source_a, discrepancy_source_b, "
            "price_a, price_b, absolute_difference, percentage_difference, "
            "score, score_result_id, scoring_factors_applied, score_range, "
            "alert_decision, alert_decision_id, suppression_reason, "
            "opportunity_timestamp"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s::jsonb, %s::jsonb, %s, %s, %s, %s)",
            (
                EXEC_B,
                PRODUCT_B,
                "pair-b",
                "OPPORTUNITY_SCORED_NO_ALERT",
                "rule-b",
                "source_a",
                "source_b",
                200.0,
                205.0,
                5.0,
                0.025,
                17.0,
                "score-b",
                json.dumps([]),
                json.dumps({"min": 0.0, "max": 100.0}),
                "NO_ALERT",
                "alert-b",
                "below_threshold",
                ts_b,
            ),
        )

        cur.execute(
            "INSERT INTO alert_decisions ("
            "pipeline_execution_id, notification_type, alert_decision_id, "
            "product_id, pair_id, score, alert_threshold, threshold_met, "
            "decision_result, suppression_reason, decision_basis, "
            "duplicate_check_result, decision_reference_timestamp"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, "
            "%s, %s)",
            (
                EXEC_A,
                "EMAIL",
                "alert-a",
                PRODUCT_A,
                "pair-a",
                42.0,
                10.0,
                True,
                "ALERT_ELIGIBLE",
                None,
                json.dumps([]),
                "NO_PRIOR_ALERT",
                ts_a,
            ),
        )
        cur.execute(
            "INSERT INTO alert_decisions ("
            "pipeline_execution_id, notification_type, alert_decision_id, "
            "product_id, pair_id, score, alert_threshold, threshold_met, "
            "decision_result, suppression_reason, decision_basis, "
            "duplicate_check_result, decision_reference_timestamp"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, "
            "%s, %s)",
            (
                EXEC_B,
                "EMAIL",
                "alert-b",
                PRODUCT_B,
                "pair-b",
                17.0,
                50.0,
                False,
                "NO_ALERT",
                "below_threshold",
                json.dumps([]),
                "NO_PRIOR_ALERT",
                ts_b,
            ),
        )
    conn.commit()


@pytest.fixture(scope="module")
def seeded_db() -> Iterator[None]:
    connection = connect()
    try:
        _delete_seeded(connection)
        _seed(connection)
        yield
        _delete_seeded(connection)
    finally:
        connection.close()


_TEST_API_KEY = "test-api-key"


@pytest.fixture(scope="module")
def client(seeded_db: None) -> Iterator[TestClient]:
    prior = os.environ.get("AACE_API_KEY")
    os.environ["AACE_API_KEY"] = _TEST_API_KEY
    try:
        with TestClient(app, headers={"X-API-Key": _TEST_API_KEY}) as test_client:
            yield test_client
    finally:
        if prior is None:
            os.environ.pop("AACE_API_KEY", None)
        else:
            os.environ["AACE_API_KEY"] = prior


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_pipeline_result_returns_seeded_row(client: TestClient) -> None:
    response = client.get(f"/pipeline-results/{EXEC_A}")
    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_execution_id"] == EXEC_A
    assert body["product_id"] == PRODUCT_A
    assert body["result_classification"] == "OPPORTUNITY_DETECTED"
    assert body["stage_reached"] == "RESULT_ASSEMBLY"
    assert isinstance(body["result_timestamp"], str)
    assert isinstance(body["stage_outcome_summary"], list)


def test_get_pipeline_result_missing_returns_404(client: TestClient) -> None:
    response = client.get(f"/pipeline-results/{EXEC_MISSING}")
    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "detail": "Pipeline result not found",
    }


def test_list_opportunities_returns_list(client: TestClient) -> None:
    response = client.get("/opportunities")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    execution_ids = {row["pipeline_execution_id"] for row in body}
    assert {EXEC_A, EXEC_B}.issubset(execution_ids)

    seeded = [
        row for row in body if row["pipeline_execution_id"] in SEEDED_EXECUTIONS
    ]
    timestamps = [row["opportunity_timestamp"] for row in seeded]
    assert timestamps == sorted(timestamps, reverse=True)

    sample = next(row for row in seeded if row["pipeline_execution_id"] == EXEC_A)
    assert isinstance(sample["price_a"], float)
    assert isinstance(sample["score"], float)


def test_list_opportunities_filters_by_product_id(client: TestClient) -> None:
    response = client.get("/opportunities", params={"product_id": PRODUCT_A})
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    assert all(row["product_id"] == PRODUCT_A for row in body)
    assert any(row["pipeline_execution_id"] == EXEC_A for row in body)
    assert all(row["pipeline_execution_id"] != EXEC_B for row in body)


def test_list_alert_decisions_returns_list(client: TestClient) -> None:
    response = client.get("/alert-decisions")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    execution_ids = {row["pipeline_execution_id"] for row in body}
    assert {EXEC_A, EXEC_B}.issubset(execution_ids)

    seeded = [
        row for row in body if row["pipeline_execution_id"] in SEEDED_EXECUTIONS
    ]
    timestamps = [row["decision_reference_timestamp"] for row in seeded]
    assert timestamps == sorted(timestamps, reverse=True)

    sample = next(row for row in seeded if row["pipeline_execution_id"] == EXEC_A)
    assert isinstance(sample["score"], float)
    assert isinstance(sample["alert_threshold"], float)
    assert sample["threshold_met"] is True


def test_list_alert_decisions_filters_by_pipeline_execution_id(
    client: TestClient,
) -> None:
    response = client.get(
        "/alert-decisions",
        params={"pipeline_execution_id": EXEC_A},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["pipeline_execution_id"] == EXEC_A
    assert body[0]["decision_result"] == "ALERT_ELIGIBLE"


_UNAUTHORIZED_BODY = {
    "error": "unauthorized",
    "detail": "Invalid or missing API key",
}


def test_pipeline_results_without_api_key_returns_401(
    seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AACE_API_KEY", "correct-key")
    with TestClient(app) as raw_client:
        response = raw_client.get(f"/pipeline-results/{EXEC_A}")
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED_BODY


def test_pipeline_results_with_wrong_api_key_returns_401(
    seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AACE_API_KEY", "correct-key")
    with TestClient(app) as raw_client:
        response = raw_client.get(
            f"/pipeline-results/{EXEC_A}", headers={"X-API-Key": "wrong-key"}
        )
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED_BODY


def test_pipeline_results_with_correct_api_key_returns_200(
    seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AACE_API_KEY", "correct-key")
    with TestClient(app) as raw_client:
        response = raw_client.get(
            f"/pipeline-results/{EXEC_A}", headers={"X-API-Key": "correct-key"}
        )
    assert response.status_code == 200
    assert response.json()["pipeline_execution_id"] == EXEC_A
