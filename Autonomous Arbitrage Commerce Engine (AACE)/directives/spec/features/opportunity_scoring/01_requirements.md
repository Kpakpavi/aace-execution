# Opportunity Scoring Requirements

## 1. Purpose

This document defines the requirements for the Opportunity Scoring feature.

It specifies how discrepancies are evaluated and converted into prioritized opportunities using deterministic scoring rules.

This document defines required behavior, not implementation details.

---

## 2. Feature Goal

The feature must:

- consume discrepancy results
- calculate a score for each discrepancy
- rank opportunities based on score
- preserve scoring factors for explanation
- produce deterministic outputs

The goal is prioritization based on value.

---

## 3. Input Requirements

The feature must accept:

- valid discrepancy result
- price difference data
- product context
- listing/source context
- timestamps

### Required Conditions

Scoring must NOT occur unless:

- discrepancy is valid
- required fields are present
- discrepancy passed threshold rules

---

## 4. Core Scoring Factors

The MVP must use simple, deterministic factors.

### 4.1 Price Difference (Primary Factor)

Must include:

- absolute difference
- or percentage difference

Higher difference → higher score

---

### 4.2 Relative Value (Optional MVP Factor)

May consider:

- relative percentage difference
- normalized comparison across products

---

### 4.3 Freshness (Optional MVP Factor)

May include:

- recency of observation
- newer data → higher score

---

## 5. Scoring Model

The system must:

- compute score using explicit formula
- use consistent weighting
- avoid hidden adjustments

### Example (illustrative only)

- score = base_value + (weight_1 * price_difference)

Final formula must be:

- deterministic
- documented
- testable

---

## 6. Score Range

The system should define a consistent range.

Example:
- 0 to 100

Rules:

- higher score = better opportunity
- same input → same score

---

## 7. Ranking Requirements

The system must:

- rank opportunities by score
- ensure consistent ordering
- handle equal scores predictably

---

## 8. Output Requirements

Each opportunity must include:

- opportunity_id
- discrepancy_reference
- score
- contributing factors
- timestamps
- status

---

## 9. Explainability

Each score must explain:

- how score was calculated
- what factors contributed
- why it ranks higher/lower

---

## 10. Determinism

The system must:

- produce same score for same input
- avoid randomness
- avoid hidden logic

---

## 11. Downstream Compatibility

The output must support:

- UI display
- reporting
- user review
- status updates

---

## 12. Failure Handling

The system must:

- reject invalid discrepancies
- avoid scoring incomplete data
- log scoring failures
- not produce partial scores

---

## 13. Constraints

The system must NOT:

- use AI to determine scores
- use hidden weights
- infer missing data
- produce non-explainable scores

---

## 14. Minimum Requirements

The feature is valid if:

- discrepancies are scored
- scores are deterministic
- ranking works
- results are explainable
- outputs are structured

---

## 15. Open Questions

- should score be normalized?
- what weights should be used?
- should freshness be included in MVP?