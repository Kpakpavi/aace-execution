# PostgreSQL Persistence Schema

## 1. Purpose

This document defines the PostgreSQL table schema contract for the AACE execution project's
persistence layer.

It specifies:

- the exact tables, columns, types, and nullability rules for all persisted record types,
- the primary key and uniqueness constraints that enforce idempotency,
- the foreign key relationships that enforce referential integrity,
- the write order, failure handling, and determinism rules expressed in PostgreSQL terms.

This is a schema contract, not an implementation document.
It does not contain migration scripts, ORM mappings, or application code.
It does not choose an ORM, migration tool, or connection library.
It defines what the PostgreSQL schema must look like so that any implementation can target it.

---

## 2. Relationship to Persistence Contract

This schema implements the storage requirements defined in `PERSISTENCE_CONTRACT.md`.

Every table in this schema corresponds to a record type defined in `PERSISTENCE_CONTRACT.md`
Section 5. Every column corresponds to a field defined in `PERSISTENCE_CONTRACT.md` Section 6.

This schema must not add columns, tables, or constraints that contradict the persistence
contract. Where the persistence contract defines a behavioral rule (e.g., write order,
idempotency, failure handling), this schema defines how that rule is expressed in PostgreSQL
structures.

Business rules and persistence requirements flow one direction:
`PERSISTENCE_CONTRACT.md` -> this schema contract.
This schema must not redefine any rule owned by the persistence contract.

---

## 3. Storage Objective

All four record types defined in `PERSISTENCE_CONTRACT.md` Section 5 are stored in PostgreSQL
tables. The schema must support:

- durable storage of every pipeline execution result regardless of outcome,
- unique constraint enforcement to prevent duplicate records on retries,
- append-only audit records that accumulate across retry attempts,
- conditional record writes (opportunity and alert decision records written only when applicable),
- queryability by `pipeline_execution_id` across all tables.

---

## 4. Table List

| Table | Persistence Contract Record Type | Written On Every Execution |
|---|---|---|
| `pipeline_results` | Pipeline Result Record (Section 5.1) | Yes |
| `opportunities` | Opportunity Record (Section 5.2) | No — only for `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT` |
| `alert_decisions` | Alert Decision Record (Section 5.3) | No — only when pipeline reaches Stage 4 |
| `audit_records` | Audit Record (Section 5.4) | Yes — including all failure paths |

---

## 5. Table: pipeline_results

This table stores one row per pipeline execution. It is the canonical record of what the
pipeline produced for a given `pipeline_execution_id`.

| Column | Type | Nullable | Purpose |
|---|---|---|---|
| `pipeline_execution_id` | `TEXT` | `NOT NULL` | Unique identifier for this pipeline run. Primary key and deduplication key. |
| `product_id` | `TEXT` | `NOT NULL` | Stable product identifier from the pipeline input context. |
| `result_classification` | `TEXT` | `NOT NULL` | One of: `OPPORTUNITY_DETECTED`, `OPPORTUNITY_SCORED_NO_ALERT`, `NO_OPPORTUNITY`, `NO_OP`, `VALIDATION_FAILURE`, `PRECONDITION_FAILURE`, `PROCESSING_FAILURE`. |
| `stage_reached` | `TEXT` | `NOT NULL` | The last pipeline stage that executed before the result was assembled. |
| `result_timestamp` | `TIMESTAMPTZ` | `NOT NULL` | ISO 8601 timestamp marking when the result was assembled. Must be the `freshness_reference_timestamp` carried through the pipeline, not the system clock at write time. |
| `stage_outcome_summary` | `JSONB` | `NOT NULL` | Structured summary listing each stage that executed and its output classification. |
| `retry_eligible` | `BOOLEAN` | `NULL` | For `PROCESSING_FAILURE` results: whether the failure is retriable. `NULL` for non-failure results. |
| `failure_stage` | `TEXT` | `NULL` | For `PROCESSING_FAILURE` results: which stage failed. `NULL` for non-failure results. |
| `failure_reason` | `TEXT` | `NULL` | For `PROCESSING_FAILURE` results: the classified failure reason. `NULL` for non-failure results. |

### Constraints

- **Primary key**: `pipeline_execution_id`
- **CHECK**: `result_classification IN ('OPPORTUNITY_DETECTED', 'OPPORTUNITY_SCORED_NO_ALERT', 'NO_OPPORTUNITY', 'NO_OP', 'VALIDATION_FAILURE', 'PRECONDITION_FAILURE', 'PROCESSING_FAILURE')`

---

## 6. Table: opportunities

This table stores one row per pipeline execution that produced an opportunity. It is only
written for `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT` results.

| Column | Type | Nullable | Purpose |
|---|---|---|---|
| `pipeline_execution_id` | `TEXT` | `NOT NULL` | Links this opportunity to the pipeline run that produced it. Primary key and deduplication key. |
| `product_id` | `TEXT` | `NOT NULL` | Stable product identifier. |
| `pair_id` | `TEXT` | `NOT NULL` | Canonical pair identifier from the discrepancy that produced this opportunity. |
| `result_classification` | `TEXT` | `NOT NULL` | `OPPORTUNITY_DETECTED` or `OPPORTUNITY_SCORED_NO_ALERT`. |
| `discrepancy_rule_id` | `TEXT` | `NOT NULL` | The discrepancy rule applied. |
| `discrepancy_source_a` | `TEXT` | `NOT NULL` | Canonical source identifier A. |
| `discrepancy_source_b` | `TEXT` | `NOT NULL` | Canonical source identifier B. |
| `price_a` | `NUMERIC` | `NOT NULL` | Normalized price from source A. |
| `price_b` | `NUMERIC` | `NOT NULL` | Normalized price from source B. |
| `absolute_difference` | `NUMERIC` | `NOT NULL` | Computed absolute price difference. |
| `percentage_difference` | `NUMERIC` | `NOT NULL` | Computed percentage price difference. |
| `score` | `NUMERIC` | `NOT NULL` | The final computed opportunity score. |
| `score_result_id` | `TEXT` | `NOT NULL` | Deterministic scoring result identifier. |
| `scoring_factors_applied` | `JSONB` | `NOT NULL` | The full factor breakdown from the scoring worker output. |
| `score_range` | `JSONB` | `NOT NULL` | The configured min and max of the scoring range. |
| `alert_decision` | `TEXT` | `NOT NULL` | `ALERT_ELIGIBLE` or `NO_ALERT`. |
| `alert_decision_id` | `TEXT` | `NOT NULL` | Deterministic alert decision identifier. |
| `suppression_reason` | `TEXT` | `NULL` | For `NO_ALERT`: the reason the alert was suppressed. `NULL` for `ALERT_ELIGIBLE`. |
| `opportunity_timestamp` | `TIMESTAMPTZ` | `NOT NULL` | ISO 8601 timestamp. Must be the `freshness_reference_timestamp` carried through the pipeline. |

### Constraints

- **Primary key**: `pipeline_execution_id`
- **Foreign key**: `pipeline_execution_id` references `pipeline_results(pipeline_execution_id)`
- **CHECK**: `result_classification IN ('OPPORTUNITY_DETECTED', 'OPPORTUNITY_SCORED_NO_ALERT')`
- **CHECK**: `alert_decision IN ('ALERT_ELIGIBLE', 'NO_ALERT')`

---

## 7. Table: alert_decisions

This table stores one row per alert decision evaluation within a pipeline execution. It is only
written when the pipeline reaches Stage 4 and produces an `ALERT_ELIGIBLE` or `NO_ALERT`
decision.

| Column | Type | Nullable | Purpose |
|---|---|---|---|
| `pipeline_execution_id` | `TEXT` | `NOT NULL` | Links this decision to the pipeline run. Part of composite primary key. |
| `notification_type` | `TEXT` | `NOT NULL` | The notification condition type evaluated. Part of composite primary key. |
| `alert_decision_id` | `TEXT` | `NOT NULL` | Deterministic identifier derived from `pipeline_execution_id` and `notification_type`. |
| `product_id` | `TEXT` | `NOT NULL` | Stable product identifier. |
| `pair_id` | `TEXT` | `NOT NULL` | Canonical pair identifier. |
| `score` | `NUMERIC` | `NOT NULL` | The score evaluated against the threshold. |
| `alert_threshold` | `NUMERIC` | `NOT NULL` | The configured threshold applied. |
| `threshold_met` | `BOOLEAN` | `NOT NULL` | Whether the score met or exceeded the threshold. |
| `decision_result` | `TEXT` | `NOT NULL` | `ALERT_ELIGIBLE` or `NO_ALERT`. |
| `suppression_reason` | `TEXT` | `NULL` | For `NO_ALERT`: the primary suppression reason. `NULL` for `ALERT_ELIGIBLE`. |
| `decision_basis` | `JSONB` | `NOT NULL` | Ordered list of rule evaluations from the alert decision worker. |
| `duplicate_check_result` | `TEXT` | `NOT NULL` | Pre-resolved duplicate check value: `NO_PRIOR_ALERT` or `PRIOR_ALERT_EXISTS`. |
| `decision_reference_timestamp` | `TIMESTAMPTZ` | `NOT NULL` | ISO 8601 timestamp from the alert decision worker input. |

### Constraints

- **Primary key**: `(pipeline_execution_id, notification_type)`
- **Foreign key**: `pipeline_execution_id` references `pipeline_results(pipeline_execution_id)`
- **UNIQUE**: `alert_decision_id`
- **CHECK**: `decision_result IN ('ALERT_ELIGIBLE', 'NO_ALERT')`
- **CHECK**: `duplicate_check_result IN ('NO_PRIOR_ALERT', 'PRIOR_ALERT_EXISTS')`

---

## 8. Table: audit_records

This table stores one row per pipeline execution attempt. Unlike other tables, audit records
are append-only — multiple rows for the same `pipeline_execution_id` are expected when retries
occur.

| Column | Type | Nullable | Purpose |
|---|---|---|---|
| `id` | `BIGINT GENERATED ALWAYS AS IDENTITY` | `NOT NULL` | Surrogate primary key. Required because `pipeline_execution_id` is not unique in this table (retries produce multiple audit records). |
| `pipeline_execution_id` | `TEXT` | `NOT NULL` | The pipeline run this audit record describes. Indexed but not unique. |
| `product_id` | `TEXT` | `NOT NULL` | Stable product identifier. |
| `result_classification` | `TEXT` | `NOT NULL` | The final result classification of the pipeline execution. |
| `result_timestamp` | `TIMESTAMPTZ` | `NOT NULL` | ISO 8601 timestamp of result assembly. |
| `stage_outcome_summary` | `JSONB` | `NOT NULL` | Each stage that executed and its output classification. |
| `discrepancy_rule_applied` | `TEXT` | `NULL` | For `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT`: the rule ID. `NULL` otherwise. |
| `score` | `NUMERIC` | `NULL` | For `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT`: the computed score. `NULL` otherwise. |
| `scoring_factor_summary` | `JSONB` | `NULL` | For `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT`: the factor breakdown. `NULL` otherwise. |
| `alert_decision` | `TEXT` | `NULL` | For `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT`: the alert eligibility decision. `NULL` otherwise. |
| `failure_stage` | `TEXT` | `NULL` | For `PROCESSING_FAILURE`: the stage where the failure occurred. `NULL` otherwise. |
| `failure_reason` | `TEXT` | `NULL` | For `PROCESSING_FAILURE`: the classified failure reason. `NULL` otherwise. |
| `early_exit_stage` | `TEXT` | `NULL` | For `NO_OP` and `NO_OPPORTUNITY`: the stage at which the pipeline exited early. `NULL` otherwise. |
| `early_exit_reason` | `TEXT` | `NULL` | For `NO_OP` and `NO_OPPORTUNITY`: the reason for early exit. `NULL` otherwise. |
| `persistence_outcome` | `TEXT` | `NOT NULL` | Whether all other persistence writes for this execution succeeded. One of: `ALL_WRITES_SUCCEEDED`, `PARTIAL_WRITE_FAILURE`, `RESULT_WRITE_FAILED`. |
| `persistence_failure_detail` | `TEXT` | `NULL` | If any persistence write failed, a description of which write failed and why. `NULL` if all writes succeeded. |
| `audit_written_at` | `TIMESTAMPTZ` | `NOT NULL` | Timestamp of when this audit record was written. This is the one column permitted to use the actual system clock at write time. |

### Constraints

- **Primary key**: `id`
- **INDEX**: `pipeline_execution_id` (non-unique index for querying all audit records for a given execution)
- **CHECK**: `result_classification IN ('OPPORTUNITY_DETECTED', 'OPPORTUNITY_SCORED_NO_ALERT', 'NO_OPPORTUNITY', 'NO_OP', 'VALIDATION_FAILURE', 'PRECONDITION_FAILURE', 'PROCESSING_FAILURE')`
- **CHECK**: `persistence_outcome IN ('ALL_WRITES_SUCCEEDED', 'PARTIAL_WRITE_FAILURE', 'RESULT_WRITE_FAILED')`

### No Foreign Key to pipeline_results

The `audit_records` table does not have a foreign key referencing `pipeline_results`. This is
intentional: audit records must be writable even when the pipeline result record write fails.
A foreign key constraint would prevent writing the audit record in that scenario, violating
`PERSISTENCE_CONTRACT.md` Section 7 Rule 4 and Section 9.1.

---

## 9. Primary Keys and Uniqueness Rules

| Table | Primary Key | Uniqueness Guarantee |
|---|---|---|
| `pipeline_results` | `pipeline_execution_id` | One row per pipeline execution. Enforced by primary key. |
| `opportunities` | `pipeline_execution_id` | One row per pipeline execution that produced an opportunity. Enforced by primary key. |
| `alert_decisions` | `(pipeline_execution_id, notification_type)` | One row per notification type per pipeline execution. Enforced by composite primary key. Additionally, `alert_decision_id` has a unique constraint. |
| `audit_records` | `id` (surrogate) | Multiple rows per `pipeline_execution_id` are permitted. `pipeline_execution_id` is indexed but not unique. |

---

## 10. Foreign Key Rules

1. `opportunities.pipeline_execution_id` references `pipeline_results.pipeline_execution_id`.
   An opportunity row must not exist without a corresponding pipeline result row.

2. `alert_decisions.pipeline_execution_id` references `pipeline_results.pipeline_execution_id`.
   An alert decision row must not exist without a corresponding pipeline result row.

3. `audit_records` has no foreign key to `pipeline_results`. Audit records must be writable
   independently of all other tables. This supports the requirement that audit records are
   written even when pipeline result writes fail.

4. All foreign keys use the default `NO ACTION` behavior. Deletion or update of referenced
   rows is not expected in normal operation — finalized records are immutable. If a
   `PROCESSING_FAILURE` result is superseded by a retry, the application layer must handle
   the update sequence (update `pipeline_results` before inserting dependent rows), not rely
   on cascading behavior.

---

## 11. Write Order Rules

Writes for a single pipeline execution must occur in this order:

1. `INSERT` into `pipeline_results`
2. `INSERT` into `opportunities` (if result classification is `OPPORTUNITY_DETECTED` or `OPPORTUNITY_SCORED_NO_ALERT`)
3. `INSERT` into `alert_decisions` (if pipeline reached Stage 4)
4. `INSERT` into `audit_records` (always — must be last)

This order is required because:

- `opportunities` and `alert_decisions` have foreign keys to `pipeline_results`, so the
  parent row must exist first.
- `audit_records` must capture the outcome of all preceding writes in its
  `persistence_outcome` column, so it must be written last.

All writes for a single pipeline execution should occur within a single database transaction,
with the exception of the audit record write on failure paths (see Section 13).

---

## 12. Idempotency Rules

1. **Primary key enforcement prevents duplicate inserts.** Attempting to `INSERT` a row with
   a `pipeline_execution_id` that already exists in `pipeline_results`, `opportunities`, or
   `alert_decisions` will raise a unique constraint violation. The application layer must
   handle this as a duplicate write, not as an unexpected error.

2. **Retry after `PROCESSING_FAILURE` uses upsert semantics.** When a pipeline execution is
   retried after a `PROCESSING_FAILURE`, the application layer must:
   - Check whether the existing `pipeline_results` row has `result_classification = 'PROCESSING_FAILURE'`.
   - If yes: `UPDATE` the existing row with the new result. Then insert `opportunities` and
     `alert_decisions` rows if applicable.
   - If no (the existing row is a finalized result): reject the write. A finalized result
     must not be overwritten.

3. **Audit records are always inserted, never upserted.** Because audit records use a surrogate
   `id` primary key and `pipeline_execution_id` is not unique, every write is a fresh `INSERT`.
   Retries accumulate audit records — this is correct behavior.

4. **Constraint violations as idempotency signals.** A unique constraint violation on
   `pipeline_results.pipeline_execution_id` for a non-`PROCESSING_FAILURE` existing row is
   not an error — it is a signal that the write was already completed. The application layer
   must treat this as a successful no-op, not as a failure.

---

## 13. Failure Handling Rules

1. **Transaction rollback on non-audit write failure.** If any write to `pipeline_results`,
   `opportunities`, or `alert_decisions` fails, the transaction containing those writes must
   be rolled back to prevent partial state.

2. **Audit record write in a separate transaction on failure paths.** When a preceding write
   fails and the transaction is rolled back, the audit record must be written in a new,
   independent transaction. The audit record's `persistence_outcome` must reflect the failure
   (`RESULT_WRITE_FAILED` or `PARTIAL_WRITE_FAILURE`) and `persistence_failure_detail` must
   describe what failed.

3. **Audit record write failure is a critical error.** If the audit record write itself fails,
   the failure must be surfaced explicitly to the caller. The pipeline execution must be
   treated as incomplete. The failure must be logged at the highest available severity level.

4. **Transient vs. terminal failure distinction.** The application layer must distinguish
   between:
   - **Transient failures** (connection timeout, temporary unavailability): may be retried
     with bounded retry count.
   - **Terminal failures** (constraint violation indicating logic error, schema mismatch):
     must not be retried. Must be surfaced immediately.

5. **No silent failure suppression.** Every write failure must be captured in the audit record's
   `persistence_outcome` and `persistence_failure_detail` columns. A write failure that is not
   reflected in the audit trail is a persistence defect.

---

## 14. Determinism Rules

1. **No `DEFAULT` expressions that introduce non-determinism on business columns.** Columns
   in `pipeline_results`, `opportunities`, and `alert_decisions` must not use `DEFAULT now()`,
   `DEFAULT gen_random_uuid()`, or any other non-deterministic default. All values must come
   from the application layer, which receives them from the assembled pipeline result.

2. **`audit_written_at` is the sole exception.** This column may use `DEFAULT now()` or be
   set by the application layer at write time. It is the only column permitted to reflect
   the actual system clock.

3. **No triggers that modify row content.** No `BEFORE INSERT` or `BEFORE UPDATE` triggers
   may alter column values. The persisted row must exactly match what the application layer
   wrote. Triggers for logging or notification purposes are outside the scope of this schema
   contract.

4. **No generated columns derived from other columns.** All column values are written
   explicitly by the application layer. PostgreSQL `GENERATED ALWAYS AS` columns must not
   be used for business data.

5. **`NUMERIC` type for all monetary and score values.** `NUMERIC` (arbitrary precision) is
   used instead of `FLOAT` or `DOUBLE PRECISION` to avoid floating-point representation
   differences that would violate determinism. Given the same input, the same value must be
   stored every time.

---

## 15. What This Schema Must NOT Do

- **Define application logic in stored procedures or functions.** Business rules, write-order
  orchestration, and idempotency handling belong in the application layer, not in PL/pgSQL.
- **Use cascading deletes or updates.** Finalized records are immutable. Cascading behavior
  would enable silent modification of downstream records.
- **Include tables for notification delivery, scheduling, or external API state.** This schema
  covers the four persistence contract record types only.
- **Define row-level security policies or roles.** Access control is an infrastructure concern
  outside this schema contract.
- **Choose a partitioning strategy.** Partitioning is a performance optimization to be decided
  at implementation time, not in the schema contract.
- **Specify index types beyond primary keys and the `audit_records.pipeline_execution_id`
  index.** Additional indexes are performance optimizations to be decided at implementation
  time.
- **Choose an ORM, migration tool, or connection library.** This schema defines what must
  exist in PostgreSQL, not how it gets there.

---

## 16. Success Criteria

This schema is successful when:

1. All four tables (`pipeline_results`, `opportunities`, `alert_decisions`, `audit_records`)
   can be created in a PostgreSQL database without errors.
2. Every column defined in `PERSISTENCE_CONTRACT.md` Section 6 has a corresponding column in
   the appropriate table with a compatible PostgreSQL type.
3. The primary key on `pipeline_results` prevents duplicate rows for the same
   `pipeline_execution_id`.
4. The primary key on `opportunities` prevents duplicate rows for the same
   `pipeline_execution_id`.
5. The composite primary key on `alert_decisions` prevents duplicate rows for the same
   `(pipeline_execution_id, notification_type)` pair.
6. The unique constraint on `alert_decisions.alert_decision_id` prevents duplicate decision
   identifiers.
7. The surrogate primary key on `audit_records` allows multiple rows per
   `pipeline_execution_id`.
8. Foreign keys on `opportunities` and `alert_decisions` enforce referential integrity to
   `pipeline_results`.
9. The absence of a foreign key on `audit_records` allows audit writes even when pipeline
   result writes fail.
10. `CHECK` constraints on `result_classification`, `persistence_outcome`, `decision_result`,
    and `duplicate_check_result` restrict values to their defined enumerations.
11. `NUMERIC` is used for all monetary and score columns, preventing floating-point
    determinism violations.
12. No column uses a non-deterministic `DEFAULT` except `audit_written_at`.
13. No trigger, stored procedure, or generated column modifies persisted values.

---

## 17. Non-Acceptance Conditions

This schema is not acceptable if any of the following are true:

- A column defined in `PERSISTENCE_CONTRACT.md` Section 6 has no corresponding column in the
  schema.
- A table is missing from the schema.
- `pipeline_results` allows duplicate rows for the same `pipeline_execution_id`.
- `opportunities` allows duplicate rows for the same `pipeline_execution_id`.
- `alert_decisions` allows duplicate rows for the same
  `(pipeline_execution_id, notification_type)` pair.
- `audit_records` prevents multiple rows for the same `pipeline_execution_id`.
- A foreign key on `audit_records` prevents audit writes when `pipeline_results` writes fail.
- A `NOT NULL` column is defined as nullable or vice versa relative to the persistence
  contract field requirements.
- A monetary or score column uses `FLOAT`, `DOUBLE PRECISION`, or `REAL` instead of `NUMERIC`.
- A business-record timestamp column uses a non-deterministic `DEFAULT` expression.
- A trigger or generated column modifies persisted row content.
- The schema includes tables, columns, or constraints not traceable to the persistence
  contract.
- The schema defines stored procedures, functions, or application logic.
- The schema specifies an ORM, migration tool, or connection library.

Any of these conditions is a blocking defect.
The schema must not be considered complete while any non-acceptance condition is present.
