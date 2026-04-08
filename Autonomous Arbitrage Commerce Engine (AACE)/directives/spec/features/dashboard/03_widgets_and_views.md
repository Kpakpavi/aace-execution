# Dashboard Widgets and Views

## 1. Purpose

This document defines the individual widgets and views that make up the AACE MVP Dashboard.

It specifies:

- what each widget displays,
- how each widget behaves,
- what data each widget depends on,
- what constitutes correct widget behavior.

This document is a companion to the dashboard requirements and acceptance criteria.

---

## 2. Widget Design Principles

All dashboard widgets must be:

- deterministic (same data produces same display),
- role-aware (only authorized data is shown),
- read-only (no mutations from widget interactions),
- safe under empty or missing data (graceful fallback),
- clearly labeled (users understand what they are seeing).

---

## 3. Widget Inventory

### Widget 1: Total Opportunities Counter

**Purpose**: Display the total number of opportunities detected in the active time window.

**Data Source**: opportunity records filtered by time window.

**Display**:
- numeric count,
- label: "Total Opportunities",
- time window label below the count.

**Rules**:
- count must reflect persisted opportunity records only,
- must not include in-progress or failed pipeline runs,
- must update when the page is refreshed.

**Empty State**:
- display "0" with a clear label,
- do not hide the widget if count is zero.

---

### Widget 2: Average Opportunity Score

**Purpose**: Display the average score across all opportunities in the active time window.

**Data Source**: opportunity score values filtered by time window.

**Display**:
- numeric average (rounded to defined precision),
- label: "Average Score",
- time window label below the value.

**Rules**:
- average must be computed from persisted scores,
- must use the same scoring model as defined in the scoring specification.

**Empty State**:
- display "N/A" or "0" if no opportunities exist in the time window.

---

### Widget 3: Opportunities by Status

**Purpose**: Display a breakdown of opportunities by their current status.

**Data Source**: opportunity records grouped by status, filtered by time window.

**Display**:
- list or summary of status labels with counts,
- each status row includes: status label, count.

**Status Values**:
- New,
- Under Review,
- Actioned,
- Dismissed.

**Rules**:
- all defined status values must appear even if count is zero,
- ordering must be deterministic.

**Empty State**:
- display all status labels with count 0.

---

### Widget 4: Total Alerts Counter

**Purpose**: Display the total number of alerts generated in the active time window.

**Data Source**: alert records filtered by time window.

**Display**:
- numeric count,
- label: "Total Alerts",
- time window label below the count.

**Rules**:
- count must reflect persisted alert records only,
- duplicate alerts for the same opportunity must not be counted twice.

**Empty State**:
- display "0" with a clear label.

---

### Widget 5: Recent Opportunities List

**Purpose**: Display a list of the most recent opportunities detected.

**Data Source**: opportunity records ordered by detection timestamp or score, limited to a defined count.

**Display**:
Each row must include:
- opportunity_id,
- score,
- product reference (name or identifier),
- status,
- timestamp.

**Rules**:
- list must have a defined maximum row count,
- ordering must be deterministic,
- no duplicate entries,
- clicking a row must navigate to the opportunity detail view (where implemented).

**Empty State**:
- display a clear empty state message if no opportunities exist.

---

### Widget 6: Recent Alerts List

**Purpose**: Display a list of the most recent alerts generated.

**Data Source**: alert records ordered by generation timestamp, limited to a defined count.

**Display**:
Each row must include:
- alert_id,
- opportunity reference,
- score,
- summary,
- timestamp.

**Rules**:
- list must have a defined maximum row count,
- ordering must be deterministic,
- no duplicate alerts displayed.

**Empty State**:
- display a clear empty state message if no alerts exist.

---

### Widget 7: Navigation Links

**Purpose**: Provide quick navigation to deeper system views.

**Links**:
- Opportunity Review — navigates to full opportunity list and detail view,
- Reports — navigates to the reporting section.

**Rules**:
- links must respect role-based access control,
- if a user does not have access to a target view, the link must not be shown or must be clearly disabled,
- links must function correctly and not navigate to broken or unauthorized pages.

---

## 4. Time Window Selector

**Purpose**: Allow users to change the time window applied to dashboard metrics.

**MVP Options**:
- Today,
- Last 7 days (default),
- Last 30 days.

**Rules**:
- changing the time window must refresh all metric widgets,
- the selected time window must be clearly visible,
- the selected time window must apply consistently to all widgets.

---

## 5. Dashboard Layout

For the MVP, the dashboard layout must:

- display summary metric widgets first,
- display recent opportunities and alerts below the metrics,
- display navigation links in a consistent, accessible location.

Advanced layout customization is not required for the MVP.

---

## 6. Role-Aware Visibility

The following visibility rules apply:

| Role | Visible Widgets |
|------|----------------|
| Admin | All widgets |
| Manager | All widgets except admin-only views |
| User | Summary metrics, recent opportunities, recent alerts, navigation |

Widgets containing sensitive or admin-only data must not be visible to lower roles.

---

## 7. Failure Behavior

If a widget cannot load its data:

- the widget must display a clean error or unavailable state,
- the error must not expose internal system details,
- other widgets must not be affected by one widget's failure,
- the failure must be logged.

---

## 8. Constraints

Widgets must NOT:

- trigger business logic,
- modify any system records,
- make synchronous live marketplace API calls,
- display data outside the user's authorization scope.

---

## 9. Open Questions

- What is the maximum row count for the recent opportunities and alerts lists?
- Should score values be displayed as raw numbers or mapped to a human-readable label?
- Should any widget support drill-down in the MVP or only top-level summary?
- Is a time window selector required for the first MVP release or can a fixed default be used?
