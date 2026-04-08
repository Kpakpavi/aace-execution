# Amazon Integration Specification

## 1. Purpose

This document defines the specification for the Amazon marketplace integration in the AACE MVP.

It specifies:

- what data the Amazon adapter must fetch,
- how authentication is handled,
- what the output data model must look like,
- what safety and rate limiting rules apply,
- what is in and out of scope for the MVP.

---

## 2. Integration Overview

The Amazon adapter retrieves product and pricing data from the Amazon marketplace for use in discrepancy detection and opportunity scoring.

This integration is read-only in the MVP.

No write operations (repricing, order placement, inventory updates) are permitted.

---

## 3. MVP Scope

### In Scope

- Fetching product listing data by product identifier (ASIN or equivalent),
- Fetching current pricing data for a given listing,
- Normalizing Amazon response data to the internal data model.

### Out of Scope

- Writing to Amazon accounts,
- Advertising API access,
- Order management,
- Seller performance data,
- FBA inventory management.

---

## 4. Authentication

The Amazon adapter must authenticate using the credentials defined for Amazon marketplace API access.

Rules:

- credentials must be injected via environment variables,
- credentials must never be hardcoded in source code or directive files,
- credentials must be stored and rotated following the procedure in the runbook,
- authentication failures must surface as typed exceptions with clear error messages.

---

## 5. Data to Fetch

### Product Listing Data

Minimum required fields:

- marketplace_product_id (ASIN or equivalent),
- product title,
- product category,
- marketplace identifier (Amazon).

### Pricing Data

Minimum required fields:

- marketplace_product_id,
- current price (value and currency),
- price type (e.g., buy box, listing price),
- timestamp of observation.

---

## 6. Output Normalization

All data returned by the Amazon adapter must be normalized to the internal data model before storage.

Rules:

- raw Amazon API response payloads must not be stored as the primary record,
- normalization must be deterministic,
- normalization failures must produce clear typed errors,
- currency values must be preserved with their currency code.

---

## 7. Rate Limiting

The Amazon adapter must respect Amazon marketplace API rate limits.

Rules:

- the adapter must track and respect the defined API call quotas,
- rate limit errors must be caught and surfaced as retriable typed exceptions,
- the adapter must implement bounded retry behavior with backoff,
- rate limit handling must be internal to the adapter and invisible to the caller.

---

## 8. Error Handling

The adapter must handle the following error types:

- authentication failure: surface as non-retriable exception,
- rate limit exceeded: surface as retriable exception with backoff,
- product not found: surface as typed not-found exception,
- malformed response: surface as parse error exception,
- network timeout: surface as retriable exception.

All errors must be logged with enough context to diagnose the failure.

---

## 9. Mock Adapter

A mock Amazon adapter must be provided for testing.

The mock must:

- implement the same interface as the live adapter,
- return deterministic test data,
- never make real API calls,
- support scenarios for success, not-found, and failure cases.

---

## 10. Testing Requirements

Tests for the Amazon adapter must:

- use the mock adapter by default,
- verify normalization output,
- verify error handling behavior,
- never call the live Amazon API during automated test runs.

Live API tests may only run with an explicit opt-in environment flag against a sandbox or test account.

---

## 11. Constraints

The Amazon adapter must NOT:

- write to any Amazon account,
- store credentials in source code or directive files,
- exceed defined API rate limits,
- return raw API payloads as the primary data record,
- make synchronous calls in user-facing request paths without justification.

---

## 12. Open Questions

- Which Amazon API product is used for this integration (SP-API, MWS, or other)?
- What is the Amazon sandbox environment setup required for safe testing?
- Which markets or regions should the MVP adapter support initially?
- Is a real Amazon seller account required for MVP testing or only a sandbox account?
