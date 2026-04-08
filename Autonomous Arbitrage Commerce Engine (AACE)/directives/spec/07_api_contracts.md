# AACE MVP API Contracts

## 1. Purpose

This document defines the API contract for the AACE MVP.

It specifies:

- available endpoints,
- access control requirements,
- request and response expectations,
- error handling rules,
- contract consistency requirements.

This is a behavior contract, not an implementation guide.

---

## 2. API Principles

All APIs must be:

- deterministic
- secure
- role-aware
- auditable
- consistent

Every endpoint must clearly define:

- purpose
- access level
- request shape
- response shape
- failure behavior

---

## 3. Base Conventions

### 3.1 Base Path
```

/api/v1/

````

---

### 3.2 Data Format
- JSON for all requests/responses
- No implicit structures

---

### 3.3 Authentication

Protected endpoints require authentication.

---

### 3.4 Authorization Roles

- admin
- manager
- user

---

### 3.5 Response Format

#### Success
```json
{
  "success": true,
  "data": {},
  "meta": {}
}
````

#### Error

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Readable message"
  }
}
```

---

## 4. Authentication Endpoints

### 4.1 Login

```
POST /api/v1/auth/login
```

**Access:** Public
**Purpose:** Authenticate user

**Request:**

```json
{
  "email": "string",
  "password": "string"
}
```

**Response:**

* authenticated user context
* session/token

---

### 4.2 Logout

```
POST /api/v1/auth/logout
```

**Access:** Authenticated
**Purpose:** End session

---

### 4.3 Current User

```
GET /api/v1/auth/me
```

**Access:** Authenticated

**Response:**

```json
{
  "id": "string",
  "role": "user|manager|admin"
}
```

---

## 5. Admin User Management

### 5.1 List Users

```
GET /api/v1/admin/users
```

**Access:** Admin

---

### 5.2 Create User

```
POST /api/v1/admin/users
```

**Access:** Admin

---

### 5.3 Update User

```
PATCH /api/v1/admin/users/{userId}
```

**Access:** Admin

---

## 6. Ingestion API

### 6.1 Ingest Product Data

```
POST /api/v1/ingestion/products
```

**Access:** Authenticated

**Purpose:** Submit product + listing data

**Behavior:**

* validates input
* normalizes data
* stores records

---

## 7. Product APIs

### 7.1 List Products

```
GET /api/v1/products
```

**Access:** Authenticated

---

### 7.2 Get Product

```
GET /api/v1/products/{productId}
```

---

### 7.3 Product Listings

```
GET /api/v1/products/{productId}/listings
```

---

## 8. Observations API

### 8.1 List Observations

```
GET /api/v1/observations
```

---

### 8.2 Observation Detail

```
GET /api/v1/observations/{id}
```

---

## 9. Opportunity APIs

### 9.1 List Opportunities

```
GET /api/v1/opportunities
```

**Response includes:**

* id
* score
* discrepancy summary
* timestamps

---

### 9.2 Opportunity Detail

```
GET /api/v1/opportunities/{id}
```

---

### 9.3 Update Opportunity

```
PATCH /api/v1/opportunities/{id}
```

**Purpose:** Update status

---

## 10. Reporting APIs

### 10.1 Opportunity Summary

```
GET /api/v1/reports/opportunities/summary
```

---

### 10.2 Ingestion Summary

```
GET /api/v1/reports/ingestion/summary
```

---

## 11. Audit APIs

### 11.1 Audit Events

```
GET /api/v1/audit/events
```

**Access:** Admin

---

## 12. Health Endpoint

```
GET /api/v1/health
```

---

## 13. Error Codes

* UNAUTHORIZED
* FORBIDDEN
* VALIDATION_ERROR
* NOT_FOUND
* CONFLICT
* INTERNAL_ERROR

---

## 14. Status Codes

* 200 OK
* 201 Created
* 400 Bad Request
* 401 Unauthorized
* 403 Forbidden
* 404 Not Found
* 500 Internal Error

---

## 15. Contract Rules

* No hidden behavior
* No implicit data mutation
* All write operations must be auditable
* All protected routes must enforce auth
* No sensitive data leakage

---

## 16. MVP Limits

The API must NOT include:

* auto purchasing
* repricing automation
* external marketplace execution
* uncontrolled AI endpoints

---

## 17. Open Questions

* API-first vs dashboard-first?
* Sync vs async ingestion?
* Required opportunity statuses?