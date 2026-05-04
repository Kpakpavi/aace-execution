# Persistence Writer Contract

## 1. Purpose

This document defines the interface contract for the persistence writer — the application-layer
component responsible for accepting assembled pipeline results and writing them to the system
of record.

It defines:

- what the writer receives as input,
- what methods the writer must expose,
- the input and output contracts for each method,
- the write order, idempotency, and failure handling responsibilities the writer must fulfill,
- how the writer reports success, partial success, and terminal failure,
- what the writer is and is not allowed to do.

This is an interface contract, not an implementation document.
It does not contain code, pseudocode, or framework-specific instructions.
It does not choose raw SQL, an ORM, a connection pool library, or a transaction management
strategy.
It defines the behavioral contract that any persistence writer implementation must satisfy.

---

## 2. Relationship to Persistence Contract and PostgreSQL Schema Contract

This writer contract sits between the persistence contract and the storage layer.

```
PERSISTENCE_CONTRACT.md
  Defines: what data must be persisted, when, and under what rules.

POSTGRES_PERSISTENCE_SCHEMA.md
  Defines: the PostgreSQL tables, columns, types, constraints, and structural rules.

PERSISTENCE_WRITER_CONTRACT.md (this document)
  Defines: the application-layer interface that accepts assembled pipeline results
  and writes them to the tables defined in the schema, following the rules defined
  in the persistence contract.
```

The persistence contract defines the behavioral requirements.
The PostgreSQL schema contract defines the storage structure.
This writer contract defines how the application layer bridges the two.

Rules flow one direction:
`PERSISTENCE_CONTRACT.md` -> this writer contract.
`POSTGRES_PERSISTENCE_SCHEMA.md` -> this writer contract (for structural compatibility).

This writer contract must not redefine any rule owned by the persistence contract or the
schema contract. It must not add persistence behaviors, record types, or fields not defined
in those contracts.

---

## 3. Writer Objective

The persistence writer is the single component responsible for writing assembled pipeline
results to the system of record. It is invoked after the pipeline orchestrator completes
Stage 5 (result assembly) and Stage 6 (audit emission).

Its objective is to:

- accept the assembled pipeline result and the audit event produced by the orchestrator,
- write each required record to the system of record in the defined order,
- enforce idempotency by detecting and handling duplicate writes,
- ensure that audit records are written even when other writes fail,
- report the outcome of all writes back to the caller with enough detail to determine
  whether the pipeline execution is complete.

The writer makes no business decisions.
It does not evaluate, filter, transform, or supplement the data it receives.
It writes what the pipeline produced — nothing more, nothing less.

---

## 4. Inputs to the Writer

The writer receives a single assembled pipeline result object as its primary input.
This object is the output of Stage 5 (result assembly) as defined in
`PIPELINE_ORCHESTRATION_CONTRACT.md` Section 6.

The assembled result contains all the field values needed to populate every record type
applicable to this pipeline execution. The writer extracts fields from this result — it does
not compute, derive, or fetch any field value.

### 4.1 Fields Always Present in the Assembled Result

The following fields are always present regardless of result classification:

- `pipeline_execution_id`
- `product_id`
- `result_classification`
- `stage_reached`
- `result_timestamp`
- `stage_outcome_summary`

### 4.2 Fields Present Only for Specific Result Classifications

The following fields are present only when the result classification requires them,
as defined in `PERSISTENCE_CONTRACT.md` Section 6:

- **For `PROCESSING_FAILURE`**: `retry_eligible`, `failure_stage`, `failure_reason`
- **For `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT`**: all opportunity fields
  (`pair_id`, `discrepancy_rule_id`, `discrepancy_source_a`, `discrepancy_source_b`,
  `price_a`, `price_b`, `absolute_difference`, `percentage_difference`, `score`,
  `score_result_id`, `scoring_factors_applied`, `score_range`, `alert_decision`,
  `alert_decision_id`, `suppression_reason`, `opportunity_timestamp`)
- **For executions that reached Stage 4**: all alert decision fields
  (`alert_decision_id`, `pair_id`, `score`, `alert_threshold`, `threshold_met`,
  `decision_result`, `suppression_reason`, `decision_basis`, `notification_type`,
  `duplicate_check_result`, `decision_reference_timestamp`)

### 4.3 Audit Event Input

The writer also receives the Stage 6 audit event, which contains the fields defined in
`PERSISTENCE_CONTRACT.md` Section 6.4. The audit event is a separate input from the
assembled result because the audit record includes fields that describe the persistence
outcome itself (`persistence_outcome`, `persistence_failure_detail`), which are determined
by the writer during execution and must be set by the writer before the audit record is
written.

The writer receives the audit event with `persistence_outcome` and
`persistence_failure_detail` unset. The writer must populate these fields based on the
outcome of the preceding writes before persisting the audit record.

### 4.4 What the Writer Must NOT Do With Inputs

- Must not add fields not present in the assembled result.
- Must not remove or omit fields that are present.
- Must not transform, normalize, or reformat field values.
- Must not substitute timestamps with the system clock (except `audit_written_at`).
- Must not generate or replace identifiers (`pipeline_execution_id`, `score_result_id`,
  `alert_decision_id`, `pair_id`).

---

## 5. Records the Writer Can Persist

The writer is responsible for persisting exactly four record types, corresponding to the
four tables defined in `POSTGRES_PERSISTENCE_SCHEMA.md`:

| Record Type | Target Table | When Written |
|---|---|---|
| Pipeline result record | `pipeline_results` | Every pipeline execution, regardless of result classification. |
| Opportunity record | `opportunities` | Only when `result_classification` is `OPPORTUNITY_DETECTED` or `OPPORTUNITY_SCORED_NO_ALERT`. |
| Alert decision record | `alert_decisions` | Only when the pipeline reached Stage 4 and produced an `ALERT_ELIGIBLE` or `NO_ALERT` decision. |
| Audit record | `audit_records` | Every pipeline execution, regardless of result classification. Must be attempted even when other writes fail. |

### 5.1 Records That Must Always Be Attempted

Two record types must be attempted for every pipeline execution:

1. **Pipeline result record** — must be attempted for all seven result classifications.
2. **Audit record** — must be attempted for all seven result classifications, including
   when the pipeline result record write itself fails.

### 5.2 Records That Must NOT Be Written on Certain Paths

- An opportunity record must not be written for `VALIDATION_FAILURE`, `PRECONDITION_FAILURE`,
  `NO_OPPORTUNITY`, `NO_OP`, or `PROCESSING_FAILURE` results. Writing an opportunity record
  for these classifications is a writer defect.
- An alert decision record must not be written for pipeline executions that did not reach
  Stage 4. Writing an alert decision record for such executions is a writer defect.

---

## 6. Required Writer Methods

The writer must expose the following methods. Each method has a defined responsibility,
input, and output contract specified in Section 7.

| Method | Responsibility |
|---|---|
| `persist_pipeline_result` | Write the pipeline result record. |
| `persist_opportunity` | Write the opportunity record. |
| `persist_alert_decision` | Write the alert decision record. |
| `persist_audit_record` | Write the audit record. |
| `persist_execution` | Top-level method that orchestrates all writes for a single pipeline execution in the correct order, handles failures, and returns the overall persistence outcome. |

### 6.1 Why Individual Methods

Each record type has its own method so that:

- failure in one write can be isolated without preventing the audit record write,
- idempotency handling can be specific to each record type's uniqueness rules,
- testing can exercise each write independently with deterministic inputs.

### 6.2 Why a Top-Level Method

The `persist_execution` method exists so that:

- write order is enforced in a single place,
- the caller does not need to know which records apply to which result classification,
- the audit record's `persistence_outcome` field can be populated based on the outcome of
  all preceding writes,
- the caller receives a single, structured outcome describing the result of all persistence
  operations.

---

## 7. Method Input/Output Contracts

### 7.1 `persist_pipeline_result`

**Input**: The fields required for the `pipeline_results` table as defined in
`POSTGRES_PERSISTENCE_SCHEMA.md` Section 5. Extracted from the assembled pipeline result.

**Behavior**:
- Writes one row to `pipeline_results`.
- If a row already exists for this `pipeline_execution_id` with a finalized result
  classification (`OPPORTUNITY_DETECTED`, `OPPORTUNITY_SCORED_NO_ALERT`, `NO_OPPORTUNITY`,
  `NO_OP`), the write must be treated as a successful no-op. The existing row must not be
  modified.
- If a row already exists with `result_classification = 'PROCESSING_FAILURE'`, the existing
  row must be updated with the new result. This supports retry-after-failure.
- If no row exists, a new row is inserted.

**Output**: A structured result indicating one of:
- `WRITTEN` — a new row was inserted.
- `UPDATED` — an existing `PROCESSING_FAILURE` row was updated with a new result.
- `ALREADY_EXISTS` — a finalized row already exists. No write occurred.
- `FAILED` — the write failed. Includes the failure reason and whether the failure is
  transient or terminal.

### 7.2 `persist_opportunity`

**Input**: The fields required for the `opportunities` table as defined in
`POSTGRES_PERSISTENCE_SCHEMA.md` Section 6. Extracted from the assembled pipeline result.

**Precondition**: `result_classification` must be `OPPORTUNITY_DETECTED` or
`OPPORTUNITY_SCORED_NO_ALERT`. The writer must not call this method for any other
classification. Violating this precondition is a writer defect.

**Behavior**:
- Writes one row to `opportunities`.
- If a row already exists for this `pipeline_execution_id`, the write must be treated as a
  successful no-op. The existing row must not be modified.
- If no row exists, a new row is inserted.

**Output**: A structured result indicating one of:
- `WRITTEN` — a new row was inserted.
- `ALREADY_EXISTS` — a row already exists. No write occurred.
- `FAILED` — the write failed. Includes the failure reason and whether the failure is
  transient or terminal.

### 7.3 `persist_alert_decision`

**Input**: The fields required for the `alert_decisions` table as defined in
`POSTGRES_PERSISTENCE_SCHEMA.md` Section 7. Extracted from the assembled pipeline result.

**Precondition**: The pipeline must have reached Stage 4 and produced an `ALERT_ELIGIBLE` or
`NO_ALERT` decision. The writer must not call this method for executions that did not reach
Stage 4. Violating this precondition is a writer defect.

**Behavior**:
- Writes one row to `alert_decisions`.
- If a row already exists for this `(pipeline_execution_id, notification_type)` pair, the
  write must be treated as a successful no-op. The existing row must not be modified.
- If no row exists, a new row is inserted.

**Output**: A structured result indicating one of:
- `WRITTEN` — a new row was inserted.
- `ALREADY_EXISTS` — a row already exists. No write occurred.
- `FAILED` — the write failed. Includes the failure reason and whether the failure is
  transient or terminal.

### 7.4 `persist_audit_record`

**Input**: The fields required for the `audit_records` table as defined in
`POSTGRES_PERSISTENCE_SCHEMA.md` Section 8. Includes the `persistence_outcome` and
`persistence_failure_detail` fields populated by the writer based on the outcome of preceding
writes.

**Behavior**:
- Always inserts a new row into `audit_records`. Audit records are append-only and never
  deduplicated.
- Sets `audit_written_at` to the current system time at the moment of write. This is the
  one field the writer is permitted to derive from the system clock.
- Multiple audit records for the same `pipeline_execution_id` are expected and correct
  (retries produce additional audit records).

**Output**: A structured result indicating one of:
- `WRITTEN` — a new row was inserted.
- `FAILED` — the write failed. Includes the failure reason and whether the failure is
  transient or terminal. This is a critical failure.

### 7.5 `persist_execution`

**Input**: The assembled pipeline result and the audit event (with `persistence_outcome` and
`persistence_failure_detail` unset).

**Behavior**:
1. Determine which record types are required based on `result_classification` and which
   stages executed (see Section 5).
2. Write required records in the order defined in Section 8.
3. If any non-audit write fails, proceed to the audit record write with the failure captured
   in `persistence_outcome` and `persistence_failure_detail`.
4. Return a structured outcome describing the result of all writes.

**Output**: A structured result indicating one of:
- `ALL_WRITES_SUCCEEDED` — every required record was written (or confirmed as already
  existing). The pipeline execution is complete.
- `PARTIAL_WRITE_FAILURE` — the pipeline result was written, but one or more dependent
  records (opportunity or alert decision) failed. The audit record was written with the
  failure captured. The pipeline execution is incomplete.
- `RESULT_WRITE_FAILED` — the pipeline result record write failed. No dependent records
  were attempted. The audit record was written with the failure captured. The pipeline
  execution is incomplete.
- `AUDIT_WRITE_FAILED` — all non-audit writes succeeded (or were not required), but the
  audit record write failed. The pipeline execution is incomplete. This is a critical failure.
- `TOTAL_FAILURE` — both the non-audit writes and the audit record write failed. The pipeline
  execution is incomplete. This is a critical failure.

Each outcome must include:
- The individual result of every write that was attempted.
- The `pipeline_execution_id` for traceability.

---

## 8. Write Order Responsibilities

The writer must execute writes in this fixed order for every pipeline execution:

1. `persist_pipeline_result` — always first.
2. `persist_opportunity` — second, if applicable to this result classification.
3. `persist_alert_decision` — third, if applicable to this execution.
4. `persist_audit_record` — always last.

### 8.1 Why This Order

- `opportunities` and `alert_decisions` have foreign key dependencies on `pipeline_results`
  in the PostgreSQL schema. The parent row must exist before dependent rows can be inserted.
- `audit_records` must capture the outcome of all preceding writes in its
  `persistence_outcome` field. It cannot be written until all other writes have been attempted
  or skipped.

### 8.2 Order Enforcement

The writer must not reorder, parallelize, or batch writes across record types within a single
pipeline execution. Writes must be sequential within the execution.

The writer must not batch or interleave writes across different pipeline executions. Each
`persist_execution` call handles exactly one `pipeline_execution_id`.

---

## 9. Idempotency Responsibilities

### 9.1 Duplicate Detection

The writer must detect when a write targets a record that already exists:

- For `pipeline_results`: detect via `pipeline_execution_id` uniqueness.
- For `opportunities`: detect via `pipeline_execution_id` uniqueness.
- For `alert_decisions`: detect via `(pipeline_execution_id, notification_type)` uniqueness.
- For `audit_records`: no duplicate detection. Every write is a new insert.

### 9.2 Duplicate Handling

When a duplicate is detected:

- If the existing `pipeline_results` row has a finalized result classification
  (`OPPORTUNITY_DETECTED`, `OPPORTUNITY_SCORED_NO_ALERT`, `NO_OPPORTUNITY`, `NO_OP`):
  treat the write as a successful no-op. Return `ALREADY_EXISTS`. Do not modify the existing
  row. Do not attempt dependent writes (`opportunities`, `alert_decisions`).
- If the existing `pipeline_results` row has `result_classification = 'PROCESSING_FAILURE'`:
  update the existing row with the new result. Return `UPDATED`. Proceed with dependent
  writes as applicable.
- If an `opportunities` or `alert_decisions` row already exists: treat the write as a
  successful no-op. Return `ALREADY_EXISTS`. Do not modify the existing row.

### 9.3 Idempotency Must Not Depend on Application-Layer Checks Alone

The writer may perform application-layer checks (e.g., read-before-write) for efficiency
or to distinguish between `ALREADY_EXISTS` and `UPDATED` outcomes. However, the underlying
storage layer must also enforce uniqueness constraints. Application-layer checks are an
optimization, not a substitute for constraint enforcement.

### 9.4 `persist_execution` Behavior on Full Duplicate

If `persist_pipeline_result` returns `ALREADY_EXISTS` (finalized result), then
`persist_execution` must:

- Skip `persist_opportunity` and `persist_alert_decision`.
- Still write the audit record with `persistence_outcome = 'ALL_WRITES_SUCCEEDED'`
  (the original writes already succeeded; the duplicate attempt is a no-op).
- Return `ALL_WRITES_SUCCEEDED`.

---

## 10. Failure Handling Responsibilities

### 10.1 Non-Audit Write Failure

If `persist_pipeline_result`, `persist_opportunity`, or `persist_alert_decision` returns
`FAILED`:

1. **Stop dependent writes.** If `persist_pipeline_result` fails, do not attempt
   `persist_opportunity` or `persist_alert_decision` (foreign key dependency would cause
   them to fail).
2. **Proceed to audit write.** The audit record must still be attempted regardless of which
   non-audit write failed.
3. **Populate audit failure fields.** Set `persistence_outcome` to `RESULT_WRITE_FAILED`
   (if the pipeline result write failed) or `PARTIAL_WRITE_FAILURE` (if the pipeline result
   succeeded but a dependent write failed). Set `persistence_failure_detail` to describe
   which write failed and the failure reason.
4. **Report to caller.** Return the appropriate `persist_execution` outcome
   (`RESULT_WRITE_FAILED` or `PARTIAL_WRITE_FAILURE`).

### 10.2 Audit Write Failure

If `persist_audit_record` returns `FAILED`:

1. **Surface as critical error.** The writer must not suppress this failure.
2. **Report to caller.** Return `AUDIT_WRITE_FAILED` (if non-audit writes succeeded) or
   `TOTAL_FAILURE` (if both non-audit and audit writes failed).
3. **Include diagnostic detail.** The failure reason from the audit write must be included
   in the `persist_execution` outcome.

### 10.3 Transient vs. Terminal Failures

Every `FAILED` result from an individual write method must indicate whether the failure is
transient or terminal:

- **Transient failures** (connection timeout, temporary unavailability, lock contention):
  the caller may retry the write with bounded retry count. Each retry attempt must be logged.
- **Terminal failures** (unique constraint violation indicating a logic error, schema mismatch,
  data type violation): must not be retried. Must be surfaced immediately with diagnostic
  context.

The writer must not implement its own retry loop for transient failures. Retry policy is the
caller's responsibility. The writer reports the failure classification; the caller decides
whether to retry.

### 10.4 No Silent Failure Suppression

Every write failure must be:

- reflected in the individual method's return value,
- captured in the audit record's `persistence_outcome` and `persistence_failure_detail`
  (if the audit write itself succeeds),
- included in the `persist_execution` outcome returned to the caller.

A write failure that does not appear in all three locations is a writer defect.

---

## 11. Audit Write Rules

The audit record write has special rules that differ from all other record types:

### 11.1 Always Attempted

The writer must attempt to write the audit record for every pipeline execution, regardless
of:

- the result classification,
- whether the pipeline result write succeeded or failed,
- whether the opportunity or alert decision writes succeeded or failed.

There is no condition under which the writer may skip the audit record write.

### 11.2 Written After All Other Writes

The audit record is always the last record written. This is because the audit record's
`persistence_outcome` field must reflect the outcome of all preceding writes.

### 11.3 Independent of Prior Write Success

The audit record write must not depend on the success of any prior write. If the pipeline
result record write failed and was rolled back, the audit record must still be writable.
This is why the `audit_records` table has no foreign key to `pipeline_results` in the
PostgreSQL schema.

### 11.4 Separate Transaction on Failure Paths

If non-audit writes fail and their transaction is rolled back, the audit record must be
written in a new, independent transaction. The writer must not attempt to write the audit
record within a rolled-back transaction.

### 11.5 `audit_written_at` Set by the Writer

The writer sets `audit_written_at` to the current system time when writing the audit record.
This is the one field the writer is permitted to derive from the system clock.

### 11.6 Append-Only

Audit records are never updated or deleted after being written. Each call to
`persist_audit_record` produces a new row. Multiple audit records for the same
`pipeline_execution_id` are expected and correct.

---

## 12. Determinism Rules

1. **Same assembled result produces same records.** Given the same assembled pipeline result,
   the writer must produce the same set of record writes with the same field values on every
   invocation. The sole exception is `audit_written_at`, which reflects the actual write time.

2. **No computed or derived fields.** The writer must not compute, derive, or transform any
   field value from the assembled result. It extracts and writes — it does not evaluate.

3. **No conditional field population based on runtime state.** The writer must not populate
   fields differently based on system load, connection pool state, time of day, or any other
   runtime condition. Field population is determined solely by the assembled result content and
   the record type rules in `PERSISTENCE_CONTRACT.md` Section 6.

4. **No system-clock timestamps in business records.** All timestamps in pipeline result
   records, opportunity records, and alert decision records must come from the assembled
   pipeline result. The writer must not substitute the system clock for any business-record
   timestamp. The only exception is `audit_written_at`.

5. **Record content must not depend on write order outcomes.** Although writes occur in a
   fixed order, the content of each record must not change based on whether earlier writes
   succeeded or failed. The only exception is the audit record, whose `persistence_outcome`
   and `persistence_failure_detail` fields are populated based on prior write outcomes by
   design.

6. **No random identifiers.** The writer must not generate identifiers. All identifiers
   (`pipeline_execution_id`, `score_result_id`, `alert_decision_id`, `pair_id`) are provided
   in the assembled pipeline result. The writer uses them as-is.

---

## 13. What the Writer Must NOT Do

The following are explicitly forbidden in the persistence writer:

- **Evaluate business rules.** The writer does not determine whether a discrepancy exists,
  how to score an opportunity, or whether an alert is eligible. It writes the results of
  those evaluations.
- **Transform or enrich data.** The writer writes what it receives. It must not add, modify,
  or remove fields from the assembled result before writing.
- **Decide which records to write based on business logic.** Which records to write is
  determined by the result classification and the rules in Section 5 — not by evaluating the
  business content of the result.
- **Call external APIs or services.** The writer writes to the system of record. It does not
  call marketplace APIs, notification services, or any external system.
- **Send or schedule notifications.** Persistence of an `ALERT_ELIGIBLE` decision does not
  trigger notification delivery. That is a downstream concern outside this contract.
- **Implement retry logic for transient failures.** The writer reports failure classifications.
  The caller decides whether and when to retry. The writer must not contain its own retry loop.
- **Suppress audit record writes.** No failure in other record writes justifies skipping the
  audit record.
- **Silently swallow write failures.** Every write failure must be surfaced in the method
  return value, the audit record, and the `persist_execution` outcome.
- **Use AI models at runtime.** No AI model may be invoked within the writer for any purpose.
- **Generate timestamps from the system clock for business records.** All business-record
  timestamps must originate from the assembled pipeline result. The sole exception is
  `audit_written_at`.
- **Write partial records.** A record must be written completely or not at all. A partially
  written record is a writer defect.
- **Batch writes across pipeline executions.** Each `persist_execution` call handles exactly
  one `pipeline_execution_id`. The writer must not merge, batch, or correlate records from
  different executions.
- **Delete or overwrite finalized records.** A finalized pipeline result must not be deleted
  or overwritten. An audit record must not be modified or deleted after being written.
- **Choose a storage technology or access pattern.** This contract defines the interface. It
  does not choose raw SQL, an ORM, a connection pool, or a transaction management strategy.
  Those are implementation decisions.

---

## 14. Success Criteria

The persistence writer is successful when:

1. Every pipeline execution — regardless of result classification — produces a persisted
   pipeline result record and a persisted audit record via the writer.
2. `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT` results produce a persisted
   opportunity record via `persist_opportunity`.
3. Pipeline executions that reached Stage 4 produce a persisted alert decision record via
   `persist_alert_decision`.
4. `persist_pipeline_result` returns `ALREADY_EXISTS` when a finalized record already exists,
   without modifying the existing row.
5. `persist_pipeline_result` returns `UPDATED` when superseding a `PROCESSING_FAILURE` record
   with a new result.
6. `persist_opportunity` and `persist_alert_decision` return `ALREADY_EXISTS` when duplicate
   rows are detected, without modifying existing rows.
7. `persist_audit_record` always inserts a new row, accumulating records across retries.
8. A failure in `persist_pipeline_result` does not prevent `persist_audit_record` from being
   attempted.
9. A failure in `persist_opportunity` or `persist_alert_decision` does not prevent
   `persist_audit_record` from being attempted.
10. The audit record's `persistence_outcome` and `persistence_failure_detail` accurately
    reflect the outcome of all preceding writes.
11. `persist_execution` returns the correct outcome classification (`ALL_WRITES_SUCCEEDED`,
    `PARTIAL_WRITE_FAILURE`, `RESULT_WRITE_FAILED`, `AUDIT_WRITE_FAILED`, `TOTAL_FAILURE`)
    for every scenario.
12. No opportunity record is written for `VALIDATION_FAILURE`, `PRECONDITION_FAILURE`,
    `NO_OPPORTUNITY`, `NO_OP`, or `PROCESSING_FAILURE` results.
13. No alert decision record is written for pipeline executions that did not reach Stage 4.
14. Every write failure is reflected in the individual method return value, the audit record
    (if the audit write succeeds), and the `persist_execution` outcome.
15. No field value is computed, derived, or transformed by the writer.
16. No business-record timestamp is derived from the system clock.
17. No identifier is generated or replaced by the writer.
18. All writer methods are independently testable with deterministic inputs.
19. The writer runs fully in a local development environment without production credentials
    or infrastructure.

---

## 15. Non-Acceptance Conditions

The persistence writer is not acceptable if any of the following are true:

- A pipeline execution completes without the writer attempting to persist a pipeline result
  record.
- A pipeline execution completes without the writer attempting to persist an audit record.
- An `OPPORTUNITY_DETECTED` or `OPPORTUNITY_SCORED_NO_ALERT` result has no corresponding
  `persist_opportunity` call.
- A pipeline execution that reached Stage 4 has no corresponding `persist_alert_decision`
  call.
- An opportunity record is written for a `VALIDATION_FAILURE`, `PRECONDITION_FAILURE`,
  `NO_OPPORTUNITY`, `NO_OP`, or `PROCESSING_FAILURE` result.
- An alert decision record is written for a pipeline execution that never reached Stage 4.
- A finalized pipeline result record is overwritten or deleted by the writer.
- A `PROCESSING_FAILURE` result record is not superseded when a successful retry occurs.
- An audit record is modified or deleted after being written.
- A write failure in `persist_pipeline_result`, `persist_opportunity`, or
  `persist_alert_decision` prevents `persist_audit_record` from being attempted.
- A write failure is not captured in the audit record's `persistence_outcome` and
  `persistence_failure_detail`.
- A write failure is not reflected in the `persist_execution` return value.
- `persist_execution` returns `ALL_WRITES_SUCCEEDED` when any required write failed.
- `persist_execution` returns a failure outcome when all required writes succeeded
  (including `ALREADY_EXISTS` results for duplicate writes).
- The writer computes, derives, or transforms any field value from the assembled result.
- The writer generates or replaces any identifier.
- The writer substitutes the system clock for any business-record timestamp.
- The writer writes a partial record (e.g., an opportunity record missing scoring factors).
- The writer evaluates business logic to decide what to write.
- The writer calls an external API or service.
- An AI model is invoked within the writer for any purpose.
- The writer implements its own retry loop for transient failures.
- The writer batches, merges, or correlates writes across different `pipeline_execution_id`
  values.
- Writer methods are not independently testable with deterministic inputs.
- Any of the five required methods (`persist_pipeline_result`, `persist_opportunity`,
  `persist_alert_decision`, `persist_audit_record`, `persist_execution`) is missing from
  the implementation.

Any of these conditions is a blocking defect.
The persistence writer must not be considered complete while any non-acceptance condition
is present.
