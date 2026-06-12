import hmac
import logging
import os
from dataclasses import asdict
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from aace_execution.api.models import RunPipelineRequest
from aace_execution.api.responses import RunPipelineResponse
from aace_execution.connectors.resale_comps import (
    KeepaClient,
    RoutedResaleCompsClient,
    SerpApiClient,
)
from aace_execution.observability import init_sentry

from aace_execution.persistence.db import connect
from aace_execution.persistence.postgres_writer import PostgresWriter
from aace_execution.pipeline.pipeline_runner import PipelineRunner
from aace_execution.validators.input_validator import (
    InputValidator,
    ValidationContext,
)

ALLOWED_SOURCES = frozenset({"source_a", "source_b"})
FRESHNESS_WINDOW_SECONDS = 3600

logger = logging.getLogger(__name__)

init_sentry(service_name="aace-api")

app = FastAPI(
    title="AACE Execution API",
    description=(
        "HTTP interface to the Autonomous Arbitrage Commerce Engine "
        "pipeline: run a pipeline execution and read back pipeline results, "
        "opportunities, and alert decisions."
    ),
)


_UNAUTHORIZED_BODY = {
    "error": "unauthorized",
    "detail": "Invalid or missing API key",
}


@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    if request.method == "GET" and request.url.path == "/health":
        return await call_next(request)
    expected = os.environ.get("AACE_API_KEY")
    provided = request.headers.get("X-API-Key")
    if (
        expected is None
        or provided is None
        or not hmac.compare_digest(provided, expected)
    ):
        return JSONResponse(status_code=401, content=_UNAUTHORIZED_BODY)
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail}
    )


@app.get("/health", summary="Service liveness probe")
def health() -> dict[str, str]:
    return {"status": "ok"}


_PIPELINE_RESULT_COLUMNS = (
    "pipeline_execution_id",
    "product_id",
    "result_classification",
    "stage_reached",
    "result_timestamp",
    "stage_outcome_summary",
    "retry_eligible",
    "failure_stage",
    "failure_reason",
)


@app.get(
    "/pipeline-results/{pipeline_execution_id}",
    summary="Fetch a pipeline result by execution id",
    description=(
        "Return the persisted pipeline_results row for the given "
        "pipeline_execution_id, or 404 if it does not exist."
    ),
)
def get_pipeline_result(pipeline_execution_id: str) -> dict:
    try:
        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pipeline_execution_id, product_id, "
                    "result_classification, stage_reached, result_timestamp, "
                    "stage_outcome_summary, retry_eligible, failure_stage, "
                    "failure_reason "
                    "FROM pipeline_results "
                    "WHERE pipeline_execution_id = %s",
                    (pipeline_execution_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "detail": "Pipeline result not found",
                },
            )

        record = dict(zip(_PIPELINE_RESULT_COLUMNS, row))
        if record["result_timestamp"] is not None:
            record["result_timestamp"] = record["result_timestamp"].isoformat()
        return record
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_pipeline_result_internal_error")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "detail": "Pipeline result lookup failed",
            },
        )


_OPPORTUNITY_COLUMNS = (
    "pipeline_execution_id",
    "product_id",
    "pair_id",
    "result_classification",
    "discrepancy_rule_id",
    "discrepancy_source_a",
    "discrepancy_source_b",
    "price_a",
    "price_b",
    "absolute_difference",
    "percentage_difference",
    "score",
    "score_result_id",
    "scoring_factors_applied",
    "score_range",
    "alert_decision",
    "alert_decision_id",
    "suppression_reason",
    "opportunity_timestamp",
)

_OPPORTUNITY_NUMERIC_FIELDS = frozenset({
    "price_a",
    "price_b",
    "absolute_difference",
    "percentage_difference",
    "score",
})


@app.get(
    "/opportunities",
    summary="List persisted opportunities",
    description=(
        "Return opportunities rows ordered by opportunity_timestamp "
        "descending, optionally filtered by product or result "
        "classification."
    ),
)
def list_opportunities(
    product_id: str | None = Query(
        None, description="Filter to opportunities for this product_id."
    ),
    result_classification: str | None = Query(
        None,
        description=(
            "Filter by result classification "
            "(OPPORTUNITY_DETECTED or OPPORTUNITY_SCORED_NO_ALERT)."
        ),
    ),
) -> list[dict]:
    try:
        sql = (
            "SELECT pipeline_execution_id, product_id, pair_id, "
            "result_classification, discrepancy_rule_id, "
            "discrepancy_source_a, discrepancy_source_b, price_a, price_b, "
            "absolute_difference, percentage_difference, score, "
            "score_result_id, scoring_factors_applied, score_range, "
            "alert_decision, alert_decision_id, suppression_reason, "
            "opportunity_timestamp "
            "FROM opportunities"
        )
        clauses: list[str] = []
        params: list[str] = []
        if product_id is not None:
            clauses.append("product_id = %s")
            params.append(product_id)
        if result_classification is not None:
            clauses.append("result_classification = %s")
            params.append(result_classification)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY opportunity_timestamp DESC"

        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
        finally:
            connection.close()

        records: list[dict] = []
        for row in rows:
            record = dict(zip(_OPPORTUNITY_COLUMNS, row))
            if record["opportunity_timestamp"] is not None:
                record["opportunity_timestamp"] = record[
                    "opportunity_timestamp"
                ].isoformat()
            for field in _OPPORTUNITY_NUMERIC_FIELDS:
                value = record.get(field)
                if isinstance(value, Decimal):
                    record[field] = float(value)
            records.append(record)
        return records
    except HTTPException:
        raise
    except Exception:
        logger.exception("list_opportunities_internal_error")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "detail": "Opportunities lookup failed",
            },
        )


_ALERT_DECISION_COLUMNS = (
    "pipeline_execution_id",
    "notification_type",
    "alert_decision_id",
    "product_id",
    "pair_id",
    "score",
    "alert_threshold",
    "threshold_met",
    "decision_result",
    "suppression_reason",
    "decision_basis",
    "duplicate_check_result",
    "decision_reference_timestamp",
)

_ALERT_DECISION_NUMERIC_FIELDS = frozenset({"score", "alert_threshold"})


@app.get(
    "/alert-decisions",
    summary="List persisted alert decisions",
    description=(
        "Return alert_decisions rows ordered by "
        "decision_reference_timestamp descending, optionally filtered by "
        "execution, product, decision result, or notification type."
    ),
)
def list_alert_decisions(
    pipeline_execution_id: str | None = Query(
        None, description="Filter to decisions for this pipeline execution."
    ),
    product_id: str | None = Query(
        None, description="Filter to decisions for this product_id."
    ),
    decision_result: str | None = Query(
        None,
        description="Filter by decision result (ALERT_ELIGIBLE or NO_ALERT).",
    ),
    notification_type: str | None = Query(
        None, description="Filter by notification type."
    ),
) -> list[dict]:
    try:
        sql = (
            "SELECT pipeline_execution_id, notification_type, "
            "alert_decision_id, product_id, pair_id, score, alert_threshold, "
            "threshold_met, decision_result, suppression_reason, "
            "decision_basis, duplicate_check_result, "
            "decision_reference_timestamp "
            "FROM alert_decisions"
        )
        clauses: list[str] = []
        params: list[str] = []
        if pipeline_execution_id is not None:
            clauses.append("pipeline_execution_id = %s")
            params.append(pipeline_execution_id)
        if product_id is not None:
            clauses.append("product_id = %s")
            params.append(product_id)
        if decision_result is not None:
            clauses.append("decision_result = %s")
            params.append(decision_result)
        if notification_type is not None:
            clauses.append("notification_type = %s")
            params.append(notification_type)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY decision_reference_timestamp DESC"

        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
        finally:
            connection.close()

        records: list[dict] = []
        for row in rows:
            record = dict(zip(_ALERT_DECISION_COLUMNS, row))
            if record["decision_reference_timestamp"] is not None:
                record["decision_reference_timestamp"] = record[
                    "decision_reference_timestamp"
                ].isoformat()
            for field in _ALERT_DECISION_NUMERIC_FIELDS:
                value = record.get(field)
                if isinstance(value, Decimal):
                    record[field] = float(value)
            records.append(record)
        return records
    except HTTPException:
        raise
    except Exception:
        logger.exception("list_alert_decisions_internal_error")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "detail": "Alert decisions lookup failed",
            },
        )


@app.get(
    "/analytics/opportunity-summary",
    summary="Aggregate opportunity counts and average score",
    description=(
        "Return total opportunity count, ALERT_ELIGIBLE and NO_ALERT counts, "
        "and the average score across all persisted opportunities. Counts "
        "are zero and average_score is null when no rows exist."
    ),
)
def get_opportunity_summary() -> dict:
    try:
        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS total_opportunities, "
                    "COUNT(*) FILTER (WHERE alert_decision = 'ALERT_ELIGIBLE') "
                    "AS alert_eligible, "
                    "COUNT(*) FILTER (WHERE alert_decision = 'NO_ALERT') "
                    "AS no_alert, "
                    "AVG(score) AS average_score "
                    "FROM opportunities"
                )
                row = cursor.fetchone()
        finally:
            connection.close()

        total, alert_eligible, no_alert, average_score = row
        if isinstance(average_score, Decimal):
            average_score = float(average_score)
        return {
            "total_opportunities": int(total),
            "alert_eligible": int(alert_eligible),
            "no_alert": int(no_alert),
            "average_score": average_score,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_opportunity_summary_internal_error")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "detail": "Opportunity summary lookup failed",
            },
        )


@app.get(
    "/analytics/top-products",
    summary="Top products by opportunity count",
    description=(
        "Return up to the top 10 products ranked by number of persisted "
        "opportunities, ordered by count descending. Returns an empty list "
        "when no opportunities exist."
    ),
)
def get_top_products() -> list[dict]:
    try:
        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT product_id, COUNT(*) AS opportunity_count "
                    "FROM opportunities "
                    "GROUP BY product_id "
                    "ORDER BY opportunity_count DESC "
                    "LIMIT 10"
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        return [
            {"product_id": product_id, "opportunity_count": int(count)}
            for product_id, count in rows
        ]
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_top_products_internal_error")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "detail": "Top products lookup failed",
            },
        )


@app.get(
    "/analytics/alert-rate",
    summary="Alert eligibility rate across opportunities",
    description=(
        "Return total opportunity count, ALERT_ELIGIBLE and NO_ALERT counts, "
        "and the percentage of each across all persisted opportunities. "
        "When no opportunities exist, all counts and rates are zero."
    ),
)
def get_alert_rate() -> dict:
    try:
        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS total_opportunities, "
                    "COUNT(*) FILTER (WHERE alert_decision = 'ALERT_ELIGIBLE') "
                    "AS alert_eligible, "
                    "COUNT(*) FILTER (WHERE alert_decision = 'NO_ALERT') "
                    "AS no_alert, "
                    "100.0 * COUNT(*) FILTER (WHERE alert_decision = "
                    "'ALERT_ELIGIBLE') / NULLIF(COUNT(*), 0) "
                    "AS alert_rate_percent, "
                    "100.0 * COUNT(*) FILTER (WHERE alert_decision = "
                    "'NO_ALERT') / NULLIF(COUNT(*), 0) "
                    "AS no_alert_rate_percent "
                    "FROM opportunities"
                )
                row = cursor.fetchone()
        finally:
            connection.close()

        total, alert_eligible, no_alert, alert_rate, no_alert_rate = row
        if isinstance(alert_rate, Decimal):
            alert_rate = float(alert_rate)
        if isinstance(no_alert_rate, Decimal):
            no_alert_rate = float(no_alert_rate)
        return {
            "total_opportunities": int(total),
            "alert_eligible": int(alert_eligible),
            "no_alert": int(no_alert),
            "alert_rate_percent": alert_rate if alert_rate is not None else 0.0,
            "no_alert_rate_percent": (
                no_alert_rate if no_alert_rate is not None else 0.0
            ),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_alert_rate_internal_error")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "detail": "Alert rate lookup failed",
            },
        )


@app.get(
    "/analytics/high-score-opportunities",
    summary="Top 10 opportunities by score",
    description=(
        "Return up to the top 10 persisted opportunities ordered by score "
        "descending. Supports optional filters on minimum score and "
        "product_id. Returns an empty list when no matching rows exist."
    ),
)
def get_high_score_opportunities(
    min_score: float | None = Query(
        None, description="Filter to opportunities with score >= min_score."
    ),
    product_id: str | None = Query(
        None, description="Filter to opportunities for this product_id."
    ),
) -> list[dict]:
    try:
        sql = (
            "SELECT pipeline_execution_id, product_id, pair_id, score, "
            "result_classification, alert_decision, opportunity_timestamp "
            "FROM opportunities"
        )
        clauses: list[str] = []
        params: list[object] = []
        if min_score is not None:
            clauses.append("score >= %s")
            params.append(min_score)
        if product_id is not None:
            clauses.append("product_id = %s")
            params.append(product_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY score DESC LIMIT 10"

        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
        finally:
            connection.close()

        columns = (
            "pipeline_execution_id",
            "product_id",
            "pair_id",
            "score",
            "result_classification",
            "alert_decision",
            "opportunity_timestamp",
        )
        records: list[dict] = []
        for row in rows:
            record = dict(zip(columns, row))
            if record["opportunity_timestamp"] is not None:
                record["opportunity_timestamp"] = record[
                    "opportunity_timestamp"
                ].isoformat()
            if isinstance(record["score"], Decimal):
                record["score"] = float(record["score"])
            records.append(record)
        return records
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_high_score_opportunities_internal_error")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "detail": "High score opportunities lookup failed",
            },
        )


@app.get(
    "/analytics/daily-opportunities",
    summary="Opportunity counts grouped by calendar day (UTC)",
    description=(
        "Return per-day counts of persisted opportunities, including "
        "ALERT_ELIGIBLE and NO_ALERT sub-counts, grouped by the UTC "
        "calendar day of opportunity_timestamp and ordered by day "
        "ascending. Supports an optional product_id filter. Returns an "
        "empty list when no matching rows exist."
    ),
)
def get_daily_opportunities(
    product_id: str | None = Query(
        None, description="Filter to opportunities for this product_id."
    ),
) -> list[dict]:
    try:
        sql = (
            "SELECT DATE(opportunity_timestamp AT TIME ZONE 'UTC') AS day, "
            "COUNT(*) AS opportunity_count, "
            "COUNT(*) FILTER (WHERE alert_decision = 'ALERT_ELIGIBLE') "
            "AS alert_eligible_count, "
            "COUNT(*) FILTER (WHERE alert_decision = 'NO_ALERT') "
            "AS no_alert_count "
            "FROM opportunities"
        )
        clauses: list[str] = []
        params: list[object] = []
        if product_id is not None:
            clauses.append("product_id = %s")
            params.append(product_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " GROUP BY day ORDER BY day ASC"

        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
        finally:
            connection.close()

        records: list[dict] = []
        for day, opportunity_count, alert_eligible_count, no_alert_count in rows:
            records.append(
                {
                    "day": day.isoformat() if day is not None else None,
                    "opportunity_count": int(opportunity_count),
                    "alert_eligible_count": int(alert_eligible_count),
                    "no_alert_count": int(no_alert_count),
                }
            )
        return records
    except HTTPException:
        raise
    except Exception:
        logger.exception("get_daily_opportunities_internal_error")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "detail": "Daily opportunities lookup failed",
            },
        )


@app.post(
    "/run-pipeline",
    response_model=RunPipelineResponse,
    summary="Execute one pipeline run",
    description=(
        "Run the six-stage opportunity pipeline for a single product "
        "execution and return the classified result along with per-stage "
        "outputs and the audit record."
    ),
)
def run_pipeline(request: RunPipelineRequest) -> RunPipelineResponse:
    pipeline_input = request.model_dump()

    def validator_factory(inp: dict) -> InputValidator:
        ref_ts = inp["freshness_reference_timestamp"]
        return InputValidator(
            ValidationContext(
                pipeline_execution_id=inp["pipeline_execution_id"],
                freshness_reference_timestamp=ref_ts,
                freshness_window_seconds=FRESHNESS_WINDOW_SECONDS,
                allowed_sources=ALLOWED_SOURCES,
                validated_at=ref_ts,
            )
        )

    try:
        connection = connect()
        try:
            runner = PipelineRunner(
                input_validator_factory=validator_factory,
                postgres_writer=PostgresWriter(connection),
            )
            result = runner.run(pipeline_input)
        finally:
            connection.close()
        return RunPipelineResponse.model_validate(asdict(result))
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_request", "detail": str(exc)},
        )
    except Exception:
        logger.exception("run_pipeline_internal_error")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "detail": "Pipeline execution failed",
            },
        )


@app.get(
    "/all-deals",
    summary="Live cross-source deal browser",
    description=(
        "Fetches every current listing from all connectors and returns "
        "them flat, optionally filtered by a search query against the "
        "title. Use this to browse deals like a multi-source aggregator."
    ),
)
def list_all_deals(
    q: str | None = Query(None, description="Case-insensitive substring match on title"),
    max_results: int = Query(200, ge=1, le=1000),
) -> list[dict]:
    # Local imports so unit tests don't need feedparser/httpx.
    from aace_execution.connectors.bensbargains import BensBargainsConnector
    from aace_execution.connectors.dealnews import DealNewsConnector
    from aace_execution.connectors.slickdeals import SlickdealsConnector
    from aace_execution.connectors.techbargains import TechBargainsConnector

    needle = q.lower().strip() if q else None
    deals: list[dict] = []

    for connector_cls in (
        SlickdealsConnector,
        DealNewsConnector,
        BensBargainsConnector,
        TechBargainsConnector,
    ):
        try:
            for listing in connector_cls().run():
                title = listing.title or ""
                if needle and needle not in title.lower():
                    continue
                deals.append({
                    "source": listing.source,
                    "title": title,
                    "price": float(listing.price),
                    "currency": listing.currency,
                    "url": listing.url,
                })
        except Exception as exc:
            logger.warning(
                "all_deals_connector_failed",
                extra={"connector": connector_cls.__name__, "error": str(exc)},
            )

    deals.sort(key=lambda d: d["price"])
    return deals[:max_results]


_WORKER_OPPORTUNITY_COLUMNS = (
    "opportunity_id",
    "product_key",
    "sources",
    "source_count",
    "min_price",
    "max_price",
    "absolute_spread",
    "percent_spread",
    "score",
    "delivery_status",
    "detected_at",
)


# Process-wide resale-comps client. Routed: Amazon -> Keepa (real if
# KEEPA_API_KEY is set; mock otherwise), other platforms -> SerpAPI
# (real if SERPAPI_KEY is set; mock otherwise). The router falls back
# to the mock cleanly if either client fails or isn't configured —
# so missing or revoked keys never break the dashboard.
# (KeepaClient / RoutedResaleCompsClient / SerpApiClient imported at the
# top of the file to satisfy ruff E402; this section just wires them up.)


def _build_resale_comps_client() -> RoutedResaleCompsClient:
    """Build the process-wide resale-comps router from env config.

    Cred-free / dev environment: returns a router with mock fallback
    only (matches yesterday's Sprint 2 scaffolding behaviour).
    """
    keepa = None
    keepa_key = os.environ.get("KEEPA_API_KEY")
    if keepa_key:
        try:
            keepa = KeepaClient(api_key=keepa_key)
            logger.info("keepa_client_enabled")
        except Exception:  # noqa: BLE001
            logger.exception("keepa_client_init_failed")
            keepa = None

    serpapi = None
    serpapi_key = os.environ.get("SERPAPI_KEY")
    if serpapi_key:
        try:
            serpapi = SerpApiClient(api_key=serpapi_key)
            logger.info("serpapi_client_enabled")
        except Exception:  # noqa: BLE001
            logger.exception("serpapi_client_init_failed")
            serpapi = None

    return RoutedResaleCompsClient(keepa=keepa, serpapi=serpapi)


_RESALE_COMPS_CLIENT = _build_resale_comps_client()


@app.get(
    "/worker-opportunities",
    summary="Live worker opportunities (v0.1.0 worker output)",
    description=(
        "List the most recent opportunities the scheduled worker scored "
        "and shipped to the AI agent. Newest first. When ``platform`` is "
        "supplied, each row is enriched with a resale-comp lookup "
        "(``resale_avg``, ``resale_source``, ``resale_confidence``) for "
        "that resale platform."
    ),
)
def list_worker_opportunities(
    limit: int = Query(50, ge=1, le=500),
    min_score: float | None = Query(None),
    platform: str | None = Query(
        None,
        description=(
            "Resale platform to compute comps for (e.g. 'Amazon', 'eBay'). "
            "When omitted, comp fields are not populated."
        ),
    ),
) -> list[dict]:
    try:
        sql = (
            "SELECT opportunity_id, product_key, sources, source_count, "
            "min_price, max_price, absolute_spread, percent_spread, "
            "score, delivery_status, detected_at "
            "FROM worker_opportunities"
        )
        params: list[object] = []
        if min_score is not None:
            sql += " WHERE score >= %s"
            params.append(min_score)
        sql += " ORDER BY detected_at DESC LIMIT %s"
        params.append(limit)

        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
        finally:
            connection.close()

        records: list[dict] = []
        for row in rows:
            record = dict(zip(_WORKER_OPPORTUNITY_COLUMNS, row))
            for field in (
                "min_price",
                "max_price",
                "absolute_spread",
                "percent_spread",
                "score",
            ):
                value = record.get(field)
                if isinstance(value, Decimal):
                    record[field] = float(value)
            if record["detected_at"] is not None:
                record["detected_at"] = record["detected_at"].isoformat()

            # Resale comp enrichment — only when caller asked for one.
            # Errors here MUST NOT break the listing endpoint: we log and
            # leave the comp fields blank so the dashboard falls back to
            # the legacy max_price proxy.
            if platform:
                try:
                    comp = _RESALE_COMPS_CLIENT.lookup(
                        product_key=record["product_key"],
                        platform=platform,
                        price_hint=record.get("min_price"),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "resale_comps_lookup_failed",
                        extra={
                            "opportunity_id": record.get("opportunity_id"),
                            "platform": platform,
                        },
                    )
                    comp = None
                if comp is not None:
                    record["resale_avg"] = comp.sold_avg
                    record["resale_count"] = comp.sold_count
                    record["resale_source"] = comp.source
                    record["resale_confidence"] = comp.confidence
                else:
                    record["resale_avg"] = None
                    record["resale_count"] = None
                    record["resale_source"] = None
                    record["resale_confidence"] = None

            records.append(record)
        return records
    except HTTPException:
        raise
    except Exception:
        logger.exception("list_worker_opportunities_internal_error")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "detail": "Worker opportunities lookup failed",
            },
        )


@app.get(
    "/docs/usage",
    summary="API usage documentation",
    description=(
        "Return a structured JSON description of the AACE API: overview, "
        "authentication, and per-endpoint purpose with example requests and "
        "responses."
    ),
)
def get_usage_docs() -> dict:
    return {
        "overview": (
            "The AACE (Autonomous Arbitrage Commerce Engine) API exposes the "
            "opportunity-detection pipeline and analytics over arbitrage "
            "opportunities. Clients can execute pipeline runs, read back "
            "persisted pipeline results, opportunities, and alert decisions, "
            "and query aggregate analytics for dashboards."
        ),
        "authentication": {
            "scheme": "API key",
            "header": "X-API-Key",
            "note": "All endpoints require X-API-Key header except /health",
        },
        "endpoints": [
            {
                "method": "POST",
                "path": "/run-pipeline",
                "purpose": "Execute one end-to-end pipeline run for a product and persist the result.",
                "example_request": (
                    "curl -X POST http://localhost:8000/run-pipeline "
                    "-H 'X-API-Key: $AACE_API_KEY' "
                    "-H 'Content-Type: application/json' "
                    "-d '{\"pipeline_execution_id\": \"exec-123\", \"product_id\": \"prod-1\", "
                    "\"freshness_reference_timestamp\": \"2026-04-26T12:00:00Z\"}'"
                ),
                "example_response": {
                    "pipeline_execution_id": "exec-123",
                    "product_id": "prod-1",
                    "result_classification": "OPPORTUNITY_DETECTED",
                    "stage_reached": "alert_decision",
                },
            },
            {
                "method": "GET",
                "path": "/pipeline-results/{pipeline_execution_id}",
                "purpose": "Fetch the persisted pipeline result for a given execution id.",
                "example_request": (
                    "curl http://localhost:8000/pipeline-results/exec-123 "
                    "-H 'X-API-Key: $AACE_API_KEY'"
                ),
                "example_response": {
                    "pipeline_execution_id": "exec-123",
                    "product_id": "prod-1",
                    "result_classification": "OPPORTUNITY_DETECTED",
                    "stage_reached": "alert_decision",
                    "result_timestamp": "2026-04-26T12:00:05+00:00",
                },
            },
            {
                "method": "GET",
                "path": "/opportunities",
                "purpose": "List persisted opportunities, optionally filtered by product or classification.",
                "example_request": (
                    "curl 'http://localhost:8000/opportunities?product_id=prod-1' "
                    "-H 'X-API-Key: $AACE_API_KEY'"
                ),
                "example_response": [
                    {
                        "pipeline_execution_id": "exec-123",
                        "product_id": "prod-1",
                        "score": 87.5,
                        "alert_decision": "ALERT_ELIGIBLE",
                        "opportunity_timestamp": "2026-04-26T12:00:05+00:00",
                    }
                ],
            },
            {
                "method": "GET",
                "path": "/alert-decisions",
                "purpose": "List persisted alert decisions, optionally filtered by execution, product, or result.",
                "example_request": (
                    "curl 'http://localhost:8000/alert-decisions?decision_result=ALERT_ELIGIBLE' "
                    "-H 'X-API-Key: $AACE_API_KEY'"
                ),
                "example_response": [
                    {
                        "pipeline_execution_id": "exec-123",
                        "product_id": "prod-1",
                        "score": 87.5,
                        "alert_threshold": 80.0,
                        "decision_result": "ALERT_ELIGIBLE",
                        "decision_reference_timestamp": "2026-04-26T12:00:05+00:00",
                    }
                ],
            },
            {
                "method": "GET",
                "path": "/analytics/opportunity-summary",
                "purpose": "Aggregate counts of opportunities and the average score.",
                "example_request": (
                    "curl http://localhost:8000/analytics/opportunity-summary "
                    "-H 'X-API-Key: $AACE_API_KEY'"
                ),
                "example_response": {
                    "total_opportunities": 42,
                    "alert_eligible": 18,
                    "no_alert": 24,
                    "average_score": 71.34,
                },
            },
            {
                "method": "GET",
                "path": "/analytics/top-products",
                "purpose": "Top 10 products ranked by opportunity count.",
                "example_request": (
                    "curl http://localhost:8000/analytics/top-products "
                    "-H 'X-API-Key: $AACE_API_KEY'"
                ),
                "example_response": [
                    {"product_id": "prod-1", "opportunity_count": 12},
                    {"product_id": "prod-2", "opportunity_count": 9},
                ],
            },
            {
                "method": "GET",
                "path": "/analytics/alert-rate",
                "purpose": "Counts and percentage of ALERT_ELIGIBLE versus NO_ALERT opportunities.",
                "example_request": (
                    "curl http://localhost:8000/analytics/alert-rate "
                    "-H 'X-API-Key: $AACE_API_KEY'"
                ),
                "example_response": {
                    "total_opportunities": 42,
                    "alert_eligible": 18,
                    "no_alert": 24,
                    "alert_rate_percent": 42.86,
                    "no_alert_rate_percent": 57.14,
                },
            },
            {
                "method": "GET",
                "path": "/analytics/high-score-opportunities",
                "purpose": "Top 10 opportunities by score, with optional min_score and product_id filters.",
                "example_request": (
                    "curl 'http://localhost:8000/analytics/high-score-opportunities?min_score=80' "
                    "-H 'X-API-Key: $AACE_API_KEY'"
                ),
                "example_response": [
                    {
                        "product_id": "prod-1",
                        "score": 92.1,
                        "alert_decision": "ALERT_ELIGIBLE",
                        "result_classification": "OPPORTUNITY_DETECTED",
                        "opportunity_timestamp": "2026-04-26T12:00:05+00:00",
                    }
                ],
            },
            {
                "method": "GET",
                "path": "/analytics/daily-opportunities",
                "purpose": "Per-day opportunity counts (UTC) with ALERT_ELIGIBLE and NO_ALERT breakdowns.",
                "example_request": (
                    "curl http://localhost:8000/analytics/daily-opportunities "
                    "-H 'X-API-Key: $AACE_API_KEY'"
                ),
                "example_response": [
                    {
                        "day": "2026-04-25",
                        "opportunity_count": 20,
                        "alert_eligible_count": 8,
                        "no_alert_count": 12,
                    },
                    {
                        "day": "2026-04-26",
                        "opportunity_count": 22,
                        "alert_eligible_count": 10,
                        "no_alert_count": 12,
                    },
                ],
            },
        ],
    }
