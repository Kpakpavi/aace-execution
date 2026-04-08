# AACE MVP Integrations

## 1. Purpose

This document defines the integration requirements for the AACE MVP.

It specifies:

- which external systems the MVP integrates with,
- how integrations are structured,
- what safety and credential rules apply to all integrations,
- what is in and out of scope for the MVP.

Integrations are the boundary between AACE and the external world. They must be controlled, testable, and safe.

---

## 2. Integration Principles

All integrations must be:

- isolated in dedicated adapter modules,
- testable with mock implementations,
- safe to fail without crashing the core system,
- credential-safe (no secrets in code or repository),
- read-only in the MVP unless explicitly approved otherwise.

---

## 3. MVP Integration Scope

### In Scope

The MVP must support:

- at least one marketplace integration for product and pricing data retrieval,
- a mock adapter interface for testing without live API calls.

### Out of Scope

The MVP does not include:

- write operations to any marketplace (no auto-repricing, no order placement),
- payment gateway integrations,
- ERP or warehouse system integrations,
- email or notification platform integrations (unless explicitly approved),
- full multi-marketplace live coverage from day one.

---

## 4. Integration Architecture

Each integration must be implemented as a dedicated adapter.

### Adapter Requirements

Each adapter must:

- implement the common internal integration interface,
- handle all marketplace-specific authentication internally,
- normalize output to the standard internal data model,
- handle rate limiting and retry behavior internally,
- surface failures as typed exceptions,
- be testable in isolation using a mock or stub.

### Common Interface

All adapters must expose:

- a method to fetch product listings for a given product or identifier,
- a method to fetch current pricing data,
- a method to validate connectivity (for health check purposes).

---

## 5. Credential Management

All integration credentials must:

- be injected via environment variables at runtime,
- never appear in source code, directive files, or committed configuration,
- be documented in `.env.example` as named placeholders,
- be rotated following the procedure defined in the runbook.

---

## 6. MVP Marketplace Integrations

Detailed integration specifications are defined in:

- `features/integrations/amazon.md`
- `features/integrations/ebay.md`
- `features/integrations/shopify.md`

For the MVP, a subset of these will be activated. The active integrations must be defined in configuration, not hardcoded.

---

## 7. Mock Integration Requirements

All live integrations must have a mock counterpart for testing.

Mock adapters must:

- implement the same interface as the live adapter,
- return deterministic test data,
- never make real API calls,
- be used as the default in all unit and integration tests.

---

## 8. Rate Limiting and Throttling

Each adapter must handle the rate limits imposed by the target marketplace.

Rules:

- adapters must not exceed marketplace rate limits,
- rate limit handling must be internal to each adapter,
- rate limit errors must be surfaced as typed exceptions with retry guidance,
- retry behavior must be bounded and idempotent.

---

## 9. Failure Handling

Integration failures must:

- never crash the core system,
- surface as explicit, typed exceptions,
- be logged with enough context to diagnose the failure,
- trigger appropriate retry behavior where applicable,
- not produce duplicate records on retry.

---

## 10. Data Normalization

All data returned by marketplace adapters must be normalized to the internal data model before storage.

Rules:

- raw marketplace payloads must not be stored as the primary record,
- normalization logic must be deterministic,
- normalization failures must produce clear errors, not partial records.

---

## 11. Audit and Traceability

Each integration call must be traceable.

Minimum logging requirements per call:

- marketplace identifier,
- type of request (product fetch, price fetch),
- outcome (success or failure),
- timestamp.

---

## 12. Integration Testing Rules

Integration tests for marketplace adapters:

- must use mock adapters by default,
- must never call live marketplace APIs during automated test runs,
- may test against a sandbox or dev account only with explicit opt-in (environment flag),
- must verify normalization output, not just raw adapter response.

---

## 13. Post-MVP Integration Path

After the MVP proves the integration model, future integrations may include:

- additional marketplace adapters,
- notification or alerting platform integrations,
- export integrations for reporting,
- write-capable marketplace actions with appropriate safeguards.

Each new integration requires its own adapter specification and approval before implementation.

---

## 14. Constraints

Integrations must NOT:

- write to external systems in the MVP without explicit approval,
- store credentials in the repository,
- make synchronous live API calls in user-facing request paths without a clear performance and failure justification,
- bypass the common adapter interface.

---

## 15. Open Questions

- Which marketplace integration is activated first in the MVP?
- Should the sandbox/test environment require a real API key or only the mock adapter?
- What is the acceptable maximum latency for a marketplace adapter call?
- How should integration failures be surfaced to the dashboard or admin view?
