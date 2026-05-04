"""Integration tests for the FastAPI POST /run-pipeline endpoint.

Loads examples/pipeline_input_demo.json and exercises the HTTP layer via
FastAPI's TestClient against a live PostgreSQL database. Persisted rows
are cleaned up before and after the run.

Requires PostgreSQL env vars (POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB,
POSTGRES_USER, POSTGRES_PASSWORD); skipped otherwise.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
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


_DEMO_INPUT_PATH = (
    Path(__file__).resolve().parent.parent / "examples" / "pipeline_input_demo.json"
)


def _load_demo_input() -> dict:
    with _DEMO_INPUT_PATH.open() as handle:
        return json.load(handle)


def _clear_rows(conn: psycopg.Connection, execution_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM audit_records WHERE pipeline_execution_id = %s",
            (execution_id,),
        )
        cur.execute(
            "DELETE FROM alert_decisions WHERE pipeline_execution_id = %s",
            (execution_id,),
        )
        cur.execute(
            "DELETE FROM opportunities WHERE pipeline_execution_id = %s",
            (execution_id,),
        )
        cur.execute(
            "DELETE FROM pipeline_results WHERE pipeline_execution_id = %s",
            (execution_id,),
        )
    conn.commit()


@pytest.fixture
def cleaned_execution() -> Iterator[str]:
    execution_id = _load_demo_input()["pipeline_execution_id"]
    connection = connect()
    try:
        _clear_rows(connection, execution_id)
        yield execution_id
        _clear_rows(connection, execution_id)
    finally:
        connection.close()


_TEST_API_KEY = "test-api-key"


@pytest.fixture
def client() -> Iterator[TestClient]:
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


def test_run_pipeline_returns_opportunity_detected(
    client: TestClient, cleaned_execution: str
) -> None:
    payload = _load_demo_input()

    response = client.post("/run-pipeline", json=payload)

    assert response.status_code == 200
    body = response.json()

    assert body["result"] == "OPPORTUNITY_DETECTED"
    assert body["pipeline_execution_id"] == cleaned_execution
    assert body["product_id"] == payload["product_id"]

    stage_outputs = body["stage_outputs"]
    assert isinstance(stage_outputs, dict)
    assert stage_outputs["input_validation"] is not None
    assert stage_outputs["discrepancy_detection"] is not None
    assert stage_outputs["opportunity_scoring"] is not None
    assert stage_outputs["alert_decision"] is not None

    audit = body["audit"]
    assert isinstance(audit, dict)
    assert audit["pipeline_execution_id"] == cleaned_execution
    assert audit["final_result"] == "OPPORTUNITY_DETECTED"
    assert isinstance(audit["stage_outcomes"], list)
    assert len(audit["stage_outcomes"]) > 0


def test_run_pipeline_invalid_payload_returns_422(client: TestClient) -> None:
    response = client.post("/run-pipeline", json={"pipeline_execution_id": "x"})

    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert isinstance(body["detail"], list)
    assert len(body["detail"]) > 0

    first_error = body["detail"][0]
    assert "type" in first_error
    assert "loc" in first_error
    assert "msg" in first_error
    assert first_error["loc"][0] == "body"

    missing_fields = {
        tuple(err["loc"]) for err in body["detail"] if err["type"] == "missing"
    }
    assert ("body", "product_id") in missing_fields


_UNAUTHORIZED_BODY = {
    "error": "unauthorized",
    "detail": "Invalid or missing API key",
}


def test_run_pipeline_without_api_key_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AACE_API_KEY", "correct-key")
    with TestClient(app) as raw_client:
        response = raw_client.post("/run-pipeline", json=_load_demo_input())
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED_BODY


def test_run_pipeline_with_wrong_api_key_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AACE_API_KEY", "correct-key")
    with TestClient(app) as raw_client:
        response = raw_client.post(
            "/run-pipeline",
            json=_load_demo_input(),
            headers={"X-API-Key": "wrong-key"},
        )
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED_BODY


def test_run_pipeline_with_correct_api_key_returns_200(
    cleaned_execution: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AACE_API_KEY", "correct-key")
    with TestClient(app) as raw_client:
        response = raw_client.post(
            "/run-pipeline",
            json=_load_demo_input(),
            headers={"X-API-Key": "correct-key"},
        )
    assert response.status_code == 200
    assert response.json()["pipeline_execution_id"] == cleaned_execution
