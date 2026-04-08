# AACE MVP Overview

## 1. Purpose

Autonomous Arbitrage Commerce Engine (AACE) is a SaaS platform intended to help eCommerce operators identify actionable price discrepancies across marketplaces in a controlled, auditable, and scalable way.

The MVP is not a full autonomous commerce platform. Its purpose is to establish the smallest reliable version of the system that can:

- ingest product and listing data,
- compare prices across defined sources,
- detect meaningful discrepancies,
- score opportunities using transparent rules,
- present results in a way that a user can review and act on.

The MVP prioritizes safety, determinism, auditability, and clarity over breadth of automation.

---

## 2. Business Intent

The business problem AACE addresses is that eCommerce sellers often miss profitable opportunities because marketplace prices change quickly and manual monitoring is slow, inconsistent, and difficult to scale.

AACE is intended to reduce that manual burden by creating a system that continuously evaluates product pricing data and highlights opportunities that may be worth investigating.

The MVP should prove that the platform can deliver useful, trustworthy signals before expanding into deeper automation, broader integrations, and more advanced orchestration.

---

## 3. MVP Objective

The AACE MVP must demonstrate that the platform can reliably do the following:

1. accept a defined set of product and listing inputs,
2. normalize and store those inputs,
3. compare prices across selected marketplaces or simulated sources,
4. identify price discrepancies based on explicit rules,
5. score the resulting opportunities using deterministic logic,
6. present opportunities to authenticated users through a controlled interface or API,
7. preserve enough data and event history to support review, testing, and auditability.

Success for the MVP is not measured by full autonomy. Success is measured by the system’s ability to produce clear, traceable, and testable opportunity outputs.

---

## 4. Intended Users

The MVP is designed primarily for:

- solo eCommerce entrepreneurs,
- small business operators managing multiple listings,
- growth-focused sellers seeking faster pricing visibility,
- internal admins or managers reviewing system outputs.

These users need actionable visibility into pricing differences, not a black-box automation engine.

---

## 5. Core Value Proposition

The AACE MVP provides value by combining:

- structured product/listing ingestion,
- controlled discrepancy detection,
- transparent opportunity scoring,
- authenticated user access,
- auditable system behavior.

Its core promise is:

> help users identify potentially profitable price discrepancies faster and more consistently than manual workflows.

---

## 6. MVP Scope Summary

### In Scope

The MVP includes:

- user authentication and role-based access control,
- product and listing data ingestion from approved sources,
- storage of products, listings, price observations, and opportunity evaluations,
- discrepancy detection rules for comparing marketplace prices,
- deterministic opportunity scoring,
- protected dashboard and/or API access for reviewing results,
- basic reporting of detected opportunities,
- audit/event logging sufficient for debugging and replay,
- a Claude-governed workflow where planning/specification is separated from deterministic execution.

### Out of Scope

The MVP does not include:

- autonomous purchasing or order execution,
- automatic repricing on live marketplaces,
- broad marketplace coverage from day one,
- advanced AI-driven decision-making replacing deterministic evaluation,
- enterprise IAM or SSO,
- full-scale microservices architecture,
- unlimited integrations,
- production-grade business intelligence warehouse,
- unrestricted agent autonomy.

Anything beyond controlled opportunity detection and review should be treated as future work unless explicitly approved.

---

## 7. High-Level System Model

The MVP follows a layered model:

1. **Directives / Specifications Layer**  
   Defines system intent, constraints, acceptance criteria, decomposition, and evaluation logic.

2. **Claude Orchestration Layer**  
   Claude operates as planner, explainer, and orchestrator. Claude does not directly become the runtime execution engine for business logic.

3. **Deterministic Execution Layer**  
   Application code, services, tests, and scripts perform actual data processing, API handling, storage, and evaluation in a controlled and reproducible way.

This separation is essential to maintain safety, predictability, and auditability.

---

## 8. Architectural Direction

For the MVP, AACE should follow a modular monolith architecture with well-defined internal boundaries.

This means:

- one primary application system of record,
- modular separation by domain,
- clear boundaries between auth, ingestion, price monitoring, scoring, reporting, and audit behavior,
- a design that supports future extraction if scale or complexity requires it.

The MVP is intentionally not microservices-first.

---

## 9. Data Direction

The MVP should use a relational system of record for core entities and preserve structured, queryable data for:

- users,
- products,
- marketplace listings,
- price observations,
- opportunity evaluations,
- audit/event records.

Highly variable metadata may be stored in bounded form, but the primary business model must remain explicit and understandable.

---

## 10. Security Direction

The MVP must operate with minimum necessary access and least-privilege assumptions.

Core security expectations include:

- authenticated access,
- role-based authorization,
- secure password handling,
- no secrets in repository,
- controlled handling of integration credentials,
- protected APIs and dashboards,
- safe logging practices,
- traceability of important user and system actions.

---

## 11. What the MVP Must Prove

The MVP must prove that AACE can do the following in a trustworthy way:

- ingest relevant pricing inputs,
- detect discrepancies consistently,
- score opportunities transparently,
- expose results to the right users,
- retain enough information to explain how outputs were produced,
- support testing across happy path, edge case, failure, and retry scenarios.

This proof matters more than broad feature count.

---

## 12. Non-Goals

The MVP is not intended to prove:

- full autonomous commerce execution,
- AI-only decision quality,
- maximum marketplace coverage,
- enterprise-scale architecture,
- high-frequency trading-like price execution.

Those concerns belong to later phases after the MVP demonstrates correctness and control.

---

## 13. Success Criteria at a High Level

At a high level, the MVP is successful if:

- a user can securely access the system,
- relevant product/listing data can be ingested and stored,
- discrepancy rules produce reviewable opportunity candidates,
- scoring produces explainable prioritization,
- outputs are visible through a protected interface,
- the system can be tested and audited reliably.

Detailed success criteria are defined in the acceptance criteria and evaluation plan documents.

---

## 14. Dependency Relationship to Other Spec Files

This overview is the top-level narrative entry point for the spec system.

The following files refine this overview:

- `01_requirements.md` defines detailed functional and non-functional requirements,
- `02_acceptance_criteria.md` defines what must be true for the MVP to be considered done,
- `03_constraints.md` defines guardrails and boundaries,
- `04_breakdown_plan.md` defines the phased decomposition of implementation work,
- `05_eval_plan.md` defines how the system will be tested and evaluated,
- feature-level specs define domain-specific behavior such as price monitoring, alerts, and opportunity scoring.

This file should remain high-level and stable.

---

## 15. Implementation Principle

The implementation principle for the MVP is:

**build the smallest trustworthy system that can detect and present actionable price discrepancies with clear rules, secure access, and auditable behavior.**

When trade-offs appear, prefer:

1. safety,
2. correctness,
3. determinism,
4. auditability,
5. maintainability,
6. speed.

---

## 16. Open Questions

- Which marketplaces or data sources should be included in the first live MVP slice?
- Will the first user-facing review surface be API-first, dashboard-first, or both?
- What opportunity threshold should be considered meaningful for the first scoring model?
- How much historical price retention is required for the MVP versus later analytics phases?