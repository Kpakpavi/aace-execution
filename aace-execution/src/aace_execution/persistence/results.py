"""Structured return types for persistence writer methods.

Defines the result types used by individual write methods (WriteResult) and the
top-level persist_execution method (ExecutionOutcome). These are plain data classes
with no behavior — they carry outcome data only.

Contracts implemented:
- PERSISTENCE_WRITER_CONTRACT.md Section 7 (method output contracts)
- POSTGRES_WRITER_IMPLEMENTATION_PLAN.md Section 5.3
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WriteStatus(Enum):
    """Outcome of an individual write method.

    WRITTEN: A new row was inserted.
    UPDATED: An existing PROCESSING_FAILURE row was updated with a new result.
    ALREADY_EXISTS: A finalized row already exists. No write occurred.
    FAILED: The write failed. See WriteResult.failure for details.
    """

    WRITTEN = "WRITTEN"
    UPDATED = "UPDATED"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    FAILED = "FAILED"


class FailureKind(Enum):
    """Whether a write failure is transient or terminal.

    TRANSIENT: Connection timeout, temporary unavailability, lock contention.
               The caller may retry with bounded retry count.
    TERMINAL: Constraint violation indicating logic error, schema mismatch,
              data type violation. Must not be retried.
    """

    TRANSIENT = "TRANSIENT"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True)
class WriteFailure:
    """Details of a failed write operation.

    Attributes:
        kind: Whether the failure is transient or terminal.
        reason: Human-readable description of what failed.
        sqlstate: The PostgreSQL error code if available, None otherwise.
    """

    kind: FailureKind
    reason: str
    sqlstate: str | None


@dataclass(frozen=True)
class WriteResult:
    """Result of an individual write method (persist_pipeline_result, persist_opportunity,
    persist_alert_decision, persist_audit_record).

    Attributes:
        status: The outcome of the write attempt.
        table: The target table name.
        failure: Present only when status is FAILED. None otherwise.
    """

    status: WriteStatus
    table: str
    failure: WriteFailure | None = None


class ExecutionStatus(Enum):
    """Overall outcome of persist_execution.

    ALL_WRITES_SUCCEEDED: Every required record was written or confirmed as already
        existing. The pipeline execution is complete.
    PARTIAL_WRITE_FAILURE: The pipeline result was written, but one or more dependent
        records (opportunity or alert decision) failed. The audit record was written
        with the failure captured. The pipeline execution is incomplete.
    RESULT_WRITE_FAILED: The pipeline result record write failed. No dependent records
        were attempted. The audit record was written with the failure captured. The
        pipeline execution is incomplete.
    AUDIT_WRITE_FAILED: All non-audit writes succeeded (or were not required), but the
        audit record write failed. The pipeline execution is incomplete. Critical failure.
    TOTAL_FAILURE: Both the non-audit writes and the audit record write failed. The
        pipeline execution is incomplete. Critical failure.
    """

    ALL_WRITES_SUCCEEDED = "ALL_WRITES_SUCCEEDED"
    PARTIAL_WRITE_FAILURE = "PARTIAL_WRITE_FAILURE"
    RESULT_WRITE_FAILED = "RESULT_WRITE_FAILED"
    AUDIT_WRITE_FAILED = "AUDIT_WRITE_FAILED"
    TOTAL_FAILURE = "TOTAL_FAILURE"


@dataclass(frozen=True)
class ExecutionOutcome:
    """Result of persist_execution — the top-level orchestration method.

    Attributes:
        status: The overall outcome of all persistence writes.
        pipeline_execution_id: The pipeline execution this outcome describes.
        pipeline_result_write: Result of persist_pipeline_result. Always present.
        opportunity_write: Result of persist_opportunity. None if not applicable
            to this result classification or if skipped due to prior failure.
        alert_decision_write: Result of persist_alert_decision. None if not applicable
            to this execution or if skipped due to prior failure.
        audit_record_write: Result of persist_audit_record. None only if the audit
            write was not attempted (should not happen in correct operation).
    """

    status: ExecutionStatus
    pipeline_execution_id: str
    pipeline_result_write: WriteResult
    opportunity_write: WriteResult | None
    alert_decision_write: WriteResult | None
    audit_record_write: WriteResult | None
