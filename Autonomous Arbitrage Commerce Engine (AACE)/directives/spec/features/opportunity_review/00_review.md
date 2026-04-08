# Opportunity Review Feature Overview

## 1. Purpose

This document defines the purpose and scope of the Opportunity Review feature in the AACE MVP.

Opportunity Review allows authorized users to:

- view scored opportunities
- understand discrepancy details
- evaluate opportunity quality
- take controlled actions (e.g., mark reviewed or dismissed)

This feature is the primary interface between the system and the user.

---

## 2. Feature Objective

The Opportunity Review feature must:

- present scored opportunities
- display discrepancy context
- show scoring breakdown
- allow status updates
- enforce access control

The goal is usability and decision support.

---

## 3. Why This Feature Exists

Without this feature:

- users cannot see results
- scoring has no impact
- system has no practical value

This feature converts system outputs into actionable insights.

---

## 4. MVP Scope

The feature must support:

- viewing opportunities
- viewing score and discrepancy details
- filtering and sorting opportunities
- updating opportunity status
- role-based access control

---

## 5. Inputs

The feature consumes:

- scored opportunities
- discrepancy data
- product and listing data
- scoring factors
- user authentication context

---

## 6. Outputs

The feature presents:

- opportunity list
- opportunity detail view
- score and ranking
- discrepancy explanation
- status (active, reviewed, dismissed)

---

## 7. Feature Boundaries

### In Scope
- viewing opportunities
- reviewing details
- updating status
- filtering and sorting

### Out of Scope
- executing trades
- automated actions
- AI recommendations
- marketplace integration

---

## 8. Access Control

The feature must enforce:

- authentication required
- role-based access

### Roles:
- admin → full access
- manager → review access
- user → limited access

---

## 9. Explainability Requirement

Each opportunity must clearly show:

- what was compared
- price difference
- score
- why it was ranked

---

## 10. Determinism Requirement

The feature must display:

- consistent ordering
- consistent scoring
- stable results

---

## 11. Relationship to Other Features

Depends on:
- Price Monitoring
- Opportunity Scoring

Feeds into:
- Reporting
- Decision workflows

---

## 12. Operational Model

The feature may be:

- API-based
- UI-based
- or both

Must remain:

- secure
- consistent
- testable

---

## 13. Risk Areas

- confusing UI structure
- missing explanation
- inconsistent ranking
- unauthorized access

---

## 14. Success Condition

The feature is successful if:

- users can view opportunities
- data is clear and explainable
- ranking is visible
- access is controlled
- actions are possible

---

## 15. Future Expansion (Not MVP)

- advanced filtering
- alerts/notifications
- bulk actions
- personalization

---

## 16. Open Questions

- API-first or UI-first?
- what filters are required?
- what status transitions are allowed?