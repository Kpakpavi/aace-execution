# AACE MVP Dashboard Specification

## 1. Purpose

This document defines the full specification for the Dashboard in the AACE MVP.

It is the authoritative reference for:

- what the dashboard must display,
- how it must behave,
- what access rules apply,
- what constitutes correct and accepted behavior.

This document consolidates and elevates the feature-level dashboard specs into a system-level specification.

---

## 2. Dashboard Goal

The dashboard is the primary user-facing operational surface of the AACE MVP.

Its goal is to allow a user to quickly understand:

- the current state of opportunity detection,
- recent alert activity,
- key system metrics,
- where to go for deeper review.

The dashboard does not replace detailed reports or review pages. It provides the high-level operating view.

---

## 3. Scope

### In Scope

- summary metrics (opportunities, alerts, scores, status distributions),
- recent opportunities section,
- recent alerts section,
- navigation to opportunity review and reports,
- role-aware display.

### Out of Scope

- custom dashboard configuration,
- real-time streaming updates,
- advanced analytics or trend charts,
- automated actions from the dashboard,
- business intelligence exports.

---

## 4. Dashboard Sections

### 4.1 Summary Metrics

Must display:

- total opportunities detected (with time window),
- average opportunity score,
- opportunities by status,
- total alerts generated (with time window).

Metrics must:

- reflect persisted report data,
- be accurate and consistent,
- be labeled with the time window they represent.

### 4.2 Recent Opportunities

Must display a list of recent opportunities.

Each item must include:

- opportunity_id,
- score,
- product reference,
- status,
- timestamp.

List must be ordered deterministically (by score or recency as defined).

### 4.3 Recent Alerts

Must display a list of recent alerts.

Each item must include:

- alert_id,
- opportunity reference,
- score,
- summary,
- timestamp.

List must not include duplicate alerts.

### 4.4 Navigation

Must provide clear links or navigation to:

- opportunity review,
- reporting views.

Navigation must respect role-based access control.

---

## 5. Access Control

The dashboard must enforce:

- authentication required for all dashboard views,
- role-based visibility of content,
- restricted data not visible to unauthorized roles,
- rejected access for unauthenticated or unauthorized requests.

---

## 6. Behavioral Requirements

- Dashboard must be read-only. No data mutations may occur during render.
- Dashboard must be deterministic. Same data and same user role must produce the same output.
- Dashboard must be explainable. Each metric must have a clear label and time context.
- Dashboard must fail safely. Partial failures must not crash the dashboard. Missing data must show a clean empty state.

---

## 7. Data Sources

The dashboard consumes:

- opportunity records from the scoring pipeline,
- alert records from the alert generation pipeline,
- report aggregates from the reporting layer,
- user authentication and role context.

Dashboard must not derive its own business logic. It must display what the system has already computed.

---

## 8. Time Window

The default time window for the dashboard must be defined.

All sections must use the same default time window unless explicitly differentiated.

The time window must be visible to the user.

---

## 9. Performance

The dashboard must:

- load within acceptable time for MVP data volumes,
- rely on pre-computed report data where possible,
- avoid heavy real-time computations at render time.

---

## 10. Relationship to Feature Specs

This document governs at the system level.

Feature-level detail is defined in:

- `features/dashboard/00_overview.md`
- `features/dashboard/01_requirements.md`
- `features/dashboard/02_acceptance_criteria.md`
- `features/dashboard/03_widgets_and_views.md`

In case of conflict, the feature-level acceptance criteria takes precedence for implementation decisions.

---

## 11. Acceptance Summary

The dashboard is accepted when:

- metrics are accurate,
- recent opportunities and alerts display correctly,
- role-based access is enforced,
- behavior is deterministic,
- failures are handled safely,
- outputs are structured and explainable.

---

## 12. Open Questions

- What is the default time window for the MVP dashboard?
- Should roles see different default sections?
- Is pagination required in the MVP for opportunity and alert lists?
- Should the dashboard support manual refresh or auto-refresh in the MVP?
