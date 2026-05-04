# AACE Execution Contract

## 1. Purpose

This document is the governing contract for the `aace-execution` project.

It defines how this project operates, what it is responsible for, what it is not allowed to do,
and how all code within it must behave.

This is an implementation project.
It does not define intent, business rules, or specifications.
It executes instructions that have already been defined in the AACE spec repository.

Every piece of logic in this project must be traceable to a directive, requirement,
or acceptance criterion in the spec repo.
If it cannot be traced, it does not belong here.

---

## 2. Relationship to Spec Repo (AACE)

This project is the execution layer described in:

- `directives/spec/06_architecture.md` — Three-Layer Operating Model, Layer 3
- `directives/spec/12_autonomous_execution_constraints.md` — Execution boundary rules
- `directives/spec/03_constraints.md` — Non-negotiable system constraints
- `execution/README.md` — Execution layer contract

The relationship is strictly one-directional:

```
AACE spec repo (Claude_Projects)
  └── defines rules, constraints, acceptance criteria, and domain logic
        └── aace-execution (this repo)
              └── implements those rules in deterministic Python code
```

This project must never redefine, override, or improvise business rules.
If a rule is unclear, implementation must stop and the spec must be updated first.

The spec repo is the source of truth.
This repo is the executor of that truth.

---

## 3. Execution Principles

All code in this project must conform to the following principles, in priority order:

### 3.1 Determinism
Given the same valid inputs and the same rule set, this project must produce the same outputs every time.
No random behavior, no environment-sensitive branching, no opaque decisions.

### 3.2 Explicit Validation
All inputs must be validated before any business logic executes.
Validation rules are defined in the spec. They are not invented here.
A missing field, a wrong type, or an out-of-range value must produce a structured rejection — not a silent skip.

### 3.3 No Hidden Logic
Every decision made in this codebase must be:
- traceable to a spec directive,
- expressed in explicit code,
- verifiable by a test.

There must be no logic that only works under certain runtime conditions, no behavior inferred from external state, and no decisions delegated to an AI model at runtime.

### 3.4 No Rule Ownership
This project does not own business rules.
It implements them.
Discrepancy thresholds, scoring weights, retry limits, and validation constraints all originate in the spec repo.
When those rules change in the spec, this project updates its implementation — not the other way around.

---

## 4. System Components

### 4.1 Jobs

Jobs are the scheduled entry points for automated execution.

A job:
- has one clearly defined responsibility,
- calls a pipeline or a discrete execution function,
- must not contain business logic of its own,
- must log its start time, end time, and outcome,
- must be idempotent,
- must surface failures as explicit exceptions.

Job schedules are defined in configuration. They are not hardcoded.

Examples of job responsibilities:
- trigger the ingestion pipeline for a configured data source,
- trigger the discrepancy detection pipeline for a set of observations,
- trigger the opportunity scoring pipeline for pending discrepancies.

### 4.2 Workers

Workers are the scheduling and dispatch layer responsible for invoking jobs.

A worker:
- does not contain business logic,
- is responsible for routing job execution,
- must be restart-safe,
- must handle duplicate job invocations gracefully,
- must remain observable through logs.

For the MVP, a lightweight scheduler is used.
A full message broker is deferred unless justified by a specific concurrency or retry requirement.

### 4.3 Validators

Validators enforce the input contracts defined in the spec before any pipeline stage processes data.

A validator:
- checks required fields,
- checks field types and value constraints,
- rejects malformed input with a structured, descriptive error,
- must be independently testable without I/O,
- must not apply business transformation — only structural and value validation.

Validation rules are derived from the spec.
No validation rule may be invented in this project.

### 4.4 Pipelines

Pipelines define the ordered sequence of execution stages for a given workflow.

A pipeline:
- chains validators, transformers, and persistence steps in a defined order,
- must not proceed past a stage if that stage fails,
- must produce an audit event at each significant stage boundary,
- must have a defined input contract at the start and a defined output contract at the end,
- must be independently runnable for testing without live infrastructure where possible.

The core MVP pipeline sequence is:

```
Input
  → validate
    → normalize
      → persist (product / listing / observation)
        → detect discrepancy
          → score opportunity
            → persist opportunity
              → record audit events
```

---

## 5. Execution Rules

The following rules apply to all code in this project without exception:

1. Every function that writes to persistent state must emit an audit event.
2. Every pipeline stage must receive a validated input before executing.
3. No stage may silently swallow an error and return a success result.
4. No external API call may be made without credential injection via environment variable.
5. No credential, token, API key, or secret may appear in committed code or configuration files.
6. All retry behavior must be explicit, bounded, and documented.
7. Transient failures and terminal failures must be distinguishable in code and in logs.
8. No job or pipeline may assume it is the only instance running unless explicitly enforced and documented.
9. Scheduling behavior must be defined in configuration, not logic.
10. No pipeline stage may call another pipeline stage directly in a way that creates hidden coupling.

---

## 6. Input / Output Contracts

### Input Rules

- Inputs must be validated at the earliest possible stage.
- Required fields must be checked explicitly against the spec's field definitions.
- Type mismatches must be rejected, not coerced silently.
- Inputs must never be passed directly to database queries or external calls without validation.
- Raw source payloads may be retained for audit purposes but must not become the operational data model.

### Output Rules

- Outputs that affect business state must be persisted to the system of record.
- Scored opportunity outputs must include the factors used to produce the score.
- Discrepancy outputs must include the rule applied, the input values compared, and the result.
- Derived values must be distinguishable from source data in the output model.
- Outputs must not be returned before validation and persistence are confirmed.
- Partial outputs from failed pipeline runs must not be treated as complete.

---

## 7. Failure Handling

All failure handling in this project must be explicit and intentional.

### Transient Failures
Examples: network timeouts, temporary unavailability of a data source.

- Must be identified as retriable at the point of failure.
- Retry count must be bounded.
- Each retry attempt must be logged.
- After the retry limit is exceeded, the failure must be escalated, not silently dropped.

### Terminal Failures
Examples: invalid input, violated business constraint, missing required configuration.

- Must be immediately surfaced as an explicit exception.
- Must not be retried.
- Must produce an audit record.
- Must include enough context to diagnose the cause without access to external systems.

### Partial Failures
- A pipeline that fails mid-run must not produce a partial success result.
- Any state written before the failure must be either rolled back or flagged as incomplete.
- The audit record must reflect what was completed and where the failure occurred.

---

## 8. Idempotency Rules

Every job and pipeline in this project must be safe to rerun.

Idempotency rules:

1. Rerunning a job on the same input must not create duplicate opportunity records.
2. Rerunning ingestion for the same product/listing data must not create duplicate entity records.
3. Rerunning discrepancy detection on the same observation set must not create duplicate discrepancy records.
4. Rerunning scoring on the same discrepancy must not create duplicate scored opportunities.
5. Each script must have explicit deduplication logic or use unique constraint enforcement at the persistence layer.
6. Idempotency behavior must be tested: rerun tests must assert that record counts remain stable.

---

## 9. Logging and Traceability

### Logging Rules

- Every job must log: start time, input summary, outcome, and end time.
- Every pipeline stage must log: stage name, input identity, and outcome.
- Every failure must log: error type, failure context, and whether it is retriable.
- Logs must be structured and machine-readable where possible.
- Logs must never include: secrets, tokens, passwords, full credential payloads, or unnecessary personal data.

### Traceability Rules

- Every opportunity output must be traceable to its source observations, the discrepancy rule applied, and the scoring factors used.
- Every audit event must include: entity reference, event type, timestamp, and relevant context.
- Audit records must be persisted to the system of record, not only to log files.
- A reviewer with no prior context must be able to follow one opportunity from source input to final output using code, audit records, and logs alone.

---

## 10. What Is NOT Allowed

The following are explicitly forbidden in this project:

- **Redefining business rules.** Discrepancy thresholds, scoring logic, validation rules, and retry limits are owned by the spec repo. They must not be changed here without a corresponding spec update.
- **AI runtime decision-making.** No AI model may be called at runtime to determine whether a discrepancy exists, how to score an opportunity, or what validation to apply. These are deterministic code decisions.
- **Silent failures.** Any failure that affects business state must surface explicitly.
- **Hardcoded credentials.** No secret of any kind may be committed to this repository.
- **Scope creep.** Features not described in the spec may not be introduced here.
- **Untested logic.** No discrepancy, scoring, or validation logic may be shipped without unit tests.
- **Mixed responsibilities.** Jobs must not contain pipeline logic. Validators must not contain transformation logic. Pipelines must not contain scheduling logic.
- **Direct database access from jobs.** Jobs call pipelines. Pipelines call persistence functions. Jobs must not write to the database directly.
- **Production system access during tests.** Test runs must never touch live marketplace APIs or production databases.
- **Opaque state transitions.** If the system changes business-significant state, that change must be observable, attributable, and logged.

---

## 11. First Execution Goal — Opportunity Pipeline

The first concrete goal of this project is to implement the core opportunity pipeline end-to-end.

This pipeline must prove that the execution layer can:

1. Accept a structured product input, validate it, normalize it, and persist a product record.
2. Accept a structured listing input, validate it, and persist a listing record linked to that product.
3. Record a price observation for a listing with a timestamp and source reference.
4. Compare two or more observations for the same product and evaluate at least one explicit discrepancy rule.
5. Produce a scored opportunity from a valid discrepancy, including the explanation factors.
6. Persist the opportunity to the system of record.
7. Write audit events for each stage of the pipeline.

This pipeline must be fully testable before any background job scheduling is wired up.

**The pipeline is not complete until:**
- all stages have passing unit tests,
- idempotency is verified by rerun tests,
- at least one failure path is tested per stage,
- all outputs are traceable to their inputs via code and audit records.

---

## 12. Success Criteria

This project is successful when:

1. The full opportunity pipeline runs without error on valid input.
2. Invalid inputs are rejected at the earliest stage with a structured error.
3. Opportunity outputs include the discrepancy rule applied and all scoring factors.
4. Audit records exist for every pipeline stage that affects business state.
5. Rerunning any job or pipeline on the same input does not produce duplicate records.
6. All execution logic has unit test coverage for happy path, edge case, and failure path.
7. No secrets appear in committed code or configuration.
8. A reviewer unfamiliar with this codebase can trace any opportunity from input to output using code, logs, and audit records alone.
9. All implemented logic can be mapped back to a directive or acceptance criterion in the AACE spec repo.
10. The project runs fully in a local development environment without production-scale infrastructure.
