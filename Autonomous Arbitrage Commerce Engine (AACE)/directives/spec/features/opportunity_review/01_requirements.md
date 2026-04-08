# Opportunity Review Requirements

## 1. Purpose

This document defines the functional and non-functional requirements for the Opportunity Review feature.

It specifies how users interact with scored opportunities, including viewing, filtering, and updating opportunity status.

---

## 2. Feature Goal

The feature must:

- display opportunities
- show detailed information
- allow user actions
- enforce access control
- maintain deterministic behavior

---

## 3. Input Requirements

The feature must consume:

- scored opportunities
- discrepancy data
- product and listing context
- scoring factors
- user authentication context

### Required Conditions

The feature must NOT operate unless:

- user is authenticated
- opportunity data is valid
- access permissions are satisfied

---

## 4. Opportunity List View

The system must provide a list of opportunities.

Each item must include:

- opportunity_id
- score
- product reference
- summary of discrepancy
- status
- timestamp

### Requirements

- list must be sortable by score
- list must be deterministic
- list must not expose unauthorized data

---

## 5. Opportunity Detail View

The system must allow viewing detailed opportunity information.

Must include:

- full discrepancy data
- compared prices
- score breakdown
- contributing factors
- timestamps

---

## 6. Filtering Requirements

The system should support basic filtering.

### Minimum Filters

- score range
- status
- product

Rules:

- filters must be deterministic
- filters must not alter underlying data
- filters must be consistent across sessions

---

## 7. Sorting Requirements

The system must support sorting.

### Required Sorting

- by score (default)
- by timestamp

Rules:

- sorting must be stable
- sorting must be deterministic

---

## 8. Status Management

Users must be able to update opportunity status.

### Allowed Statuses

- active
- reviewed
- dismissed

### Rules

- only valid transitions allowed
- changes must be saved
- changes must be traceable

---

## 9. Access Control

The system must enforce role-based access.

### Rules

- authentication required
- role determines access level
- unauthorized access must be blocked

---

## 10. Explainability

Each opportunity must show:

- discrepancy explanation
- score explanation
- contributing factors

---

## 11. Determinism

The system must:

- display consistent results
- preserve ranking order
- avoid randomness

---

## 12. Output Requirements

The feature must produce:

- structured list response
- structured detail response
- consistent data format

---

## 13. Failure Handling

The system must:

- handle missing data safely
- not crash on invalid requests
- return safe error messages

---

## 14. Constraints

The system must NOT:

- expose sensitive data
- allow unauthorized actions
- modify scoring logic
- execute trades

---

## 15. Minimum Requirements

The feature is valid if:

- opportunities are viewable
- details are clear
- sorting works
- filtering works
- status updates work
- access control is enforced

---

## 16. Open Questions

- should pagination be included in MVP?
- what default filters should apply?
- should bulk actions be supported?