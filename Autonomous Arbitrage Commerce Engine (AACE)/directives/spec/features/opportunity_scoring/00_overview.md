# Opportunity Scoring Feature Overview

## 1. Purpose

This document defines the purpose and scope of the Opportunity Scoring feature in the AACE MVP.

Opportunity Scoring transforms detected price discrepancies into prioritized, reviewable opportunities.

It assigns a deterministic score to each discrepancy based on explicit factors, enabling users to identify which opportunities are most valuable.

This feature does not execute trades or automate decisions.
It provides structured, explainable prioritization.

---

## 2. Feature Objective

The Opportunity Scoring feature must:

- consume valid discrepancy results,
- evaluate each discrepancy using explicit scoring rules,
- assign a deterministic score,
- preserve scoring factors for explanation,
- produce ranked opportunity outputs.

The goal is prioritization, not prediction.

---

## 3. Why This Feature Exists

Not all discrepancies are equal.

Some are:

- too small to matter
- too risky
- not actionable

This feature ensures:

- high-value opportunities rise to the top
- low-value signals are deprioritized
- users can focus on what matters

Without scoring, the system produces noise.

---

## 4. MVP Scope

The feature must support:

- deterministic scoring
- simple scoring factors
- explainable score outputs
- ranking or prioritization
- compatibility with discrepancy inputs

---

## 5. Inputs

The feature consumes:

- discrepancy results
- price difference data
- product and listing context
- timestamps
- rule-based scoring configuration

Inputs must be:

- validated
- deterministic
- traceable

---

## 6. Outputs

The feature produces opportunity objects that include:

- opportunity id
- associated discrepancy
- score value
- contributing factors
- timestamps
- status (active, reviewed, dismissed)

Outputs must be structured and consistent.

---

## 7. Feature Boundaries

### In Scope
- scoring discrepancies
- ranking opportunities
- preserving scoring context
- enabling review

### Out of Scope
- executing trades
- predicting future prices
- AI-only scoring decisions
- automated buying/selling

---

## 8. Determinism Requirement

The scoring system must be deterministic.

Given the same inputs:

- same discrepancy
- same rules

→ must produce the same score

---

## 9. Explainability Requirement

Each score must be explainable.

The system must answer:

- why this score was assigned
- what factors contributed
- how it compares to others

---

## 10. Relationship to Other Features

Depends on:
- Price Monitoring (discrepancies)

Feeds into:
- Opportunity Review
- Reporting
- Decision-making workflows

---

## 11. Operational Model

Scoring may occur:

- immediately after discrepancy detection
- in batch processing
- on-demand

Behavior must remain:

- deterministic
- traceable
- testable

---

## 12. Risk Areas

- overcomplicated scoring
- unexplainable scores
- inconsistent ranking
- hidden weighting logic

---

## 13. Success Condition

The feature is successful if:

- discrepancies are scored correctly
- scores are deterministic
- outputs are explainable
- opportunities can be ranked
- results are testable

---

## 14. Future Expansion (Not MVP)

- advanced weighting models
- ML-assisted scoring
- risk-adjusted scoring
- user-specific preferences

---

## 15. Open Questions

- what scoring factors should MVP include?
- should score be normalized (0–100)?
- should time/freshness impact score?