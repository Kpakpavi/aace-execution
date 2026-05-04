"""PostgreSQL persistence writer for AACE execution pipeline results.

Implements the five required methods from PERSISTENCE_WRITER_CONTRACT.md using
psycopg and raw SQL. Connection is injected via constructor. No pooling, no
retry logic, no ORM, no business logic.

Contracts implemented:
- PERSISTENCE_WRITER_CONTRACT.md (all sections)
- POSTGRES_WRITER_IMPLEMENTATION_PLAN.md (all sections)
- POSTGRES_PERSISTENCE_SCHEMA.md (structural compatibility)
"""

from __future__ import annotations

from typing import Any

import psycopg

from aace_execution.persistence.errors import classify_exception, is_unique_violation
from aace_execution.persistence.results import (
    ExecutionOutcome,
    ExecutionStatus,
    WriteResult,
    WriteStatus,
)
from aace_execution.persistence.sql import (
    INSERT_ALERT_DECISION,
    INSERT_AUDIT_RECORD,
    INSERT_OPPORTUNITY,
    INSERT_PIPELINE_RESULT,
    SELECT_EXISTING_PIPELINE_RESULT,
    UPDATE_PIPELINE_RESULT_FROM_FAILURE,
)

# Result classifications that produce opportunity records.
_OPPORTUNITY_CLASSIFICATIONS = frozenset({
    "OPPORTUNITY_DETECTED",
    "OPPORTUNITY_SCORED_NO_ALERT",
})

# Result classifications considered finalized (not overwritable).
_FINALIZED_CLASSIFICATIONS = frozenset({
    "OPPORTUNITY_DETECTED",
    "OPPORTUNITY_SCORED_NO_ALERT",
    "NO_OPPORTUNITY",
    "NO_OP",
})


class PostgresWriter:
    """Persistence writer targeting PostgreSQL via psycopg.

    Accepts an open psycopg.Connection. Does not create, manage, or close
    the connection. Stateless between calls.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._conn = connection

    def persist_pipeline_result(self, params: dict[str, Any]) -> WriteResult:
        """Write or update a pipeline result record.

        Implements PERSISTENCE_WRITER_CONTRACT.md Section 7.1:
        - No existing row: INSERT, return WRITTEN.
        - Existing PROCESSING_FAILURE row: UPDATE, return UPDATED.
          If UPDATE rowcount is 0 (race condition), return ALREADY_EXISTS.
        - Existing finalized row: return ALREADY_EXISTS, no write.
        - Any exception: return FAILED with classified failure.
        """
        table = "pipeline_results"
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    SELECT_EXISTING_PIPELINE_RESULT,
                    {"pipeline_execution_id": params["pipeline_execution_id"]},
                )
                row = cur.fetchone()

                if row is None:
                    # No existing row — insert.
                    try:
                        cur.execute(INSERT_PIPELINE_RESULT, params)
                        return WriteResult(status=WriteStatus.WRITTEN, table=table)
                    except Exception as insert_exc:
                        if is_unique_violation(insert_exc):
                            # Race: another process inserted between SELECT and INSERT.
                            return WriteResult(
                                status=WriteStatus.ALREADY_EXISTS, table=table
                            )
                        raise

                existing_classification = row[0]

                if existing_classification in _FINALIZED_CLASSIFICATIONS:
                    return WriteResult(
                        status=WriteStatus.ALREADY_EXISTS, table=table
                    )

                if existing_classification == "PROCESSING_FAILURE":
                    cur.execute(UPDATE_PIPELINE_RESULT_FROM_FAILURE, params)
                    if cur.rowcount == 1:
                        return WriteResult(status=WriteStatus.UPDATED, table=table)
                    # rowcount 0: another process finalized between SELECT and UPDATE.
                    return WriteResult(
                        status=WriteStatus.ALREADY_EXISTS, table=table
                    )

                # Unexpected classification — treat as already exists (finalized).
                return WriteResult(
                    status=WriteStatus.ALREADY_EXISTS, table=table
                )

        except Exception as exc:
            failure = classify_exception(exc, table, "persist_pipeline_result")
            return WriteResult(
                status=WriteStatus.FAILED, table=table, failure=failure
            )

    def persist_opportunity(self, params: dict[str, Any]) -> WriteResult:
        """Write an opportunity record.

        Implements PERSISTENCE_WRITER_CONTRACT.md Section 7.2:
        - INSERT with ON CONFLICT DO NOTHING.
        - rowcount 1: WRITTEN. rowcount 0: ALREADY_EXISTS.
        - Any exception: FAILED with classified failure.
        """
        table = "opportunities"
        try:
            with self._conn.cursor() as cur:
                cur.execute(INSERT_OPPORTUNITY, params)
                if cur.rowcount == 1:
                    return WriteResult(status=WriteStatus.WRITTEN, table=table)
                return WriteResult(
                    status=WriteStatus.ALREADY_EXISTS, table=table
                )
        except Exception as exc:
            failure = classify_exception(exc, table, "persist_opportunity")
            return WriteResult(
                status=WriteStatus.FAILED, table=table, failure=failure
            )

    def persist_alert_decision(self, params: dict[str, Any]) -> WriteResult:
        """Write an alert decision record.

        Implements PERSISTENCE_WRITER_CONTRACT.md Section 7.3:
        - INSERT with ON CONFLICT DO NOTHING on composite key.
        - rowcount 1: WRITTEN. rowcount 0: ALREADY_EXISTS.
        - Any exception: FAILED with classified failure.
        """
        table = "alert_decisions"
        try:
            with self._conn.cursor() as cur:
                cur.execute(INSERT_ALERT_DECISION, params)
                if cur.rowcount == 1:
                    return WriteResult(status=WriteStatus.WRITTEN, table=table)
                return WriteResult(
                    status=WriteStatus.ALREADY_EXISTS, table=table
                )
        except Exception as exc:
            failure = classify_exception(exc, table, "persist_alert_decision")
            return WriteResult(
                status=WriteStatus.FAILED, table=table, failure=failure
            )

    def persist_audit_record(self, params: dict[str, Any]) -> WriteResult:
        """Write an audit record. Always inserts a new row.

        Implements PERSISTENCE_WRITER_CONTRACT.md Section 7.4:
        - Always INSERT (append-only, no deduplication).
        - audit_written_at is set via now() in SQL.
        - Any exception: FAILED with classified failure.
        """
        table = "audit_records"
        try:
            with self._conn.cursor() as cur:
                cur.execute(INSERT_AUDIT_RECORD, params)
                return WriteResult(status=WriteStatus.WRITTEN, table=table)
        except Exception as exc:
            failure = classify_exception(exc, table, "persist_audit_record")
            return WriteResult(
                status=WriteStatus.FAILED, table=table, failure=failure
            )

    def persist_execution(
        self,
        pipeline_result_params: dict[str, Any],
        opportunity_params: dict[str, Any] | None,
        alert_decision_params: dict[str, Any] | None,
        audit_record_params: dict[str, Any],
    ) -> ExecutionOutcome:
        """Orchestrate all writes for a single pipeline execution.

        Implements PERSISTENCE_WRITER_CONTRACT.md Section 7.5 and Section 8:
        1. persist_pipeline_result — always first.
        2. persist_opportunity — if applicable.
        3. persist_alert_decision — if applicable.
        4. persist_audit_record — always last.

        On non-audit failure: rollback, write audit in a new transaction.
        On ALREADY_EXISTS for pipeline result: skip dependent writes.
        """
        pipeline_execution_id = pipeline_result_params["pipeline_execution_id"]

        opportunity_write: WriteResult | None = None
        alert_decision_write: WriteResult | None = None
        audit_record_write: WriteResult | None = None
        non_audit_failed = False
        persistence_outcome: str
        persistence_failure_detail: str | None = None

        # --- Step 1: persist_pipeline_result (always first) ---
        pipeline_result_write = self.persist_pipeline_result(pipeline_result_params)

        if pipeline_result_write.status == WriteStatus.FAILED:
            # Pipeline result write failed — skip dependent writes.
            non_audit_failed = True
            persistence_outcome = "RESULT_WRITE_FAILED"
            persistence_failure_detail = (
                pipeline_result_write.failure.reason
                if pipeline_result_write.failure
                else "persist_pipeline_result failed"
            )
            # Rollback and write audit in a new transaction.
            self._conn.rollback()

        elif pipeline_result_write.status == WriteStatus.ALREADY_EXISTS:
            # Finalized row exists — skip dependent writes per Section 9.4.
            persistence_outcome = "ALL_WRITES_SUCCEEDED"

        else:
            # WRITTEN or UPDATED — proceed with dependent writes.
            failure_details: list[str] = []

            # --- Step 2: persist_opportunity (if applicable) ---
            if opportunity_params is not None:
                opportunity_write = self.persist_opportunity(opportunity_params)
                if opportunity_write.status == WriteStatus.FAILED:
                    non_audit_failed = True
                    failure_details.append(
                        opportunity_write.failure.reason
                        if opportunity_write.failure
                        else "persist_opportunity failed"
                    )

            # --- Step 3: persist_alert_decision (if applicable) ---
            if alert_decision_params is not None:
                alert_decision_write = self.persist_alert_decision(
                    alert_decision_params
                )
                if alert_decision_write.status == WriteStatus.FAILED:
                    non_audit_failed = True
                    failure_details.append(
                        alert_decision_write.failure.reason
                        if alert_decision_write.failure
                        else "persist_alert_decision failed"
                    )

            if non_audit_failed:
                persistence_outcome = "PARTIAL_WRITE_FAILURE"
                persistence_failure_detail = "; ".join(failure_details)
                # Rollback the partial transaction.
                self._conn.rollback()
            else:
                persistence_outcome = "ALL_WRITES_SUCCEEDED"

        # --- Step 4: persist_audit_record (always last) ---
        audit_record_params = dict(audit_record_params)
        audit_record_params["persistence_outcome"] = persistence_outcome
        audit_record_params["persistence_failure_detail"] = persistence_failure_detail

        audit_record_write = self.persist_audit_record(audit_record_params)

        if audit_record_write.status == WriteStatus.FAILED:
            # Audit write failed — determine overall status.
            if non_audit_failed:
                status = ExecutionStatus.TOTAL_FAILURE
            else:
                status = ExecutionStatus.AUDIT_WRITE_FAILED
            self._conn.rollback()
        else:
            # Audit write succeeded — commit.
            self._conn.commit()
            if non_audit_failed:
                if pipeline_result_write.status == WriteStatus.FAILED:
                    status = ExecutionStatus.RESULT_WRITE_FAILED
                else:
                    status = ExecutionStatus.PARTIAL_WRITE_FAILURE
            else:
                status = ExecutionStatus.ALL_WRITES_SUCCEEDED

        return ExecutionOutcome(
            status=status,
            pipeline_execution_id=pipeline_execution_id,
            pipeline_result_write=pipeline_result_write,
            opportunity_write=opportunity_write,
            alert_decision_write=alert_decision_write,
            audit_record_write=audit_record_write,
        )
