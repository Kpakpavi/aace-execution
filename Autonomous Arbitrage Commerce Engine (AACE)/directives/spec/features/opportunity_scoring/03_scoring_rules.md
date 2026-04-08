# Opportunity Scoring Rules

## 1. Purpose

This document defines the deterministic rules used to calculate opportunity scores in the AACE MVP.

These rules determine:

- how discrepancies are scored
- what makes one opportunity better than another
- how opportunities are ranked

All rules must be:

- explicit
- deterministic
- explainable
- testable

---

## 2. Scoring Philosophy

Scoring must prioritize:

- real value over noise
- simplicity over complexity
- explainability over sophistication

The system must avoid:

- black-box scoring
- hidden weights
- unpredictable ranking

---

## 3. Base Scoring Model

Each opportunity score must be calculated using a deterministic formula.

### General Form

score = f(discrepancy_inputs, scoring_factors)

The function must be:

- consistent
- documented
- repeatable

---

## 4. Required Scoring Factors (MVP)

### 4.1 Price Difference (Primary Factor)

This is the core factor.

Must use one or both:

#### Absolute Difference

abs_diff = |price_a - price_b|

#### Percentage Difference

pct_diff = (|price_a - price_b| / min(price_a, price_b)) * 100

Higher difference → higher score

---

## 5. Optional Scoring Factors (MVP)

These may be included if explicitly defined.

### 5.1 Freshness Factor

More recent observations may increase score.

Example:
- recent data → higher confidence → higher score

---

### 5.2 Consistency Factor (Optional)

If multiple observations confirm discrepancy:

- higher confidence → higher score

---

## 6. Scoring Formula Requirements

The formula must:

- combine factors explicitly
- use fixed weights
- avoid hidden adjustments

### Example (Illustrative)

score = (weight_1 * normalized_diff) + (weight_2 * freshness_factor)

---

## 7. Normalization

If multiple factors are used, values may be normalized.

Example:
- scale values to 0–100 range

Rules:

- normalization must be deterministic
- normalization method must be consistent
- normalization must be documented

---

## 8. Weighting Rules

Each factor must have a defined weight.

Example:
- price difference → 80%
- freshness → 20%

Rules:

- weights must be explicit
- weights must not change dynamically
- weights must be consistent across runs

---

## 9. Score Range

The system should define a fixed range.

Example:
- 0 to 100

Rules:

- higher score = better opportunity
- score must not exceed defined range

---

## 10. Ranking Rules

Opportunities must be ranked by score.

### Requirements:

- highest score first
- stable ordering
- deterministic tie handling

---

## 11. Tie-Breaking Rules

If scores are equal, system must use deterministic tie-breakers.

Example priority:

1. higher absolute difference
2. more recent observation
3. lower product ID (stable fallback)

Tie-breaking must be:

- explicit
- consistent
- testable

---

## 12. Score Construction

Each score must include:

- score value
- contributing factors
- factor values
- weights used
- timestamp

---

## 13. Explainability Rules

Each opportunity must answer:

- what factors contributed?
- what weights were applied?
- how final score was computed?

---

## 14. Determinism Rules

The system must:

- produce identical scores for identical inputs
- avoid randomness
- avoid time-dependent hidden logic

---

## 15. Invalid Scoring Conditions

The system must NOT score if:

- discrepancy is invalid
- required inputs are missing
- price data is invalid
- rule configuration is missing

---

## 16. Noise Protection

The system must prevent:

- artificially high scores for low-value discrepancies
- inconsistent scoring across similar inputs
- score inflation due to missing normalization

---

## 17. Example Scenario

### Input

- price_a = 100
- price_b = 120
- threshold met

### Calculation

- abs_diff = 20
- pct_diff = 20%

### Output

- score = high (based on formula)
- ranked above smaller discrepancies

---

## 18. Low-Value Example

### Input

- price_a = 100
- price_b = 103

### Output

- score = low
- below higher opportunities

---

## 19. Completion Criteria

The scoring rules are complete if:

- scoring is deterministic
- ranking is consistent
- results are explainable
- outputs are testable
- rules are simple and clear

---

## 20. Non-Acceptance Conditions

The scoring system must be rejected if:

- scores change unpredictably
- weights are hidden
- outputs cannot be explained
- ranking is unstable
- invalid inputs produce scores

---

## 21. Open Questions

- should score be 0–100 or unbounded?
- what exact weights should MVP use?
- should freshness be included now or later?
- should consistency factor be included in MVP?