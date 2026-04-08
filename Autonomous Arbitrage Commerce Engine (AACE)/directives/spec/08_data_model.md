# AACE MVP Data Model

## 1. Purpose

This document defines the core data model for the AACE MVP.

It specifies:

- required entities
- relationships between entities
- what must be stored vs derived
- rules for data integrity and auditability

This is the source of truth for system data structure.

---

## 2. Data Model Principles

The data model must be:

- explicit (no hidden structure)
- relational (clear relationships)
- deterministic (same input → same stored state)
- auditable (traceable changes)
- minimal (no unnecessary complexity)

---

## 3. Core Entities

The MVP must support the following entities:

1. Users  
2. Roles  
3. Products  
4. Listings  
5. Price Observations  
6. Opportunities  
7. Audit Events  

---

## 4. Entity Definitions

---

### 4.1 Users

Represents system users.

**Fields:**
- id
- email
- password_hash
- role
- created_at
- updated_at

**Rules:**
- email must be unique
- password must never be stored in plaintext

---

### 4.2 Roles

Defines access levels.

**Values:**
- admin
- manager
- user

**Rules:**
- must enforce least privilege

---

### 4.3 Products

Represents normalized product entities.

**Fields:**
- id
- name
- normalized_identifier (SKU or equivalent)
- created_at
- updated_at

**Rules:**
- must support linking multiple listings
- must be uniquely identifiable

---

### 4.4 Listings

Represents marketplace-specific listings.

**Fields:**
- id
- product_id (FK)
- source (amazon, ebay, etc.)
- external_id
- price
- currency
- created_at
- updated_at

**Rules:**
- must link to product
- must preserve source identity

---

### 4.5 Price Observations

Represents price snapshots over time.

**Fields:**
- id
- product_id (FK)
- listing_id (FK)
- observed_price
- source
- observed_at
- created_at

**Rules:**
- must include timestamp
- must support historical tracking
- must be immutable after creation

---

### 4.6 Opportunities

Represents detected arbitrage opportunities.

**Fields:**
- id
- product_id (FK)
- score
- discrepancy_value
- status (active, dismissed, reviewed)
- created_at
- updated_at

**Rules:**
- must be derived from discrepancy detection
- must include explainable score
- must support status updates

---

### 4.7 Audit Events

Tracks system activity.

**Fields:**
- id
- event_type
- actor_id (user/system)
- entity_type
- entity_id
- metadata (JSON)
- created_at

**Rules:**
- must be append-only
- must not expose sensitive data
- must support traceability

---

## 5. Relationships

- User → Role (many-to-one)
- Product → Listings (one-to-many)
- Product → Observations (one-to-many)
- Listing → Observations (one-to-many)
- Product → Opportunities (one-to-many)
- User → Audit Events (one-to-many)

---

## 6. Derived vs Stored Data

### Stored:
- products
- listings
- observations
- opportunities
- audit events

### Derived:
- discrepancy calculations
- scoring factors (may be partially stored for explainability)

---

## 7. Data Integrity Rules

- foreign keys must be enforced
- orphan records must not exist
- timestamps required for all entities
- status values must be validated

---

## 8. Immutability Rules

- observations are immutable
- audit events are immutable
- historical truth must not be overwritten

---

## 9. Auditability Requirements

System must be able to answer:

- what data was ingested
- what evaluation occurred
- what outputs were created
- who performed actions
- when events happened

---

## 10. MVP Constraints

The data model must NOT:

- rely on unstructured blobs as primary storage
- store secrets in tables
- mix unrelated domains
- depend on AI-generated structure

---

## 11. Future Extensions (Not MVP)

- warehouse layer
- analytics tables
- caching layer (Redis)
- external data sync logs

---

## 12. Open Questions

- retention policy for observations?
- required opportunity statuses?
- metadata structure limits?
```

---

## ⚠️ CRITICAL NOTES

This model is:

* ✔ Minimal but complete
* ✔ Fully relational
* ✔ Deterministic
* ✔ Audit-safe
* ✔ MVP-aligned

---

## Common Mistakes

Do NOT:

* Add extra entities “just in case”
* Store logic instead of data
* Skip relationships
* Overuse JSON fields


