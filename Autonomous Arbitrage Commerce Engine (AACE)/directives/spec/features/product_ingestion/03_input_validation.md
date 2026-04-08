# Product Ingestion Input Validation Rules

## 1. Purpose

This document defines the explicit validation rules for all inputs to the Product Ingestion feature.

It specifies:

- what constitutes valid input
- what must be rejected
- how validation is applied
- how failures are handled

This document removes ambiguity from ingestion behavior.

---

## 2. Validation Philosophy

Validation must prioritize:

- correctness over convenience
- strictness over flexibility
- explicit rejection over silent correction

The system must:

- reject invalid data
- avoid guessing missing values
- avoid partial acceptance

Invalid input must not enter the system under any condition.

---

## 3. Validation Scope

Validation applies to:

- product data
- listing data
- price data
- source identifiers
- optional metadata (timestamps, currency)

---

## 4. Product Validation Rules

### 4.1 Required Fields

A product is valid only if:

- at least one identifier exists (name OR external_id)

If missing → reject input

---

### 4.2 Identifier Rules

Product identifiers must:

- be non-empty
- be string type
- not contain invalid characters (implementation-defined)

---

### 4.3 Normalization Rules

Product identifiers must be:

- trimmed of whitespace
- consistently formatted

---

## 5. Listing Validation Rules

### 5.1 Required Fields

A listing is valid only if ALL exist:

- source
- external_id
- price

If any missing → reject input

---

### 5.2 Source Validation

Source must:

- be non-empty string
- belong to allowed source set (if defined)

Invalid source → reject

---

### 5.3 External ID Rules

External ID must:

- be non-empty
- be string type
- uniquely identify listing within source

---

## 6. Price Validation Rules

### 6.1 Type Validation

Price must:

- be numeric (integer or float)

If not numeric → reject

---

### 6.2 Value Validation

Price must:

- be greater than 0
- not be null
- not be negative

---

### 6.3 Precision (Optional MVP)

Price should:

- support decimal values
- be normalized to consistent precision if required

---

## 7. Currency Validation (Optional MVP)

If currency is present:

- must be valid currency code
- must be consistent format (e.g., USD)

If invalid → reject or ignore (must be explicitly defined)

---

## 8. Timestamp Validation (Optional)

If timestamp is present:

- must be valid datetime format
- must not be malformed

Invalid timestamp → reject or ignore (must be defined)

---

## 9. Relationship Validation

The system must ensure:

- every listing is linked to a valid product
- product context exists before listing creation

If relationship is invalid → reject

---

## 10. Duplicate Detection Rules

The system should detect:

- duplicate product identifiers
- duplicate listing (same source + external_id)

Rules:

- duplicates must not create multiple records
- duplicates must be handled deterministically

---

## 11. Batch Validation Rules (If Batch Supported)

If multiple records are submitted:

- each record must be validated independently
- invalid records must not affect valid ones (if partial allowed)
- OR entire batch rejected (must be explicitly defined)

MVP must define one consistent behavior.

---

## 12. Failure Handling Rules

When validation fails:

- input must be rejected
- no records created
- error must be returned

Error must include:

- field causing failure
- reason for failure

---

## 13. Forbidden Behavior

The system must NOT:

- auto-correct invalid values silently
- infer missing required fields
- accept partial records
- coerce invalid types (e.g., "100" → 100 without rule)
- create records from invalid input

---

## 14. Determinism Rules

Validation must be deterministic:

- same input → same validation result
- no randomness
- no hidden logic

---

## 15. Example Valid Input

Product:
- name: "Product A"

Listing:
- source: "amazon"
- external_id: "A123"
- price: 100.50

Result:
- accepted

---

## 16. Example Invalid Inputs

### Missing Price
- listing without price

Result:
- rejected

---

### Invalid Price Type
- price: "abc"

Result:
- rejected

---

### Negative Price
- price: -10

Result:
- rejected

---

### Missing Source
- listing without source

Result:
- rejected

---

## 17. Completion Criteria

Validation rules are complete if:

- all required fields are defined
- invalid cases are explicitly handled
- behavior is deterministic
- no ambiguity exists

---

## 18. Non-Acceptance Conditions

Validation rules must be rejected if:

- invalid data can pass validation
- behavior is ambiguous
- rules are incomplete
- system guesses missing values
- validation differs across runs

---

## 19. Open Questions

- should string numeric values be coerced or rejected?
- should batch ingestion allow partial success?
- what sources are allowed in MVP?