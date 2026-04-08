# eBay Integration Specification

## 1. Purpose

This document defines the specification for the eBay marketplace integration in the AACE MVP.

It specifies:

- what data the eBay adapter must fetch,
- how authentication is handled,
- what the output data model must look like,
- what safety and rate limiting rules apply,
- what is in and out of scope for the MVP.

---

## 2. Integration Overview

The eBay adapter retrieves product and pricing data from the eBay marketplace for use in discrepancy detection and opportunity scoring.

This integration is read-only in the MVP.

No write operations (listing creation, repricing, order management) are permitted.

---

## 3. MVP Scope

### In Scope

- Fetching product listing data by eBay item identifier or search criteria,
- Fetching current pricing data for a given listing,
- Normalizing eBay response data to the internal data model.

### Out of Scope

- Creating or updating eBay listings,
- Managing eBay orders,
- Seller account management,
- eBay advertising or promoted listings,
- eBay feedback or reputation management.

---

## 4. Authentication

The eBay adapter must authenticate using the credentials defined for eBay marketplace API access.

Rules:

- credentials must be injected via environment variables,
- credentials must never be hardcoded in source code or directive files,
- credentials must be stored and rotated following the procedure in the runbook,
- authentication failures must surface as typed exceptions with clear error messages.

---

## 5. Data to Fetch

### Product Listing Data

Minimum required fields:

- marketplace_product_id (eBay item ID or equivalent),
- product title,
- product category,
- marketplace identifier (eBay),
- listing condition (new, used, etc.) where available.

### Pricing Data

Minimum required fields:

- marketplace_product_id,
- current price (value and currency),
- price type (e.g., buy it now, auction current bid),
- timestamp of observation.

---

## 6. Output Normalization

All data returned by the eBay adapter must be normalized to the internal data model before storage.

Rules:

- raw eBay API response payloads must not be stored as the primary record,
- normalization must be deterministic,
- normalization failures must produce clear typed errors,
- currency values must be preserved with their currency code,
- auction-style pricing must be clearly distinguished from fixed-price listings.

---

## 7. Rate Limiting

The eBay adapter must respect eBay marketplace API rate limits.

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
- listing not found: surface as typed not-found exception,
- malformed response: surface as parse error exception,
- network timeout: surface as retriable exception.

All errors must be logged with enough context to diagnose the failure.

---

## 9. Mock Adapter

A mock eBay adapter must be provided for testing.

The mock must:

- implement the same interface as the live adapter,
- return deterministic test data,
- never make real API calls,
- support scenarios for success, not-found, auction pricing, and failure cases.

---

## 10. Testing Requirements

Tests for the eBay adapter must:

- use the mock adapter by default,
- verify normalization output including auction versus fixed-price handling,
- verify error handling behavior,
- never call the live eBay API during automated test runs.

Live API tests may only run with an explicit opt-in environment flag against a sandbox or test account.

---

## 11. Constraints

The eBay adapter must NOT:

- write to any eBay account,
- store credentials in source code or directive files,
- exceed defined API rate limits,
- return raw API payloads as the primary data record,
- treat auction and fixed-price listings interchangeably without normalization.

---

## 12. Open Questions

- Which eBay API product is used for this integration (Browse API, Finding API, or other)?
- Does eBay provide a sandbox environment suitable for safe integration testing?
- Should auction-style listings be included in discrepancy detection or filtered out in the MVP?
- Which eBay marketplaces or regions should the MVP adapter support initially?
