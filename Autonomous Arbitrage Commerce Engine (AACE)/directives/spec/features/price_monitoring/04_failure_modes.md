# Price Monitoring Failure Modes

## 1. Purpose

This document defines the expected failure modes and failure-handling behavior for the Price Monitoring feature in the AACE MVP.

Its purpose is to ensure that the feature fails safely, predictably, and traceably when required inputs are missing, invalid, stale, or otherwise unusable.

This feature must not fail silently.
It must not guess when required comparison conditions are not met.
It must distinguish between:

- valid non-discrepancy results,
- skipped evaluations,
- invalid evaluation attempts,
- system or processing failures.

---

## 2. Failure-Handling Principles

The Price Monitoring feature must follow these principles:

1. fail safely,
2. fail explicitly,
3. preserve traceability,
4. avoid false positives,
5. avoid silent suppression of critical problems,
6. never turn invalid input into a misleading discrepancy result.

When a failure occurs, the system must prefer no discrepancy output over an incorrect discrepancy output.

---

## 3. Failure Categories

Failure modes for this feature are grouped into four categories:

1. input validation failures,
2. comparison eligibility failures,
3. rule evaluation failures,
4. operational or processing failures.

Each category must have explicit behavior.

---

## 4. Input Validation Failures

These failures occur before valid comparison can begin.

Examples include:

- missing product reference,
- missing listing reference,
- missing observed price,
- invalid price type,
- invalid or unsupported currency value,
- malformed timestamp,
- missing source identity.

### Required Behavior

When an input validation failure occurs:

- the invalid comparison candidate must not be evaluated,
- no discrepancy should be generated from that invalid candidate,
- the failure should be logged or recorded in a traceable way,
- the system should distinguish invalid input from valid no-discrepancy outcomes.

### Forbidden Behavior

The system must not:

- coerce invalid values silently into business truth,
- infer missing required fields,
- continue comparison using partially invalid core input.

---

## 5. Comparison Eligibility Failures

These failures occur when input records exist but should not be compared.

Examples include:

- listings belong to different products,
- fewer than two eligible price-bearing records exist,
- source pairing is not allowed by rule,
- duplicate listing pair selected,
- currency mismatch exists without approved normalization,
- observation freshness policy excludes one or more observations.

### Required Behavior

When a comparison eligibility failure occurs:

- the comparison must be skipped,
- no discrepancy must be emitted,
- the reason for the skip should be traceable,
- the system should not classify this as a discrepancy miss if evaluation was not actually valid.

### Important Distinction

A skipped comparison is not the same as a no-discrepancy comparison.

The system should preserve the difference between:

- comparison was valid and found no discrepancy,
- comparison was not valid and therefore not evaluated.

---

## 6. Rule Evaluation Failures

These failures occur after a comparison is eligible but rule execution cannot complete correctly.

Examples include:

- threshold configuration missing,
- invalid threshold configuration,
- division-by-zero risk in percentage-based comparison,
- unsupported comparison mode selected,
- rule dependency missing,
- inconsistency between configured rule and available data.

### Required Behavior

When a rule evaluation failure occurs:

- the discrepancy evaluation must fail safely,
- no discrepancy should be created,
- the evaluation failure must be recorded,
- the system must not substitute guessed thresholds or fallback heuristics unless explicitly defined.

### Forbidden Behavior

The system must not:

- default silently to a different threshold type,
- fabricate a discrepancy result without a valid rule basis,
- swallow rule errors without traceability.

---

## 7. Operational or Processing Failures

These failures occur because the feature cannot complete due to system-level or runtime conditions.

Examples include:

- database access failure,
- retrieval failure for required observations,
- timeout during evaluation batch processing,
- write failure when persisting discrepancy results,
- internal application error during evaluation.

### Required Behavior

When an operational failure occurs:

- the feature must fail visibly,
- the failure must be logged or recorded,
- partial ambiguous outcomes should be avoided where possible,
- users must not receive misleading “success” responses.

### Recovery Principle

Operational failures may be retried only if retry behavior is explicitly supported and safe.

Retries must not cause duplicate discrepancy outputs unless duplicate prevention rules are in place.

---

## 8. No Discrepancy Is Not a Failure

The system must clearly distinguish valid “no discrepancy found” outcomes from failures.

A valid no-discrepancy outcome occurs when:

- the input is valid,
- the comparison is eligible,
- the rule evaluation runs successfully,
- the difference does not exceed threshold.

This is a successful evaluation result, not an error condition.

---

## 9. Failure Classification Model

Each failed or skipped evaluation should be classifiable into one of the following statuses:

- `INVALID_INPUT`
- `INELIGIBLE_COMPARISON`
- `RULE_EVALUATION_FAILED`
- `PROCESSING_FAILED`
- `NO_DISCREPANCY`
- `DISCREPANCY_FOUND`

The exact status labels may vary, but the meaning must remain consistent.

The system must not collapse all non-success outcomes into a single generic error state.

---

## 10. Logging and Traceability Requirements

When failures occur, the system should preserve enough context to support debugging and audit.

At minimum, failure traces should preserve:

- product reference if available,
- listing or observation references if available,
- failure category,
- failure reason,
- evaluation timestamp,
- rule context if relevant.

### Security Constraint

Failure logging must not expose sensitive credentials, secrets, or unsafe internal data.

---

## 11. Duplicate Prevention During Failure Handling

The system must prevent failure recovery behavior from creating duplicate discrepancy outputs.

Examples of failure-sensitive duplicate risks include:

- retrying evaluation after partial write success,
- replaying the same comparison without idempotent safeguards,
- emitting both `A vs B` and `B vs A` as separate discrepancy outputs.

Failure handling must not weaken duplicate-control guarantees.

---

## 12. Freshness-Related Failure Modes

If freshness rules are enabled, the system must handle freshness-specific failures explicitly.

Examples include:

- observation too old to compare,
- missing observation timestamp,
- inconsistent freshness windows across evaluated records.

### Required Behavior

When freshness rules invalidate a comparison:

- the comparison should be skipped or marked ineligible,
- the result must not be treated as a discrepancy,
- the reason should be traceable.

---

## 13. Currency and Normalization Failure Modes

The feature must handle normalization-related failures safely.

Examples include:

- unsupported currency,
- missing currency value,
- normalization required but unavailable,
- price values present but not safely comparable.

### Required Behavior

When currency or normalization conditions are invalid:

- comparison must not proceed,
- the system must not guess conversions,
- the event must be traceable.

---

## 14. Batch Processing Failure Modes

If the feature evaluates multiple products or comparisons in a batch, it must define safe batch-failure behavior.

### Required MVP Behavior

The system should prefer bounded failure isolation.

This means:

- one failed comparison should not necessarily invalidate every unrelated valid comparison,
- failures should be attributable to the affected evaluation unit,
- batch summary outcomes should distinguish full success, partial success, and failure.

### Forbidden Behavior

The system must not report full success when substantial evaluation units failed.

---

## 15. User-Facing Failure Behavior

If discrepancy evaluation results are exposed through API or UI, the user-facing layer must behave safely.

### Required Behavior

User-visible behavior should:

- avoid exposing sensitive internal error details,
- distinguish between “no results found” and “evaluation failed” where appropriate,
- provide stable, safe error messaging,
- preserve internal debugging details in logs rather than public responses.

### Forbidden Behavior

The system must not:

- leak stack traces,
- leak database internals,
- leak secrets or environment values,
- present invalid evaluation as valid success.

---

## 16. Retry Behavior

If retry behavior is implemented for this feature, it must be controlled and explicit.

### Retry Rules

Retries may be appropriate only for failures such as:

- transient database connectivity issues,
- temporary processing timeouts,
- temporary dependency availability issues.

Retries are not appropriate for:

- invalid input,
- ineligible comparisons,
- missing rule configuration,
- unsupported data normalization conditions.

### Retry Safety

Retries must:

- be traceable,
- avoid duplicate result creation,
- preserve deterministic behavior.

---

## 17. Failure Acceptance Criteria

Failure handling for this feature is acceptable only if:

1. invalid data does not generate discrepancies,
2. ineligible comparisons are skipped safely,
3. rule failures do not create guessed outputs,
4. operational failures are visible and traceable,
5. valid no-discrepancy results remain distinct from failure states,
6. retries, if supported, do not create duplicate outputs,
7. user-facing responses remain safe.

---

## 18. Non-Acceptance Conditions

Failure handling for this feature must be rejected if any of the following occur:

- invalid input produces a discrepancy,
- unrelated products are compared,
- rule failures silently fall back to guessed behavior,
- operational failures are hidden,
- duplicate discrepancies are created through retry or replay,
- user-facing responses expose unsafe internal details,
- no-discrepancy outcomes are indistinguishable from failures.

---

## 19. Example Failure Scenarios

### Scenario A — Missing Price
- listing exists
- observed price is missing

Expected behavior:
- evaluation skipped or rejected as invalid
- no discrepancy created
- failure reason traceable

### Scenario B — Below Threshold
- product comparison valid
- price difference is below configured threshold

Expected behavior:
- evaluation succeeds
- no discrepancy created
- result classified as valid no-discrepancy

### Scenario C — Currency Mismatch
- product comparison valid
- one listing in USD
- one listing in unsupported currency
- no approved normalization rule exists

Expected behavior:
- comparison marked ineligible or failed by normalization rule
- no discrepancy created
- reason traceable

### Scenario D — Transient Write Failure
- valid discrepancy found
- persistence of result fails temporarily

Expected behavior:
- failure visible
- retry only if explicitly supported
- no duplicate discrepancy created during recovery

---

## 20. Open Questions

- Which failure categories should be persisted versus only logged?
- Should skipped comparisons be queryable in the MVP, or only traceable in logs/audit records?
- What retry policy, if any, should the first MVP support for transient operational failures?
- Should freshness failures and normalization failures use separate status codes in the first implementation?