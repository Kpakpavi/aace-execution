# AACE MVP Reporting and Analytics

## 1. Purpose

This document defines the reporting and analytics requirements for the AACE MVP.

It specifies:

- what reports the system must produce,
- how report data is generated and structured,
- what analytics are in scope for the MVP,
- what is deferred to later phases.

Reporting is a core system output. Without reporting, users cannot understand system performance, opportunity trends, or alert history.

---

## 2. Reporting Principles

All reports must be:

- deterministic (same inputs produce same outputs),
- traceable (outputs can be connected back to underlying records),
- role-aware (users see only data they are authorized to access),
- read-only (reports must not modify system state),
- explainable (users should understand what each report shows).

---

## 3. MVP Reporting Scope

### In Scope

The MVP must support:

- opportunity summary reports,
- alert summary reports,
- price observation history,
- basic performance metrics (counts, averages, status distributions),
- time-bounded report queries.

### Out of Scope

The MVP does not include:

- custom report builders,
- user-defined report templates,
- business intelligence warehouse exports,
- predictive or trend-based analytics,
- automated report scheduling and delivery,
- third-party analytics integration.

---

## 4. Required Reports

### 4.1 Opportunity Summary Report

Must include:

- total opportunities detected in a given period,
- breakdown by status,
- average opportunity score,
- top-scoring opportunities,
- opportunities by marketplace (if applicable).

### 4.2 Alert Summary Report

Must include:

- total alerts generated in a given period,
- breakdown by alert type or priority,
- alert-to-opportunity mapping,
- unresolved alerts.

### 4.3 Price Observation Report

Must include:

- price observations by product and marketplace,
- price change history within a defined time window,
- discrepancy counts per product.

### 4.4 System Activity Summary

Must include:

- ingestion counts and outcomes,
- scoring run counts,
- detection run counts,
- error counts by type.

---

## 5. Report Data Model

Reports must be generated from persisted, structured data.

Reports must not:

- be generated from live API calls at query time,
- compute complex aggregations without a defined query or materialized view,
- include unverified or raw external data.

Report data must align with:

- the data model defined in 08_data_model.md,
- the accepted records from the ingestion and scoring pipelines.

---

## 6. Time Window Requirements

All reports must support filtering by a defined time window.

Minimum requirements:

- today,
- last 7 days,
- last 30 days,
- custom date range.

Default time window must be defined and documented.

---

## 7. Access Control

Reports must enforce role-based access control.

Rules:

- unauthenticated users cannot access any report,
- admin users can access all reports,
- manager and standard user roles may have restricted report access,
- reports must never return data outside a user's authorization scope.

---

## 8. Report Output Format

Reports must return structured data.

For the MVP, structured API responses or server-rendered views are acceptable.

Output must include:

- report metadata (time window, generation timestamp),
- report sections clearly labeled,
- counts and summaries as defined per report type.

---

## 9. Determinism Requirements

Reports must be deterministic.

The same query with the same parameters and the same underlying data must return the same result.

No randomness or hidden ranking is permitted in report outputs.

---

## 10. Performance Requirements

Reports must:

- return results within a reasonable time for MVP data volumes,
- not degrade system performance under normal usage,
- rely on indexed queries where possible.

Complex aggregations that cannot be computed efficiently must be documented as known limitations.

---

## 11. Audit Alignment

Report generation events must be traceable.

Key events to log:

- who generated a report,
- what parameters were used,
- when the report was generated.

---

## 12. Analytics Direction (Post-MVP)

The MVP reporting model is intended to evolve toward:

- trend analysis over time,
- opportunity performance tracking,
- user behavior analytics,
- export capabilities for external tools.

These are future concerns. The MVP must prove correctness and traceability before expanding analytics scope.

---

## 13. Failure Handling

If a report cannot be generated:

- the system must return a clear error response,
- the error must be logged,
- partial results must not be returned as complete reports.

---

## 14. Constraints

Reports must NOT:

- expose data outside a user's authorization scope,
- modify underlying system records,
- return inconsistent results for the same query,
- include sensitive user data beyond what is required for the report.

---

## 15. Open Questions

- Which reports are required on day one versus acceptable as fast follows?
- Should reports be cached or computed on demand for the MVP?
- What is the maximum acceptable query time for core reports?
- Which user roles should have access to which reports?
