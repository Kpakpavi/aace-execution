"""Failure classification for persistence write operations.

Classifies psycopg exceptions into transient vs. terminal failures and produces
WriteFailure instances that the writer methods return. Contains no retry logic
and makes no database calls.

Contracts implemented:
- PERSISTENCE_WRITER_CONTRACT.md Section 10.3 (transient vs. terminal)
- POSTGRES_WRITER_IMPLEMENTATION_PLAN.md Section 5.4, Section 10.1
"""

from __future__ import annotations

from aace_execution.persistence.results import FailureKind, WriteFailure

# ---------------------------------------------------------------------------
# PostgreSQL sqlstate codes used for classification.
# These are the specific codes referenced in the implementation plan Section 10.1.
# ---------------------------------------------------------------------------

SQLSTATE_UNIQUE_VIOLATION = "23505"
SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"
SQLSTATE_CHECK_VIOLATION = "23514"
SQLSTATE_NOT_NULL_VIOLATION = "23502"

# Constraint-class sqlstates (23xxx) are terminal — they indicate logic errors,
# schema mismatches, or invalid data. They must not be retried.
_TERMINAL_SQLSTATE_PREFIXES = ("23",)


def classify_exception(exc: BaseException, table: str, method: str) -> WriteFailure:
    """Classify a psycopg exception as a transient or terminal WriteFailure.

    This function inspects the exception type and, where available, the PostgreSQL
    sqlstate code to determine whether the failure is transient (infrastructure issue,
    retriable by the caller) or terminal (logic error, must not be retried).

    Args:
        exc: The exception raised during a write operation. Expected to be a
            psycopg exception, but handles arbitrary exceptions defensively.
        table: The target table name (e.g., "pipeline_results") for diagnostic context.
        method: The writer method name (e.g., "persist_pipeline_result") for diagnostic
            context.

    Returns:
        A WriteFailure with the appropriate kind, a human-readable reason, and the
        sqlstate code if available.
    """
    sqlstate = _extract_sqlstate(exc)
    kind = _classify_kind(exc, sqlstate)
    reason = _format_reason(exc, table, method, sqlstate)
    return WriteFailure(kind=kind, reason=reason, sqlstate=sqlstate)


def is_unique_violation(exc: BaseException) -> bool:
    """Check whether an exception is a PostgreSQL unique constraint violation.

    Used by writer methods to distinguish idempotency signals (expected duplicate)
    from unexpected terminal errors. When persist_pipeline_result catches a unique
    violation during the expected duplicate-detection flow, it treats it as
    ALREADY_EXISTS rather than FAILED.

    Args:
        exc: The exception to check.

    Returns:
        True if the exception has sqlstate 23505 (unique_violation).
    """
    return _extract_sqlstate(exc) == SQLSTATE_UNIQUE_VIOLATION


def _extract_sqlstate(exc: BaseException) -> str | None:
    """Extract the PostgreSQL sqlstate code from an exception, if present.

    psycopg DatabaseError subclasses expose the sqlstate as the `sqlstate` attribute.
    Other exception types (InterfaceError, generic Exception) do not have a sqlstate.
    """
    sqlstate = getattr(exc, "sqlstate", None)
    if isinstance(sqlstate, str) and len(sqlstate) == 5:
        return sqlstate
    return None


def _classify_kind(exc: BaseException, sqlstate: str | None) -> FailureKind:
    """Determine whether a failure is transient or terminal.

    Classification rules (from POSTGRES_WRITER_IMPLEMENTATION_PLAN.md Section 10.1):

    Terminal:
    - UniqueViolation (23505) — unexpected duplicate, indicates logic error.
    - ForeignKeyViolation (23503) — write-order bug or missing parent row.
    - CheckViolation (23514) — invalid data passed to the writer.
    - NotNullViolation (23502) — missing required field.
    - Any constraint violation (sqlstate class 23).

    Transient:
    - OperationalError — connection timeout, temporary unavailability.
    - InterfaceError — connection lost.
    - Any exception without a constraint-class sqlstate.
    """
    if sqlstate is not None:
        for prefix in _TERMINAL_SQLSTATE_PREFIXES:
            if sqlstate.startswith(prefix):
                return FailureKind.TERMINAL
        return FailureKind.TRANSIENT

    # psycopg InterfaceError has no sqlstate — it indicates connection-level failure.
    # OperationalError subclasses without a sqlstate are also transient.
    # Unrecognized exceptions default to transient so the caller can decide whether
    # to retry, rather than silently treating an unknown failure as permanent.
    return FailureKind.TRANSIENT


def _format_reason(
    exc: BaseException,
    table: str,
    method: str,
    sqlstate: str | None,
) -> str:
    """Format a human-readable failure reason for diagnostic context.

    The reason string is used in WriteFailure.reason and may be written to the
    audit record's persistence_failure_detail field. It includes the method name,
    target table, exception class, message, and sqlstate if available.

    This is a plain text diagnostic string, not structured JSON.
    """
    exc_class = type(exc).__qualname__
    exc_message = str(exc).strip()

    parts = [
        f"{method} failed writing to {table}",
        f"exception={exc_class}",
    ]

    if sqlstate is not None:
        parts.append(f"sqlstate={sqlstate}")

    if exc_message:
        parts.append(f"detail={exc_message}")

    return "; ".join(parts)
