# AACE MVP Evaluation Plan

## 1. Purpose

This document defines how the AACE MVP will be evaluated.

It translates acceptance criteria into concrete validation methods.

The goal is to ensure that:

- the system behaves correctly,
- outputs are trustworthy,
- failures are understood,
- results are repeatable.

No feature is considered complete unless it can be evaluated using this plan.

---

## 2. Evaluation Philosophy

Evaluation must be:

- deterministic where required,
- reproducible,
- observable,
- aligned with acceptance criteria,
- structured across multiple levels.

Evaluation must cover:

- happy paths,
- edge cases,
- failure scenarios,
- retry behavior (where applicable).

The system must be testable without relying on intuition or manual guesswork.

---

## 3. Evaluation Levels

The MVP must be evaluated at three levels:

### 3.1 Unit Evaluation

Focus:
- individual functions or logic units

Examples:
- discrepancy calculation
- scoring logic
- input validation

Requirement:
- deterministic outputs
- isolated testing

---

### 3.2 Integration Evaluation

Focus:
- interaction between components

Examples:
- ingestion → storage
- auth → protected route
- discrepancy → scoring

Requirement:
- correct data flow
- correct interaction behavior

---

### 3.3 End-to-End Evaluation

Focus:
- full system behavior

Examples:
- user login → data ingestion → discrepancy → scoring → output

Requirement:
- complete workflow validation
- observable outputs
- traceable steps

---

## 4. Core Evaluation Scenarios

## 4.1 Happy Path

The system must pass:

1. user authenticates successfully
2. valid product/listing data is ingested
3. price observations are recorded
4. discrepancy is detected
5. opportunity is scored
6. user can view opportunity
7. system explains the result

---

## 4.2 Edge Cases

The system must handle:

- minimal price differences (below threshold)
- missing optional fields
- duplicate product entries
- multiple listings for same product
- inconsistent source formatting (handled or rejected safely)

---

## 4.3 Failure Scenarios

The system must handle:

- invalid input data
- authentication failure
- missing required fields
- malformed payloads
- incomplete ingestion

Requirements:
- no crashes
- clear error signaling
- traceable failure logs

---

## 4.4 Retry Behavior (Where Applicable)

If retry logic exists, system must:

- distinguish retriable vs non-retriable errors
- avoid duplicate side effects
- preserve consistency

---

## 5. Determinism Validation

The system must prove:

1. same input → same output
2. discrepancy logic is repeatable
3. scoring logic is repeatable
4. access decisions are consistent

Tests must explicitly verify this behavior.

---

## 6. Explainability Validation

The system must prove:

- every opportunity can be explained
- scoring factors are visible
- discrepancy reasoning is clear

Evaluation must include:

- verifying explanation fields exist
- verifying explanations match logic

---

## 7. Security Evaluation

The system must prove:

- unauthorized access is blocked
- role restrictions are enforced
- protected routes require authentication
- no sensitive data is exposed

---

## 8. Auditability Evaluation

The system must prove:

- events are recorded
- timestamps exist
- actions are traceable
- evaluation steps can be reconstructed

---

## 9. Data Integrity Validation

The system must prove:

- product/listing relationships are correct
- no orphan records exist
- ingestion produces valid normalized data
- stored data matches evaluated data

---

## 10. Performance Sanity Checks

The MVP must validate:

- reasonable response time for core flows
- no extreme inefficiencies
- evaluation completes within acceptable bounds

This is not optimization, but sanity validation.

---

## 11. Test Coverage Requirements

The MVP must include:

### Unit Tests
- discrepancy logic
- scoring logic
- validation rules

### Integration Tests
- ingestion pipeline
- authentication
- evaluation pipeline

### End-to-End Tests
- full system flow

---

## 12. Minimum Dataset for Evaluation

The system must be tested with:

- at least one product with multiple listings
- at least one valid discrepancy case
- at least one non-discrepancy case
- at least one invalid input case

---

## 13. Evaluation Outputs

Evaluation must produce:

- pass/fail results
- logs or traces
- test outputs
- explanation verification

Evaluation results must be reviewable.

---

## 14. Failure Acceptance Rules

The system fails evaluation if:

- outputs are inconsistent
- behavior is not repeatable
- access control fails
- discrepancies cannot be explained
- logs are missing or unusable

---

## 15. Evaluation Gate

The MVP is considered valid only if:

- all core flows pass
- all critical tests pass
- no major constraint violations exist
- outputs are explainable
- behavior is deterministic

---

## 16. Continuous Evaluation Principle

Evaluation is not a one-time step.

Every change must:

- preserve existing behavior
- pass relevant tests
- not introduce regressions

---

## 17. Open Questions

- What is the minimum acceptable dataset size for reliable validation?
- Which edge cases must be mandatory for first release?
- How will evaluation results be surfaced (logs vs dashboard)?