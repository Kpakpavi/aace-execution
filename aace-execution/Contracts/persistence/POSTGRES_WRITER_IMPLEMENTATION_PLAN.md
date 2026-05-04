# PostgreSQL Writer Implementation Plan

## 1. Purpose

This document defines the implementation plan for the PostgreSQL persistence writer — the
concrete component that implements the `PERSISTENCE_WRITER_CONTRACT.md` interface using
`psycopg` (the modern Python PostgreSQL driver) and raw SQL.

It specifies:

- the driver and access pattern chosen,
- why raw SQL is used instead of an ORM,
- the module structure and file layout,
- how connections, transactions, and failures are managed,
- how each writer method maps to SQL operations against the schema,
- how idempotency, audit writes, and determinism are achieved at the implementation level.

This is a plan document, not an implementation.
It does not contain production code.
It defines the decisions and structure that the implementation must follow.

---

## 2. Relationship to Writer Contract and PostgreSQL Schema Contract

This plan implements the interface defined in `PERSISTENCE_WRITER_CONTRACT.md` and targets
the tables defined in `POSTGRES_PERSISTENCE_SCHEMA.md`.

```
PERSISTENCE_WRITER_CONTRACT.md
  Defines: the five required methods, their input/output contracts, write order,
  idempotency responsibilities, and failure handling rules.

POSTGRES_PERSISTENCE_SCHEMA.md
  Defines: the four tables, their columns, types, constraints, and structural rules.

POSTGRES_WRITER_IMPLEMENTATION_PLAN.md (this document)
  Defines: how psycopg and raw SQL are used to implement the writer contract
  against the PostgreSQL schema.
```

This plan must not contradict the writer contract or the schema contract. Every method,
behavior, and constraint in this plan must be traceable to a requirement in one of those
two documents. Where the contracts are silent on implementation details (driver choice,
SQL patterns, module layout), this plan makes those decisions.

---

## 3. Driver Choice

**Chosen driver**: `psycopg` (version 3.x) — the modern, PEP 249-compliant PostgreSQL
adapter for Python.

**Why psycopg**:

- It is the current-generation PostgreSQL driver for Python, replacing `psycopg2`.
- It provides native support for parameterized queries with server-side binding, which
  prevents SQL injection without requiring an ORM or query builder.
- It supports explicit transaction management via connection context managers and
  `connection.transaction()` blocks, which maps directly to the writer contract's transaction
  requirements.
- It handles `JSONB` natively via Python `dict` and `list` types without manual serialization.
- It handles `NUMERIC` via Python `Decimal` without lossy float conversion.
- It handles `TIMESTAMPTZ` via Python `datetime` with timezone awareness.
- It provides typed exception hierarchy (`psycopg.errors`) that allows distinguishing
  unique constraint violations from connection errors, which is required for the writer's
  transient vs. terminal failure classification.

**Dependency**: `psycopg[binary]` will be added to `pyproject.toml` dependencies. The
`[binary]` extra includes the pre-built C-based `libpq` binding for local development.

**What is not chosen yet**: Connection pooling. The initial implementation uses a single
connection per writer instance. Connection pooling (e.g., `psycopg_pool.ConnectionPool`)
is a future optimization.

---

## 4. Why Raw SQL

**Chosen access pattern**: Raw parameterized SQL statements executed via `psycopg`.

**Why not an ORM**:

- The writer contract explicitly forbids computed or derived fields. The writer extracts
  field values from the assembled result and writes them as-is. An ORM's model layer,
  default values, lifecycle hooks, and automatic serialization add opportunities for
  unintended transformation that would violate determinism.
- The schema has exactly four tables with fixed, known columns. There is no polymorphism,
  inheritance, or dynamic schema. The mapping from Python values to SQL columns is direct
  and static. An ORM provides no structural benefit here.
- The idempotency logic (check existing row, decide between insert/update/skip) requires
  conditional SQL patterns (`INSERT ... ON CONFLICT`, `SELECT` before `UPDATE`). These are
  more transparent and auditable as explicit SQL than as ORM-managed upsert abstractions.
- The writer contract requires that every write failure be classified as transient or
  terminal based on the PostgreSQL error. Raw `psycopg` exceptions expose the `sqlstate`
  code directly. ORM exception wrappers obscure this.
- The audit record must be written in a separate transaction on failure paths. Explicit
  transaction management via `psycopg` connection context managers is simpler and more
  predictable than ORM session/unit-of-work patterns for this specific requirement.

**What raw SQL means in practice**:

- Each writer method contains a SQL string with `%s` or `%(name)s` placeholders.
- Parameters are passed as tuples or dicts to `cursor.execute()`.
- `psycopg` handles parameter binding, type adaptation, and escaping.
- No string interpolation or concatenation is used in SQL construction.

---

## 5. Writer Module Structure

The implementation lives in `src/aace_execution/persistence/`. The module structure is:

```
src/aace_execution/persistence/
├── __init__.py
├── writer.py          # PostgresWriter class implementing the five contract methods
├── sql.py             # All SQL statements as named constants
├── results.py         # WriteResult, ExecutionOutcome, and related types
└── errors.py          # Failure classification: transient vs. terminal
```

### 5.1 `writer.py`

Contains the `PostgresWriter` class with:

- `__init__(self, connection)` — accepts a `psycopg.Connection` instance. Does not create
  or manage the connection lifecycle.
- `persist_pipeline_result(self, ...)` — implements Section 7.1 of the writer contract.
- `persist_opportunity(self, ...)` — implements Section 7.2 of the writer contract.
- `persist_alert_decision(self, ...)` — implements Section 7.3 of the writer contract.
- `persist_audit_record(self, ...)` — implements Section 7.4 of the writer contract.
- `persist_execution(self, ...)` — implements Section 7.5 of the writer contract.

The class is stateless between calls. It holds a connection reference but no execution state.

### 5.2 `sql.py`

Contains all SQL statements as module-level string constants. Each constant is named for
its purpose:

- `INSERT_PIPELINE_RESULT`
- `SELECT_EXISTING_PIPELINE_RESULT`
- `UPDATE_PIPELINE_RESULT_FROM_FAILURE`
- `INSERT_OPPORTUNITY`
- `INSERT_ALERT_DECISION`
- `INSERT_AUDIT_RECORD`

No SQL is constructed dynamically. Every statement is a static string with parameter
placeholders. This makes the SQL auditable — every query the writer can execute is visible
in one file.

### 5.3 `results.py`

Contains the structured return types used by writer methods:

- `WriteResult` — returned by individual write methods. Contains the outcome
  (`WRITTEN`, `UPDATED`, `ALREADY_EXISTS`, `FAILED`) and, for `FAILED`, the failure
  reason and whether it is transient or terminal.
- `ExecutionOutcome` — returned by `persist_execution`. Contains the overall outcome
  (`ALL_WRITES_SUCCEEDED`, `PARTIAL_WRITE_FAILURE`, `RESULT_WRITE_FAILED`,
  `AUDIT_WRITE_FAILED`, `TOTAL_FAILURE`), the individual `WriteResult` for each
  attempted write, and the `pipeline_execution_id`.

These types are plain data classes or named tuples. They carry no behavior.

### 5.4 `errors.py`

Contains the logic for classifying `psycopg` exceptions as transient or terminal:

- `UniqueViolation` (`sqlstate 23505`) — terminal when it indicates a logic error (e.g.,
  inserting an opportunity for an already-finalized execution). Used as an idempotency
  signal when detected during the expected duplicate-detection flow.
- `ForeignKeyViolation` (`sqlstate 23503`) — terminal. Indicates a write-order violation.
- `CheckViolation` (`sqlstate 23514`) — terminal. Indicates invalid data.
- `OperationalError`, `ConnectionTimeout`, `InterfaceError` — transient. Connection or
  infrastructure issues.

The classification function takes a `psycopg` exception and returns a structured failure
with the transient/terminal flag and a human-readable reason.

---

## 6. Connection Management Plan

### 6.1 Connection Ownership

The `PostgresWriter` does not create, open, or close database connections. It receives
an open `psycopg.Connection` via its constructor.

Connection lifecycle management is the caller's responsibility. This separation exists
because:

- The writer contract states that the writer does not choose a connection pool or
  transaction management strategy.
- In tests, the caller provides a test connection that can be rolled back after each test.
- In production, the caller provides a connection from whatever pool or factory is configured.

### 6.2 Connection Requirements

The connection provided to the writer must:

- Be an open `psycopg.Connection` connected to a PostgreSQL database with the schema
  defined in `POSTGRES_PERSISTENCE_SCHEMA.md`.
- Have `autocommit = False` (the psycopg default). The writer manages transactions
  explicitly.

### 6.3 No Connection Pooling Yet

The initial implementation does not use `psycopg_pool`. Each `PostgresWriter` instance
operates on a single connection. Connection pooling is a future optimization that can be
introduced at the caller level without changing the writer.

### 6.4 Connection for Audit Write on Failure Paths

When non-audit writes fail and the transaction is rolled back, the writer needs a usable
connection for the audit record write. Two approaches are viable:

- **Approach chosen**: The writer rolls back the failed transaction on the existing
  connection, then opens a new transaction on the same connection for the audit write.
  `psycopg` supports this — after `connection.rollback()`, the connection is reusable.

This avoids requiring a second connection or a connection factory for the failure path.

---

## 7. Transaction Strategy

### 7.1 Happy Path: Single Transaction

When all writes succeed, all non-audit writes and the audit write occur within a single
transaction:

1. Begin transaction (implicit with `autocommit=False`, or explicit via
   `connection.transaction()`).
2. Execute `INSERT` into `pipeline_results`.
3. Execute `INSERT` into `opportunities` (if applicable).
4. Execute `INSERT` into `alert_decisions` (if applicable).
5. Execute `INSERT` into `audit_records` with `persistence_outcome = 'ALL_WRITES_SUCCEEDED'`.
6. Commit.

Using a single transaction ensures that all records for one pipeline execution are either
fully committed or fully rolled back. No partial state is possible.

### 7.2 Failure Path: Rollback and Separate Audit Transaction

When a non-audit write fails:

1. Catch the exception from the failed write.
2. Roll back the current transaction (`connection.rollback()`).
3. Classify the failure as transient or terminal.
4. Begin a new transaction on the same connection.
5. Execute `INSERT` into `audit_records` with `persistence_outcome` set to
   `RESULT_WRITE_FAILED` or `PARTIAL_WRITE_FAILURE` and `persistence_failure_detail`
   describing the failure.
6. Commit the audit transaction.
7. Return the failure outcome to the caller.

If the audit write in step 5-6 also fails, return `TOTAL_FAILURE`.

### 7.3 Idempotent Duplicate Path

When `persist_pipeline_result` detects that a finalized row already exists:

1. The `SELECT` query runs within the current transaction.
2. No `INSERT` or `UPDATE` is attempted.
3. The method returns `ALREADY_EXISTS`.
4. `persist_execution` skips dependent writes.
5. The audit record is written with `persistence_outcome = 'ALL_WRITES_SUCCEEDED'`.
6. Commit.

No rollback is needed because no write was attempted.

### 7.4 No Savepoints

The initial implementation does not use savepoints. On any non-audit write failure, the
entire transaction is rolled back. Savepoints are a future optimization if partial commit
of earlier writes becomes needed.

---

## 8. Method-to-Table Mapping

### 8.1 `persist_pipeline_result` -> `pipeline_results`

**SQL flow**:

1. `SELECT result_classification FROM pipeline_results WHERE pipeline_execution_id = %(id)s`
   to check for an existing row.
2. If no row exists: `INSERT INTO pipeline_results (...) VALUES (...)`. Return `WRITTEN`.
3. If an existing row has `result_classification = 'PROCESSING_FAILURE'`:
   `UPDATE pipeline_results SET ... WHERE pipeline_execution_id = %(id)s AND result_classification = 'PROCESSING_FAILURE'`.
   Check `rowcount` to confirm the update occurred (guards against a race where another
   process finalized the row between the `SELECT` and `UPDATE`). Return `UPDATED` if
   `rowcount = 1`, or `ALREADY_EXISTS` if `rowcount = 0`.
4. If an existing row has a finalized classification: return `ALREADY_EXISTS`. No write.

**Columns written**: `pipeline_execution_id`, `product_id`, `result_classification`,
`stage_reached`, `result_timestamp`, `stage_outcome_summary`, `retry_eligible`,
`failure_stage`, `failure_reason`.

**Parameter types**: `TEXT` values as `str`, `TIMESTAMPTZ` as `datetime`, `JSONB` as `dict`,
`BOOLEAN` as `bool` or `None`.

### 8.2 `persist_opportunity` -> `opportunities`

**SQL flow**:

1. `INSERT INTO opportunities (...) VALUES (...) ON CONFLICT (pipeline_execution_id) DO NOTHING`.
2. Check `cursor.rowcount`: if `1`, return `WRITTEN`. If `0`, return `ALREADY_EXISTS`.

`ON CONFLICT DO NOTHING` is safe here because the writer contract states that an existing
opportunity row must not be modified. The primary key constraint handles deduplication
atomically without a separate `SELECT`.

**Columns written**: All 20 columns defined in `POSTGRES_PERSISTENCE_SCHEMA.md` Section 6.

**Parameter types**: `TEXT` as `str`, `NUMERIC` as `Decimal`, `TIMESTAMPTZ` as `datetime`,
`JSONB` as `dict` or `list`.

### 8.3 `persist_alert_decision` -> `alert_decisions`

**SQL flow**:

1. `INSERT INTO alert_decisions (...) VALUES (...) ON CONFLICT (pipeline_execution_id, notification_type) DO NOTHING`.
2. Check `cursor.rowcount`: if `1`, return `WRITTEN`. If `0`, return `ALREADY_EXISTS`.

Same pattern as `persist_opportunity`. The composite primary key
`(pipeline_execution_id, notification_type)` handles deduplication.

**Columns written**: All 13 columns defined in `POSTGRES_PERSISTENCE_SCHEMA.md` Section 7.

**Parameter types**: `TEXT` as `str`, `NUMERIC` as `Decimal`, `BOOLEAN` as `bool`,
`TIMESTAMPTZ` as `datetime`, `JSONB` as `list`.

### 8.4 `persist_audit_record` -> `audit_records`

**SQL flow**:

1. `INSERT INTO audit_records (...) VALUES (...)`. Always a plain insert. No conflict
   handling — audit records are append-only with a surrogate `id` primary key.
2. The `audit_written_at` column is set to `now()` in the SQL statement (not via Python's
   `datetime.now()`), so the timestamp reflects the database server's clock at insert time.
3. Return `WRITTEN`.

**Columns written**: All columns defined in `POSTGRES_PERSISTENCE_SCHEMA.md` Section 8
except `id` (auto-generated) and `audit_written_at` (set via `now()` in SQL).

**Parameter types**: `TEXT` as `str`, `NUMERIC` as `Decimal`, `TIMESTAMPTZ` as `datetime`,
`JSONB` as `dict` or `list`.

---

## 9. Idempotency Handling Plan

### 9.1 `pipeline_results`: Select-Then-Act

`persist_pipeline_result` uses a `SELECT` before `INSERT`/`UPDATE` because the idempotency
behavior depends on the existing row's `result_classification`:

- No row: `INSERT`.
- Existing `PROCESSING_FAILURE`: `UPDATE` (with a `WHERE` clause guarding the
  classification to prevent races).
- Existing finalized row: skip.

`ON CONFLICT` alone cannot express this three-way branching.

### 9.2 `opportunities` and `alert_decisions`: ON CONFLICT DO NOTHING

These tables have simpler idempotency rules — if a row exists, do nothing. `INSERT ... ON
CONFLICT DO NOTHING` handles this atomically. The `cursor.rowcount` distinguishes `WRITTEN`
from `ALREADY_EXISTS`.

### 9.3 `audit_records`: No Idempotency

Audit records use a surrogate `id` primary key. Every insert succeeds (barring infrastructure
failure). No deduplication is needed or desired.

### 9.4 Constraint Enforcement as Safety Net

Even though the writer performs application-layer checks (`SELECT` before write, `ON CONFLICT`
handling), the underlying PostgreSQL primary key and unique constraints serve as the final
safety net. If a concurrent process writes the same record between the writer's `SELECT` and
`INSERT`, the primary key violation prevents a duplicate. The writer classifies this specific
constraint violation as an idempotency signal (`ALREADY_EXISTS`), not as a terminal error.

---

## 10. Failure Handling Plan

### 10.1 Exception Classification

All `psycopg` exceptions in write methods are caught and classified:

| psycopg Exception | sqlstate | Classification | Writer Behavior |
|---|---|---|---|
| `UniqueViolation` | `23505` | Context-dependent | If expected (idempotency signal): return `ALREADY_EXISTS`. If unexpected: terminal `FAILED`. |
| `ForeignKeyViolation` | `23503` | Terminal | Return `FAILED`. Indicates write-order bug or missing parent row. |
| `CheckViolation` | `23514` | Terminal | Return `FAILED`. Indicates invalid data passed to the writer. |
| `NotNullViolation` | `23502` | Terminal | Return `FAILED`. Indicates missing required field. |
| `OperationalError` | Various | Transient | Return `FAILED` with `transient=True`. |
| `InterfaceError` | N/A | Transient | Return `FAILED` with `transient=True`. Connection lost. |

### 10.2 No Retry Loop

The writer does not retry on transient failures. It classifies the failure and returns it.
The caller (job layer) decides whether and when to retry the entire `persist_execution` call.

### 10.3 Failure Propagation Through `persist_execution`

`persist_execution` tracks the result of each individual write and determines the overall
outcome:

1. If `persist_pipeline_result` returns `FAILED`: set `persistence_outcome` to
   `RESULT_WRITE_FAILED`. Skip `persist_opportunity` and `persist_alert_decision`.
   Proceed to `persist_audit_record`.
2. If `persist_opportunity` or `persist_alert_decision` returns `FAILED`: set
   `persistence_outcome` to `PARTIAL_WRITE_FAILURE`. Continue with remaining writes
   in the sequence (a failed opportunity write does not prevent the alert decision write
   if the alert decision is also applicable). Proceed to `persist_audit_record`.
3. If `persist_audit_record` returns `FAILED`: escalate to `AUDIT_WRITE_FAILED` or
   `TOTAL_FAILURE` depending on whether non-audit writes succeeded.

### 10.4 Failure Detail in Audit Record

The `persistence_failure_detail` field in the audit record is a plain text description
constructed by the writer. It includes:

- Which write method failed (`persist_pipeline_result`, `persist_opportunity`, or
  `persist_alert_decision`).
- The target table.
- The exception class and message.
- The `sqlstate` code if available.

This field is not structured JSON — it is a human-readable diagnostic string for audit
review.

---

## 11. Audit Write Strategy

### 11.1 Audit Write on Happy Path

When all non-audit writes succeed, the audit record is written within the same transaction
as the other records. `persistence_outcome` is set to `ALL_WRITES_SUCCEEDED`.
`persistence_failure_detail` is set to `NULL`. `audit_written_at` is set to `now()` in SQL.

### 11.2 Audit Write on Failure Path

When any non-audit write fails:

1. The current transaction is rolled back.
2. A new transaction is started on the same connection.
3. The audit record is written with `persistence_outcome` reflecting the failure and
   `persistence_failure_detail` describing what failed.
4. The audit transaction is committed.

The audit record does not depend on any other table (no foreign key to `pipeline_results`),
so it is always writable regardless of what happened to the other writes.

### 11.3 Audit Write Failure

If the audit write itself fails, the writer:

1. Catches the exception.
2. Classifies it as transient or terminal.
3. Returns `AUDIT_WRITE_FAILED` or `TOTAL_FAILURE` to the caller.
4. Does not suppress the failure.

The writer cannot write a record documenting the audit write failure (that would be
recursive). The caller is responsible for logging this critical failure.

### 11.4 `audit_written_at` via SQL `now()`

The `audit_written_at` column is set via `now()` in the SQL `INSERT` statement, not via
Python's `datetime.now()`. This uses the database server's transaction timestamp, which is
consistent within the transaction and avoids clock skew between the application and database
servers.

---

## 12. Test Strategy

### 12.1 Test Database

Tests run against a real PostgreSQL instance, not mocks. The schema from
`POSTGRES_PERSISTENCE_SCHEMA.md` is applied to a test database before tests run.

**Local PostgreSQL**: Tests require a running PostgreSQL instance. The test setup creates
a dedicated test database (or schema) and applies the table definitions. Tests clean up
after themselves.

### 12.2 Test Isolation

Each test runs within a transaction that is rolled back after the test completes. This
ensures:

- Tests do not affect each other.
- No test data persists between runs.
- Tests can assert on exact row counts without interference.

For tests that exercise the writer's own transaction management (e.g., the audit-write-
on-failure path), a separate connection is used so that the test's wrapping transaction
does not conflict with the writer's explicit `rollback()` and `commit()` calls.

### 12.3 Test Coverage by Method

Each writer method is tested independently:

**`persist_pipeline_result`**:
- Insert a new row for each of the seven result classifications.
- Insert when a `PROCESSING_FAILURE` row already exists (expect `UPDATED`).
- Insert when a finalized row already exists (expect `ALREADY_EXISTS`).
- Insert with missing required field (expect terminal `FAILED`).

**`persist_opportunity`**:
- Insert for `OPPORTUNITY_DETECTED`.
- Insert for `OPPORTUNITY_SCORED_NO_ALERT`.
- Insert when a row already exists (expect `ALREADY_EXISTS`).
- Insert without a parent `pipeline_results` row (expect terminal `FAILED` — foreign key).

**`persist_alert_decision`**:
- Insert for `ALERT_ELIGIBLE`.
- Insert for `NO_ALERT`.
- Insert when a row already exists for the same `(pipeline_execution_id, notification_type)`
  (expect `ALREADY_EXISTS`).
- Insert without a parent `pipeline_results` row (expect terminal `FAILED` — foreign key).

**`persist_audit_record`**:
- Insert a new audit record.
- Insert multiple audit records for the same `pipeline_execution_id` (expect all to succeed).
- Verify `audit_written_at` is set and is a valid timestamp.

**`persist_execution`**:
- Full happy path for `OPPORTUNITY_DETECTED` (all four records written).
- Full happy path for `NO_OP` (only pipeline result + audit written).
- Full happy path for `VALIDATION_FAILURE` (only pipeline result + audit written).
- Duplicate execution (finalized row exists — expect `ALL_WRITES_SUCCEEDED` with
  `ALREADY_EXISTS` on pipeline result, audit still written).
- Retry after `PROCESSING_FAILURE` (existing failure row updated, dependent records written).
- Pipeline result write failure (expect `RESULT_WRITE_FAILED`, audit still written with
  failure detail).
- Opportunity write failure (expect `PARTIAL_WRITE_FAILURE`, audit still written with
  failure detail).
- Audit write failure (expect `AUDIT_WRITE_FAILED`).

### 12.4 Determinism Tests

- Write the same assembled result twice. Verify that all persisted field values are
  identical across both writes (excluding `audit_written_at` and `audit_records.id`).
- Verify that no column contains a value not present in the assembled result input
  (except `audit_written_at` and `id`).

### 12.5 Test File Location

Test file: `tests/test_persistence_writer.py`.

---

## 13. What This Implementation Must NOT Do

- **Use an ORM.** No SQLAlchemy, Django ORM, Peewee, Tortoise, or any other ORM.
- **Use a query builder.** No SQLAlchemy Core, pypika, or similar. All SQL is written as
  raw strings with parameter placeholders.
- **Construct SQL via string concatenation or interpolation.** All parameterization is via
  `psycopg`'s parameter binding (`%s` or `%(name)s` placeholders).
- **Implement connection pooling.** The writer accepts a single connection. Pooling is a
  future caller-level concern.
- **Implement retry logic.** The writer classifies failures and returns them. It does not
  retry.
- **Use stored procedures or database functions.** All logic is in the Python application
  layer.
- **Use triggers or listen/notify.** The writer performs explicit SQL operations only.
- **Compute, derive, or transform field values.** The writer extracts values from the
  assembled result and passes them as SQL parameters. No transformation.
- **Generate identifiers.** All identifiers come from the assembled result.
- **Read the system clock in Python for business-record timestamps.** `audit_written_at` is
  set via SQL `now()`, not via Python.
- **Suppress exceptions.** All database exceptions are caught, classified, and surfaced.
- **Use global state or module-level connections.** The writer is instantiated with a
  connection and is stateless between calls.

---

## 14. Success Criteria

This implementation is successful when:

1. All five writer methods (`persist_pipeline_result`, `persist_opportunity`,
   `persist_alert_decision`, `persist_audit_record`, `persist_execution`) are implemented
   in `src/aace_execution/persistence/writer.py`.
2. All SQL statements are defined as named constants in `src/aace_execution/persistence/sql.py`.
3. All structured return types are defined in `src/aace_execution/persistence/results.py`.
4. All failure classification logic is in `src/aace_execution/persistence/errors.py`.
5. The writer satisfies every success criterion in `PERSISTENCE_WRITER_CONTRACT.md` Section 14.
6. Tests in `tests/test_persistence_writer.py` pass against a real PostgreSQL instance.
7. Every test uses deterministic inputs and asserts on exact outcomes.
8. Idempotency is verified: writing the same result twice does not create duplicate rows
   (except audit records, which accumulate).
9. Failure paths are verified: non-audit write failures still produce audit records.
10. The audit record's `persistence_outcome` and `persistence_failure_detail` accurately
    reflect what happened during each test scenario.
11. No SQL is constructed via string concatenation or interpolation.
12. No ORM, query builder, or stored procedure is used.
13. No retry loop exists in the writer.
14. The implementation runs in a local development environment against a local PostgreSQL
    instance without production credentials.
15. `psycopg[binary]` is the only new dependency added to `pyproject.toml`.

---

## 15. Non-Acceptance Conditions

This implementation is not acceptable if any of the following are true:

- Any of the five required writer methods is missing.
- Any SQL statement is constructed via string concatenation or interpolation instead of
  parameterized queries.
- An ORM, query builder, or stored procedure is used.
- The writer creates, opens, or closes its own database connection instead of accepting one.
- The writer implements a retry loop for transient failures.
- The writer computes, derives, or transforms any field value from the assembled result.
- The writer generates or replaces any identifier.
- The writer sets a business-record timestamp from the Python system clock.
- A non-audit write failure prevents the audit record write from being attempted.
- A write failure is not classified as transient or terminal.
- A write failure is suppressed instead of being surfaced in the method return value and
  the `persist_execution` outcome.
- The audit record's `persistence_outcome` does not accurately reflect the outcome of
  preceding writes.
- `audit_written_at` is set via Python `datetime.now()` instead of SQL `now()`.
- Tests use mocks instead of a real PostgreSQL instance.
- Tests do not cover all seven result classifications.
- Tests do not verify idempotency (duplicate write produces no additional rows).
- Tests do not verify failure paths (audit written after non-audit failure).
- Any non-acceptance condition from `PERSISTENCE_WRITER_CONTRACT.md` Section 15 is present
  in the implementation.
- A dependency other than `psycopg[binary]` is added for persistence.
- Any file outside `src/aace_execution/persistence/`, `tests/test_persistence_writer.py`,
  and `pyproject.toml` is modified by this implementation.

Any of these conditions is a blocking defect.
The implementation must not be considered complete while any non-acceptance condition is
present.
