# Shopify Integration Specification

## 1. Purpose

This document defines the specification for the Shopify integration in the AACE MVP.

It specifies:

- what data the Shopify adapter must fetch,
- how authentication is handled,
- what the output data model must look like,
- what safety and rate limiting rules apply,
- what is in and out of scope for the MVP.

---

## 2. Integration Overview

The Shopify adapter retrieves product and pricing data from a Shopify store for use in discrepancy detection and opportunity scoring.

This integration is read-only in the MVP.

No write operations (price updates, order management, product changes) are permitted.

---

## 3. MVP Scope

### In Scope

- Fetching product data from a connected Shopify store,
- Fetching current pricing data for products and variants,
- Normalizing Shopify response data to the internal data model.

### Out of Scope

- Creating or updating Shopify products,
- Managing Shopify orders,
- Shopify fulfillment management,
- Shopify Payments or financial data,
- Shopify theme or storefront management,
- Multi-store aggregation beyond a single connected store.

---

## 4. Authentication

The Shopify adapter must authenticate using the credentials defined for Shopify API access.

Rules:

- credentials must be injected via environment variables,
- credentials must never be hardcoded in source code or directive files,
- credentials must be stored and rotated following the procedure in the runbook,
- authentication failures must surface as typed exceptions with clear error messages,
- the Shopify store URL must also be configurable via environment variable.

---

## 5. Data to Fetch

### Product Data

Minimum required fields:

- marketplace_product_id (Shopify product ID),
- product title,
- product type or category,
- marketplace identifier (Shopify),
- variant IDs where applicable.

### Pricing Data

Minimum required fields:

- marketplace_product_id and variant_id,
- current price (value and currency),
- compare_at_price where available (for context),
- timestamp of observation.

---

## 6. Output Normalization

All data returned by the Shopify adapter must be normalized to the internal data model before storage.

Rules:

- raw Shopify API response payloads must not be stored as the primary record,
- normalization must be deterministic,
- normalization failures must produce clear typed errors,
- currency values must be preserved with their currency code,
- product variants must be handled distinctly where pricing differs by variant.

---

## 7. Rate Limiting

The Shopify adapter must respect Shopify API rate limits.

Rules:

- the adapter must track and respect Shopify's REST or GraphQL API rate limits,
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
- network timeout: surface as retriable exception,
- store not accessible: surface as non-retriable configuration exception.

All errors must be logged with enough context to diagnose the failure.

---

## 9. Mock Adapter

A mock Shopify adapter must be provided for testing.

The mock must:

- implement the same interface as the live adapter,
- return deterministic test data including multi-variant products,
- never make real API calls,
- support scenarios for success, not-found, variant pricing, and failure cases.

---

## 10. Testing Requirements

Tests for the Shopify adapter must:

- use the mock adapter by default,
- verify normalization output including variant price handling,
- verify error handling behavior,
- never call the live Shopify API during automated test runs.

Live API tests may only run with an explicit opt-in environment flag against a development Shopify store.

---

## 11. Constraints

The Shopify adapter must NOT:

- write to any Shopify store,
- store credentials in source code or directive files,
- exceed defined API rate limits,
- return raw API payloads as the primary data record,
- treat product variants with different prices as a single undifferentiated price point.

---

## 12. Open Questions

- Should the AACE MVP support connecting to a user-owned Shopify store via OAuth, or only via a private app credential?
- How should Shopify stores with large product catalogs be handled in the MVP?
- Should compare_at_price be used in discrepancy detection logic or treated as informational only?
- Is a Shopify development store sufficient for MVP integration testing?
