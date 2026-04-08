# AACE MVP Architecture

## 1. Purpose

This document defines the high-level architecture of the AACE MVP.

Its purpose is to describe:

- the major system modules,
- the responsibility of each module,
- the boundaries between planning and execution,
- how data moves through the system,
- how the MVP remains deterministic, auditable, and maintainable.

This file is not a low-level implementation document.
It does not define exact classes, frameworks, migrations, or deployment scripts.
Instead, it defines the architectural shape that implementation must follow.

---

## 2. Architectural Objective

The AACE MVP architecture must support the following outcomes:

1. secure user access,
2. controlled ingestion of product and listing data,
3. deterministic price discrepancy detection,
4. transparent opportunity scoring,
5. protected review and reporting surfaces,
6. auditable system behavior,
7. future extensibility without premature distributed complexity.

The architecture must prioritize:

- safety,
- correctness,
- determinism,
- auditability,
- maintainability,
- operational simplicity.

---

## 3. Chosen Architectural Style

The AACE MVP uses a **modular monolith** architecture.

This means:

- one primary application boundary,
- one primary system of record,
- clearly separated internal modules by domain,
- shared runtime and deployment unit for the MVP,
- no premature split into microservices.

The modular monolith is chosen because it provides:

- faster MVP implementation,
- simpler debugging,
- easier local development,
- clearer auditability,
- strong control over system behavior,
- a path to later extraction if needed.

---

## 4. Architectural Principles

The architecture must follow these principles:

### 4.1 Explicit Domain Boundaries
Each major domain must have a visible boundary and a clear responsibility.

### 4.2 Deterministic Runtime Logic
Core business logic must execute in deterministic application code, not opaque runtime AI behavior.

### 4.3 Specification-Led Development
Architecture must remain aligned with directives, ADRs, requirements, constraints, and acceptance criteria.

### 4.4 Explainable Outputs
Important outputs must be traceable back to inputs, rules, and persisted state.

### 4.5 Security by Default
Protected routes, sensitive data, and admin capabilities must be explicitly guarded.

### 4.6 Operational Simplicity
The MVP should avoid unnecessary services, databases, queues, and orchestration layers.

### 4.7 Extraction-Friendly Design
Even though the MVP is a modular monolith, module boundaries should be strong enough that future extraction remains possible if justified.

---

## 5. Three-Layer Operating Model

The AACE MVP follows a three-layer operating model.

### 5.1 Layer 1 — Directives and Specification
This layer defines intent, rules, constraints, and evaluation expectations.

Examples:
- ADRs
- overview
- requirements
- acceptance criteria
- constraints
- evaluation plan
- feature specs

This layer is the source of truth for what must be built.

### 5.2 Layer 2 — Claude Orchestration
Claude operates as:

- planner,
- explainer,
- reviewer support,
- scoped generation assistant.

Claude does not function as the runtime business engine.
Claude may help reason about implementation, but core logic must live in deterministic code.

### 5.3 Layer 3 — Deterministic Execution
This is the application runtime.

It includes:

- auth logic,
- ingestion logic,
- discrepancy evaluation,
- scoring,
- protected APIs,
- dashboard behavior,
- reporting behavior,
- persistence,
- tests,
- operational scripts.

This layer performs actual business behavior.

---

## 6. Major MVP Domains

The architecture must preserve the following major domains:

1. Authentication and Access Control
2. Product and Listing Ingestion
3. Product Catalog / Entity Management
4. Price Observation Management
5. Price Monitoring and Discrepancy Detection
6. Opportunity Evaluation and Scoring
7. Opportunity Review Surface
8. Reporting and Analytics
9. Audit and Event Recording
10. Administrative Control

These domains may share infrastructure, but they must not be blended into a single undifferentiated module.

---

## 7. Proposed Module Structure

A future implementation may organize the modular monolith into domain-oriented modules such as:

- `auth`
- `users`
- `products`
- `listings`
- `observations`
- `ingestion`
- `discrepancy_detection`
- `opportunity_scoring`
- `opportunities`
- `reporting`
- `audit`
- `admin`

These names are illustrative, but the boundaries are required.

Each module should own its:

- domain logic,
- validations,
- service interfaces,
- persistence interactions,
- test surface,
- audit-relevant events where appropriate.

---

## 8. Domain Responsibilities

## 8.1 Authentication and Access Control Domain
Responsible for:

- user authentication,
- session or token validation,
- role-based authorization,
- protected route enforcement,
- auth-related security boundaries.

This domain must not own business opportunity logic.

---

## 8.2 User Domain
Responsible for:

- user records,
- user profile state where applicable,
- role assignment references,
- user ownership relationships.

This domain must remain distinct from auth implementation details when possible.

---

## 8.3 Product Domain
Responsible for:

- product-level entity identity,
- product normalization,
- product-to-listing relationship foundation.

It must provide stable references for downstream evaluation.

---

## 8.4 Listing Domain
Responsible for:

- marketplace/source listing records,
- listing-source identity,
- listing-specific pricing and availability-related fields,
- relationship to product entities.

---

## 8.5 Observation Domain
Responsible for:

- price observations over time,
- observation timestamps,
- source-linked historical pricing context,
- storage and retrieval of evaluation-relevant observations.

---

## 8.6 Ingestion Domain
Responsible for:

- accepting approved input shapes,
- validating required fields,
- normalization,
- rejecting or flagging malformed inputs,
- preserving source context,
- writing valid records into product/listing/observation domains.

Ingestion must not directly decide business opportunities.

---

## 8.7 Discrepancy Detection Domain
Responsible for:

- comparing relevant prices,
- applying explicit discrepancy rules,
- deciding whether a discrepancy exists,
- preserving reasoning inputs for later review.

This logic must be deterministic and independently testable.

---

## 8.8 Opportunity Scoring Domain
Responsible for:

- generating opportunity candidates from valid discrepancies,
- scoring opportunities using explicit factors,
- preserving explanation factors,
- supporting prioritization.

This domain must not rely on opaque scoring logic.

---

## 8.9 Opportunity Review Domain
Responsible for:

- exposing opportunities through protected APIs and/or UI,
- presenting discrepancy and score information,
- supporting user review,
- distinguishing visible statuses where defined.

This domain consumes outputs from detection and scoring domains.

---

## 8.10 Reporting Domain
Responsible for:

- summarized visibility,
- counts,
- score distribution,
- recent activity views,
- business-facing reporting surfaces within MVP scope.

---

## 8.11 Audit and Event Domain
Responsible for:

- recording key system actions,
- supporting traceability,
- enabling debugging and replay support where appropriate,
- preserving bounded, useful operational history.

Audit data must remain queryable and understandable.

---

## 8.12 Administrative Domain
Responsible for:

- approved admin-only views,
- user/role management within allowed boundaries,
- high-level operational oversight surfaces,
- controlled access to sensitive operational capabilities.

---

## 9. Data Flow Overview

The high-level data flow of the MVP is:

1. **User authenticates**
2. **Authorized user or system process initiates data ingestion**
3. **Input is validated and normalized**
4. **Products, listings, and observations are persisted**
5. **Discrepancy detection evaluates relevant pricing relationships**
6. **Opportunity scoring ranks valid opportunities**
7. **Outputs are stored and exposed to authorized users**
8. **Audit and event records preserve what occurred**
9. **Reporting surfaces summarize outcomes**

This flow is intentionally sequential and explainable.

---

## 10. Request and Processing Paths

The MVP supports two broad categories of processing paths:

### 10.1 User-Initiated Request Path
Examples:
- login,
- review opportunities,
- view reports,
- manage data within role scope.

These flows require authentication and authorization.

### 10.2 System Evaluation Path
Examples:
- ingestion processing,
- discrepancy evaluation,
- opportunity scoring,
- event recording.

These flows may be triggered by user action or controlled background processing, but they must remain deterministic and observable.

---

## 11. Background Processing Boundaries

The MVP may use limited background processing if needed, but only under controlled conditions.

Allowed uses may include:

- asynchronous ingestion tasks,
- delayed evaluation processing,
- report refresh jobs,
- bounded operational housekeeping.

However:

- background work must remain traceable,
- jobs must not silently mutate critical state,
- retries must be intentional,
- asynchronous behavior must not obscure business logic.

The MVP should not depend on a highly complex job orchestration system unless explicitly justified.

---

## 12. API and UI Boundary

The architecture should support protected access through:

- API endpoints,
- dashboard/UI views,
- or both.

The presentation layer must not own business rules.
It should consume domain outputs from deterministic services/modules.

UI and API layers may differ in form, but they must rely on the same core business logic and access rules.

---

## 13. Persistence Architecture

The MVP uses a primary relational system of record.

Core entities that must persist include:

- users,
- roles or access relationships,
- products,
- listings,
- price observations,
- opportunities,
- audit/event records.

Persistence rules:

- core business state must be explicit,
- relationships must be queryable,
- derived values should be distinguishable from source truth,
- flexible metadata must remain bounded and explainable.

The architecture must not treat unstructured payloads as the primary system model.

---

## 14. Security Architecture

Security is an architectural concern, not just an implementation detail.

The architecture must ensure:

1. authentication is required for protected surfaces,
2. authorization is enforced consistently,
3. least privilege is the default,
4. secrets are not stored in repo,
5. credential-bearing systems are treated as protected,
6. logs do not leak sensitive information,
7. admin capabilities are explicitly isolated.

Security controls must exist across module boundaries, not only at the UI layer.

---

## 15. Auditability Architecture

The system must be architected so that important actions can be reconstructed.

This means the architecture must preserve:

- event timing,
- input context,
- evaluation context,
- scoring context,
- user-triggered state changes,
- operational failures of consequence.

Auditability must not be bolted on at the end.
It is a first-class architectural requirement.

---

## 16. Determinism Architecture

The architecture must make deterministic behavior practical.

This means:

- discrepancy logic must not depend on opaque runtime agent decisions,
- scoring must be explicit,
- validation rules must be codified,
- access control rules must be reliable,
- side effects must be visible and bounded.

If a behavior affects business truth, it must be represented in explicit runtime logic.

---

## 17. Testing Architecture

The architecture must support testing at multiple levels.

### 17.1 Unit Testing Support
Modules with deterministic rules must be testable in isolation.

### 17.2 Integration Testing Support
Cross-domain flows such as auth, ingestion, and evaluation must be testable across module boundaries.

### 17.3 End-to-End Testing Support
The full MVP path from authenticated access to opportunity review must be testable as one coherent workflow.

The architecture must not create excessive coupling that makes testing impossible or fragile.

---

## 18. Observability and Operations Architecture

The MVP should include minimal but useful operational visibility.

The architecture should support:

- structured logs,
- bounded event recording,
- visibility into important failures,
- review of processing outcomes,
- investigation of discrepancies between expected and actual behavior.

This is not full observability-platform design, but the architecture must leave room for it.

---

## 19. Boundary Rules

The following architectural boundaries are mandatory:

1. Auth logic must not contain business scoring logic.
2. Ingestion logic must not define opportunity scoring rules.
3. UI/API layers must not become the source of core business truth.
4. Audit/event recording must not be omitted from critical flows.
5. Claude-generated reasoning must not replace deterministic runtime business behavior.
6. Modules must not bypass access control by direct, unguarded data exposure.
7. Reporting must consume defined data outputs, not ad hoc calculations detached from persisted truth.

---

## 20. Evolution Strategy

The MVP architecture should support future growth without prematurely implementing it.

Likely future evolutions may include:

- additional marketplace integrations,
- richer reporting,
- more advanced workflow states,
- specialized read models,
- selective background job expansion,
- eventual extraction of high-load modules into separate services.

However, none of these future possibilities justify weakening the MVP’s modular monolith discipline now.

---

## 21. Architecture Success Criteria

The architecture is successful if:

- the major domains are clearly separated,
- the MVP can be built without architectural ambiguity,
- core logic remains deterministic,
- protected surfaces remain secure,
- auditability is preserved,
- contributors can explain where responsibilities belong,
- future evolution remains possible without major rework.

---

## 22. Risks the Architecture Intentionally Avoids

This architecture is intentionally designed to avoid:

- microservices complexity too early,
- hidden AI runtime decision-making,
- mixed planning/runtime responsibility,
- weak data boundaries,
- UI-owned business logic,
- untraceable outputs,
- unbounded operational complexity.

---

## 23. Relationship to Other Specs

This architecture document is refined by:

- ADRs for architecture, storage, and auth/access,
- API contracts,
- data model specs,
- security/privacy specs,
- observability/ops specs,
- feature-level specs.

Implementation must follow this document in combination with those more specific files.

---

## 24. Open Questions

- Should the first review surface be API-first, dashboard-first, or both?
- Which module boundaries should be physically separated earliest in the codebase?
- What minimum background processing is actually necessary for the first MVP slice?
- Which audit events are mandatory on day one versus shortly after MVP release?