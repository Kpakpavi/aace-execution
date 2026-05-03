"""Integration tests for the FastAPI analytics endpoints.

Seeds deterministic rows directly into the opportunities table, then exercises
the HTTP layer via FastAPI's TestClient. Validates counts, average score,
top-products ordering, and alert-rate percentages against the seeded slice,
so these assertions remain correct even when other rows exist in the table.

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

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "aace-execution" / "src"))

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


BASE_TS = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)

EXEC_1 = "api-analytics-it-exec-1"
EXEC_2 = "api-analytics-it-exec-2"
EXEC_3 = "api-analytics-it-exec-3"
EXEC_4 = "api-analytics-it-exec-4"
EXEC_5 = "api-analytics-it-exec-5"

PRODUCT_TOP = "api-analytics-it-product-top"
PRODUCT_MID = "api-analytics-it-product-mid"
PRODUCT_LOW = "api-analytics-it-product-low"
PRODUCT_BULK = "api-analytics-it-product-bulk"

# Bulk seed used by high-score-opportunities tests: 11 rows with deliberately
# high, strictly-increasing scores (1001..1011) so they sort above any other
# rows in a shared DB and let us unambiguously exercise LIMIT 10 and DESC.
BULK_COUNT = 11
BULK_SCORE_BASE = 1000.0
BULK_EXECUTIONS = tuple(
    f"api-analytics-it-exec-bulk-{i:02d}" for i in range(1, BULK_COUNT + 1)
)

SEEDED_EXECUTIONS = (EXEC_1, EXEC_2, EXEC_3, EXEC_4, EXEC_5, *BULK_EXECUTIONS)

# Seeded distribution:
#   PRODUCT_TOP:  EXEC_1, EXEC_2, EXEC_3  (3 opps — 2 ALERT_ELIGIBLE, 1 NO_ALERT)
#   PRODUCT_MID:  EXEC_4, EXEC_5          (2 opps — 1 ALERT_ELIGIBLE, 1 NO_ALERT)
#   PRODUCT_LOW:  (none; used for zero-safe assertions)
#   PRODUCT_BULK: 11 opps with scores 1001..1011 (all ALERT_ELIGIBLE)
#
# Base scores for EXEC_1..EXEC_5: 10, 20, 30, 40, 50 -> average = 30.0
# Base alert decisions: 3 ALERT_ELIGIBLE, 2 NO_ALERT
SEEDED_ROWS = (
    (EXEC_1, PRODUCT_TOP, "ALERT_ELIGIBLE", 10.0, 0),
    (EXEC_2, PRODUCT_TOP, "ALERT_ELIGIBLE", 20.0, 1),
    (EXEC_3, PRODUCT_TOP, "NO_ALERT", 30.0, 2),
    (EXEC_4, PRODUCT_MID, "ALERT_ELIGIBLE", 40.0, 3),
    (EXEC_5, PRODUCT_MID, "NO_ALERT", 50.0, 4),
    *(
        (
            BULK_EXECUTIONS[i],
            PRODUCT_BULK,
            "ALERT_ELIGIBLE",
            BULK_SCORE_BASE + (i + 1),
            100 + i,
        )
        for i in range(BULK_COUNT)
    ),
)


def _delete_seeded(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for exec_id in SEEDED_EXECUTIONS:
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
    with conn.cursor() as cur:
        for exec_id, product_id, alert_decision, score, hour_offset in SEEDED_ROWS:
            ts = BASE_TS + timedelta(hours=hour_offset)
            suppression = "below_threshold" if alert_decision == "NO_ALERT" else None
            classification = (
                "OPPORTUNITY_DETECTED"
                if alert_decision == "ALERT_ELIGIBLE"
                else "OPPORTUNITY_SCORED_NO_ALERT"
            )

            cur.execute(
                "INSERT INTO pipeline_results ("
                "pipeline_execution_id, product_id, result_classification, "
                "stage_reached, result_timestamp, stage_outcome_summary, "
                "retry_eligible, failure_stage, failure_reason"
                ") VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
                (
                    exec_id,
                    product_id,
                    classification,
                    "RESULT_ASSEMBLY",
                    ts,
                    json.dumps(
                        [
                            {"stage": "INPUT_VALIDATION", "classification": "VALID"},
                            {
                                "stage": "RESULT_ASSEMBLY",
                                "classification": classification,
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
                    exec_id,
                    product_id,
                    f"pair-{exec_id}",
                    classification,
                    f"rule-{exec_id}",
                    "source_a",
                    "source_b",
                    100.0,
                    110.0,
                    10.0,
                    0.1,
                    score,
                    f"score-{exec_id}",
                    json.dumps([]),
                    json.dumps({"min": 0.0, "max": 100.0}),
                    alert_decision,
                    f"alert-{exec_id}",
                    suppression,
                    ts,
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


@pytest.fixture
def seeded_opportunity_counts() -> Iterator[tuple[int, int, int, float]]:
    """Return totals observed in the opportunities table *excluding* seeded rows.

    Lets tests check that the endpoint's totals equal (pre-existing + seeded)
    rather than guessing absolute numbers in a shared database.
    """
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*), "
                "COUNT(*) FILTER (WHERE alert_decision = 'ALERT_ELIGIBLE'), "
                "COUNT(*) FILTER (WHERE alert_decision = 'NO_ALERT'), "
                "COALESCE(SUM(score), 0) "
                "FROM opportunities "
                "WHERE NOT (pipeline_execution_id = ANY(%s))",
                (list(SEEDED_EXECUTIONS),),
            )
            total, alert_eligible, no_alert, score_sum = cursor.fetchone()
    finally:
        connection.close()
    yield (int(total), int(alert_eligible), int(no_alert), float(score_sum))


_SEEDED_TOTAL = len(SEEDED_ROWS)
_SEEDED_ALERT = sum(1 for row in SEEDED_ROWS if row[2] == "ALERT_ELIGIBLE")
_SEEDED_NO_ALERT = sum(1 for row in SEEDED_ROWS if row[2] == "NO_ALERT")
_SEEDED_SCORE_SUM = sum(row[3] for row in SEEDED_ROWS)


def test_opportunity_summary_returns_200_and_reflects_seeded_rows(
    client: TestClient,
    seeded_opportunity_counts: tuple[int, int, int, float],
) -> None:
    pre_total, pre_alert, pre_no_alert, pre_score_sum = seeded_opportunity_counts

    response = client.get("/analytics/opportunity-summary")
    assert response.status_code == 200
    body = response.json()

    expected_total = pre_total + _SEEDED_TOTAL
    expected_alert = pre_alert + _SEEDED_ALERT
    expected_no_alert = pre_no_alert + _SEEDED_NO_ALERT
    expected_avg = (pre_score_sum + _SEEDED_SCORE_SUM) / expected_total

    assert body["total_opportunities"] == expected_total
    assert body["alert_eligible"] == expected_alert
    assert body["no_alert"] == expected_no_alert
    assert body["average_score"] is not None
    assert body["average_score"] == pytest.approx(expected_avg, rel=1e-6)


def test_top_products_returns_200_with_correct_ordering_and_counts(
    client: TestClient,
) -> None:
    response = client.get("/analytics/top-products")
    assert response.status_code == 200
    body = response.json()

    assert isinstance(body, list)
    assert len(body) <= 10

    by_product = {row["product_id"]: row["opportunity_count"] for row in body}
    assert PRODUCT_LOW not in by_product

    counts = [row["opportunity_count"] for row in body]
    assert counts == sorted(counts, reverse=True)

    if PRODUCT_TOP in by_product and PRODUCT_MID in by_product:
        assert by_product[PRODUCT_TOP] == 3
        assert by_product[PRODUCT_MID] == 2
        top_index = next(
            i for i, r in enumerate(body) if r["product_id"] == PRODUCT_TOP
        )
        mid_index = next(
            i for i, r in enumerate(body) if r["product_id"] == PRODUCT_MID
        )
        assert top_index < mid_index


def test_alert_rate_returns_200_with_correct_percentages(
    client: TestClient,
    seeded_opportunity_counts: tuple[int, int, int, float],
) -> None:
    pre_total, pre_alert, pre_no_alert, _ = seeded_opportunity_counts

    response = client.get("/analytics/alert-rate")
    assert response.status_code == 200
    body = response.json()

    expected_total = pre_total + _SEEDED_TOTAL
    expected_alert = pre_alert + _SEEDED_ALERT
    expected_no_alert = pre_no_alert + _SEEDED_NO_ALERT
    expected_alert_rate = 100.0 * expected_alert / expected_total
    expected_no_alert_rate = 100.0 * expected_no_alert / expected_total

    assert body["total_opportunities"] == expected_total
    assert body["alert_eligible"] == expected_alert
    assert body["no_alert"] == expected_no_alert
    assert body["alert_rate_percent"] == pytest.approx(expected_alert_rate, rel=1e-6)
    assert body["no_alert_rate_percent"] == pytest.approx(
        expected_no_alert_rate, rel=1e-6
    )
    assert body["alert_rate_percent"] + body["no_alert_rate_percent"] == pytest.approx(
        100.0 * (expected_alert + expected_no_alert) / expected_total, rel=1e-6
    )


def test_analytics_endpoints_zero_safe_when_opportunities_empty() -> None:
    """Validate zero-safe behavior by isolating the opportunities table.

    Skipped when the live table holds rows outside the seeded fixture scope,
    since clearing them would corrupt parallel work on a shared database.
    """
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM opportunities")
            (existing_rows,) = cursor.fetchone()
    finally:
        connection.close()

    if existing_rows != 0:
        pytest.skip(
            "opportunities table is not empty; zero-safe path requires isolation."
        )

    prior = os.environ.get("AACE_API_KEY")
    os.environ["AACE_API_KEY"] = _TEST_API_KEY
    try:
        with TestClient(
            app, headers={"X-API-Key": _TEST_API_KEY}
        ) as empty_client:
            summary = empty_client.get("/analytics/opportunity-summary")
            assert summary.status_code == 200
            summary_body = summary.json()
            assert summary_body["total_opportunities"] == 0
            assert summary_body["alert_eligible"] == 0
            assert summary_body["no_alert"] == 0
            assert summary_body["average_score"] is None

            top = empty_client.get("/analytics/top-products")
            assert top.status_code == 200
            assert top.json() == []

            rate = empty_client.get("/analytics/alert-rate")
            assert rate.status_code == 200
            rate_body = rate.json()
            assert rate_body["total_opportunities"] == 0
            assert rate_body["alert_eligible"] == 0
            assert rate_body["no_alert"] == 0
            assert rate_body["alert_rate_percent"] == 0.0
            assert rate_body["no_alert_rate_percent"] == 0.0

            high = empty_client.get("/analytics/high-score-opportunities")
            assert high.status_code == 200
            assert high.json() == []
    finally:
        if prior is None:
            os.environ.pop("AACE_API_KEY", None)
        else:
            os.environ["AACE_API_KEY"] = prior


_HIGH_SCORE_FIELDS = {
    "pipeline_execution_id",
    "product_id",
    "pair_id",
    "score",
    "result_classification",
    "alert_decision",
    "opportunity_timestamp",
}


def test_high_score_opportunities_returns_200_with_expected_fields(
    client: TestClient,
) -> None:
    response = client.get("/analytics/high-score-opportunities")
    assert response.status_code == 200
    body = response.json()

    assert isinstance(body, list)
    assert len(body) >= 1
    sample = body[0]
    assert _HIGH_SCORE_FIELDS.issubset(sample.keys())
    assert isinstance(sample["score"], float)
    assert isinstance(sample["opportunity_timestamp"], str)


def test_high_score_opportunities_orders_by_score_desc(client: TestClient) -> None:
    response = client.get("/analytics/high-score-opportunities")
    assert response.status_code == 200
    body = response.json()

    scores = [row["score"] for row in body]
    assert scores == sorted(scores, reverse=True)

    # Bulk-seeded rows have scores 1001..1011, deliberately above any other
    # seeded rows, so they must populate the top of the DESC-ordered response.
    bulk_rows = [row for row in body if row["product_id"] == PRODUCT_BULK]
    assert len(bulk_rows) >= 1
    top_score = body[0]["score"]
    assert top_score == pytest.approx(BULK_SCORE_BASE + BULK_COUNT)


def test_high_score_opportunities_caps_at_10_rows(client: TestClient) -> None:
    response = client.get("/analytics/high-score-opportunities")
    assert response.status_code == 200
    body = response.json()

    assert len(body) <= 10
    # With 11 bulk rows at scores 1001..1011 plus any other rows in the shared
    # table, the response must be saturated at exactly the LIMIT of 10.
    assert len(body) == 10


def test_high_score_opportunities_filters_by_min_score(client: TestClient) -> None:
    response = client.get(
        "/analytics/high-score-opportunities",
        params={"min_score": BULK_SCORE_BASE + 5},
    )
    assert response.status_code == 200
    body = response.json()

    assert all(row["score"] >= BULK_SCORE_BASE + 5 for row in body)
    # Bulk scores 1005..1011 → 7 qualifying rows from the seed alone.
    bulk_rows = [row for row in body if row["product_id"] == PRODUCT_BULK]
    assert len(bulk_rows) == 7
    bulk_scores = sorted(
        (row["score"] for row in bulk_rows),
        reverse=True,
    )
    assert bulk_scores == [
        BULK_SCORE_BASE + 11,
        BULK_SCORE_BASE + 10,
        BULK_SCORE_BASE + 9,
        BULK_SCORE_BASE + 8,
        BULK_SCORE_BASE + 7,
        BULK_SCORE_BASE + 6,
        BULK_SCORE_BASE + 5,
    ]


def test_high_score_opportunities_filters_by_product_id(client: TestClient) -> None:
    response = client.get(
        "/analytics/high-score-opportunities",
        params={"product_id": PRODUCT_TOP},
    )
    assert response.status_code == 200
    body = response.json()

    assert len(body) == 3
    assert all(row["product_id"] == PRODUCT_TOP for row in body)
    scores = [row["score"] for row in body]
    assert scores == sorted(scores, reverse=True)
    assert scores == [30.0, 20.0, 10.0]


def test_high_score_opportunities_returns_empty_list_for_strict_filter(
    client: TestClient,
) -> None:
    response = client.get(
        "/analytics/high-score-opportunities",
        params={"product_id": PRODUCT_LOW, "min_score": 10_000_000},
    )
    assert response.status_code == 200
    assert response.json() == []


# Day buckets derived from BASE_TS=2026-04-20T12:00Z + hour_offset:
#   base rows (offsets 0..4):  all fall on 2026-04-20
#   bulk offsets 100..107 (+4d 4..11h): all fall on 2026-04-24 (8 rows)
#   bulk offsets 108..110 (+4d 12..14h): all fall on 2026-04-25 (3 rows)
_DAY_BASE = "2026-04-20"
_DAY_BULK_A = "2026-04-24"
_DAY_BULK_B = "2026-04-25"

# Expected seeded per-day contribution by product:
#   PRODUCT_TOP: {2026-04-20: count=3, alert=2, no_alert=1}
#   PRODUCT_MID: {2026-04-20: count=2, alert=1, no_alert=1}
#   PRODUCT_BULK: {2026-04-24: count=8, alert=8, no_alert=0;
#                  2026-04-25: count=3, alert=3, no_alert=0}


def test_daily_opportunities_returns_200_with_expected_fields(
    client: TestClient,
) -> None:
    response = client.get("/analytics/daily-opportunities")
    assert response.status_code == 200
    body = response.json()

    assert isinstance(body, list)
    assert len(body) >= 2  # base day + at least one bulk day from our seed
    sample = body[0]
    assert set(sample.keys()) >= {
        "day",
        "opportunity_count",
        "alert_eligible_count",
        "no_alert_count",
    }
    assert isinstance(sample["day"], str)
    assert isinstance(sample["opportunity_count"], int)
    assert isinstance(sample["alert_eligible_count"], int)
    assert isinstance(sample["no_alert_count"], int)


def test_daily_opportunities_orders_by_day_ascending(client: TestClient) -> None:
    response = client.get("/analytics/daily-opportunities")
    assert response.status_code == 200
    body = response.json()

    days = [row["day"] for row in body]
    assert days == sorted(days)
    assert len(days) == len(set(days))  # each day appears at most once


def test_daily_opportunities_bucket_counts_include_seeded_rows(
    client: TestClient,
) -> None:
    response = client.get("/analytics/daily-opportunities")
    assert response.status_code == 200
    body = response.json()

    by_day = {row["day"]: row for row in body}

    # Base day holds at least PRODUCT_TOP (3) + PRODUCT_MID (2) = 5 rows,
    # with 3 ALERT_ELIGIBLE and 2 NO_ALERT from our seed.
    assert _DAY_BASE in by_day
    assert by_day[_DAY_BASE]["opportunity_count"] >= 5
    assert by_day[_DAY_BASE]["alert_eligible_count"] >= 3
    assert by_day[_DAY_BASE]["no_alert_count"] >= 2
    assert (
        by_day[_DAY_BASE]["alert_eligible_count"]
        + by_day[_DAY_BASE]["no_alert_count"]
        <= by_day[_DAY_BASE]["opportunity_count"]
    )

    # Bulk days carry only PRODUCT_BULK rows from our seed (8 then 3),
    # all ALERT_ELIGIBLE.
    assert _DAY_BULK_A in by_day
    assert by_day[_DAY_BULK_A]["opportunity_count"] >= 8
    assert by_day[_DAY_BULK_A]["alert_eligible_count"] >= 8

    assert _DAY_BULK_B in by_day
    assert by_day[_DAY_BULK_B]["opportunity_count"] >= 3
    assert by_day[_DAY_BULK_B]["alert_eligible_count"] >= 3


def test_daily_opportunities_filters_by_product_id_top(client: TestClient) -> None:
    response = client.get(
        "/analytics/daily-opportunities",
        params={"product_id": PRODUCT_TOP},
    )
    assert response.status_code == 200
    body = response.json()

    # PRODUCT_TOP rows exist only on the base day, so exact-equality is safe.
    assert len(body) == 1
    row = body[0]
    assert row["day"] == _DAY_BASE
    assert row["opportunity_count"] == 3
    assert row["alert_eligible_count"] == 2
    assert row["no_alert_count"] == 1


def test_daily_opportunities_filters_by_product_id_bulk(client: TestClient) -> None:
    response = client.get(
        "/analytics/daily-opportunities",
        params={"product_id": PRODUCT_BULK},
    )
    assert response.status_code == 200
    body = response.json()

    assert len(body) == 2
    days = [row["day"] for row in body]
    assert days == [_DAY_BULK_A, _DAY_BULK_B]

    by_day = {row["day"]: row for row in body}
    assert by_day[_DAY_BULK_A]["opportunity_count"] == 8
    assert by_day[_DAY_BULK_A]["alert_eligible_count"] == 8
    assert by_day[_DAY_BULK_A]["no_alert_count"] == 0
    assert by_day[_DAY_BULK_B]["opportunity_count"] == 3
    assert by_day[_DAY_BULK_B]["alert_eligible_count"] == 3
    assert by_day[_DAY_BULK_B]["no_alert_count"] == 0


def test_daily_opportunities_returns_empty_list_when_filter_matches_nothing(
    client: TestClient,
) -> None:
    response = client.get(
        "/analytics/daily-opportunities",
        params={"product_id": PRODUCT_LOW},
    )
    assert response.status_code == 200
    assert response.json() == []


_UNAUTHORIZED_BODY = {
    "error": "unauthorized",
    "detail": "Invalid or missing API key",
}


def test_opportunity_summary_without_api_key_returns_401(
    seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AACE_API_KEY", "correct-key")
    with TestClient(app) as raw_client:
        response = raw_client.get("/analytics/opportunity-summary")
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED_BODY


def test_opportunity_summary_with_wrong_api_key_returns_401(
    seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AACE_API_KEY", "correct-key")
    with TestClient(app) as raw_client:
        response = raw_client.get(
            "/analytics/opportunity-summary", headers={"X-API-Key": "wrong-key"}
        )
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED_BODY


def test_opportunity_summary_with_correct_api_key_returns_200(
    seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AACE_API_KEY", "correct-key")
    with TestClient(app) as raw_client:
        response = raw_client.get(
            "/analytics/opportunity-summary", headers={"X-API-Key": "correct-key"}
        )
    assert response.status_code == 200
    assert "total_opportunities" in response.json()
