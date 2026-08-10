---
name: api-design-patterns
description: RESTful and GraphQL API design principles, conventions, and best practices
tags: [engineering, api, rest, graphql, http, design-patterns, openapi]
---

# API Design Patterns

## When to Use
When designing new API endpoints, reviewing existing API designs, refactoring APIs, or establishing API conventions for a project. This applies to REST, GraphQL, and hybrid API architectures.

## Prerequisites
- Understanding of HTTP methods and status codes
- Knowledge of the domain model and resources being exposed
- Access to existing API code or OpenAPI/GraphQL schema files

## Steps

### Step 1: Define Resources and Relationships
Map domain entities to API resources before writing any endpoints.

```
## Resource Map

| Resource     | Plural URL      | Relationships                    |
|-------------|-----------------|----------------------------------|
| User        | /users          | has many Posts, has one Profile   |
| Post        | /posts          | belongs to User, has many Comments|
| Comment     | /comments       | belongs to Post, belongs to User  |

## Naming Rules
- Resources are nouns, plural: /users not /user
- Relationships via nested routes: /users/123/posts
- Actions as sub-resources when not CRUD: /posts/123/publish
```

**Design the resource schema:**
```json
{
  "user": {
    "id": "string (UUID)",
    "email": "string",
    "name": "string",
    "created_at": "ISO 8601 timestamp",
    "updated_at": "ISO 8601 timestamp",
    "_links": {
      "self": "/users/123",
      "posts": "/users/123/posts"
    }
  }
}
```

### Step 2: Map CRUD to HTTP Methods and Status Codes
Standard mapping for every resource:

| Operation | Method | URL | Status Code | Body |
|-----------|--------|-----|-------------|------|
| Create | POST | /resources | 201 Created | New resource |
| Read all | GET | /resources | 200 OK | Array + pagination |
| Read one | GET | /resources/:id | 200 OK | Single resource |
| Update (full) | PUT | /resources/:id | 200 OK | Updated resource |
| Update (partial) | PATCH | /resources/:id | 200 OK | Updated resource |
| Delete | DELETE | /resources/:id | 204 No Content | Empty |

**Error status codes:**
| Code | Meaning | When to Use |
|------|---------|-------------|
| 400 | Bad Request | Validation error, malformed input |
| 401 | Unauthorized | Missing or invalid authentication |
| 403 | Forbidden | Authenticated but not permitted |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Duplicate, version conflict |
| 422 | Unprocessable | Valid syntax but semantic error |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Error | Unexpected server error |

### Step 3: Design Consistent Request/Response Formats
Establish a standard envelope for all API responses.

**Success response:**
```json
{
  "data": {
    "id": "123",
    "type": "user",
    "attributes": { "name": "Alice", "email": "alice@example.com" }
  },
  "meta": {
    "request_id": "req_abc123"
  }
}
```

**List response with pagination:**
```json
{
  "data": [...],
  "meta": {
    "total": 100,
    "page": 1,
    "per_page": 20,
    "request_id": "req_abc123"
  },
  "links": {
    "self": "/users?page=1",
    "next": "/users?page=2",
    "last": "/users?page=5"
  }
}
```

**Error response:**
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The request body is invalid",
    "details": [
      { "field": "email", "message": "must be a valid email address" },
      { "field": "name", "message": "must be between 1 and 100 characters" }
    ]
  },
  "meta": { "request_id": "req_abc123" }
}
```

### Step 4: Implement Filtering, Sorting, and Pagination
Standard query parameter conventions.

```
# Filtering
GET /users?status=active
GET /users?created_after=2024-01-01&role=admin

# Sorting
GET /users?sort=name           # ascending
GET /users?sort=-created_at    # descending (prefix with -)
GET /users?sort=-created_at,name  # multiple fields

# Pagination (cursor-based preferred for large datasets)
GET /users?limit=20&cursor=abc123      # cursor-based
GET /users?page=2&per_page=20          # offset-based (simpler but less robust)

# Field selection
GET /users?fields=id,name,email         # sparse fieldsets
GET /users?include=posts,profile        # related resources (JSON:API style)
```

### Step 5: Version the API
Choose a versioning strategy and apply it consistently.

```
# URL path versioning (most visible, easiest to route)
GET /v1/users
GET /v2/users

# Header versioning (cleaner URLs)
GET /users
Accept: application/vnd.myapi.v2+json

# Query parameter (least preferred)
GET /users?version=2
```

**Versioning rules:**
- Never break v1 — add new fields freely, but never remove or rename
- Deprecate with headers: `Deprecation: true`, `Sunset: Sat, 01 Jan 2026 00:00:00 GMT`
- Document migration path between versions

### Step 6: Write the OpenAPI Specification
Document the API contract.

```yaml
openapi: 3.1.0
info:
  title: My API
  version: 1.0.0
paths:
  /users:
    get:
      summary: List users
      parameters:
        - name: status
          in: query
          schema:
            type: string
            enum: [active, inactive]
        - name: sort
          in: query
          schema:
            type: string
        - name: limit
          in: query
          schema:
            type: integer
            default: 20
            maximum: 100
      responses:
        '200':
          description: List of users
          content:
            application/json:
              schema:
                type: object
                properties:
                  data:
                    type: array
                    items:
                      $ref: '#/components/schemas/User'
    post:
      summary: Create a user
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateUser'
      responses:
        '201':
          description: User created
        '422':
          description: Validation error
```

## Tool Usage
- **file read**: Examine existing API code, OpenAPI specs, and route definitions
- **search_files**: Find existing endpoints, middleware, and validation logic
- **terminal**: Run API tests with curl, httpie, or test frameworks
- **file write**: Create or update OpenAPI specifications and API documentation

## Pitfalls
1. **Don't use verbs in URLs** — `/getUser` should be `GET /users/:id`
2. **Don't return 200 for errors** — use appropriate 4xx/5xx status codes
3. **Don't expose internal IDs or database structure** — use UUIDs, abstract the data layer
4. **Don't ignore pagination** — unbounded list responses will break clients
5. **Don't make breaking changes without versioning** — clients depend on the contract
6. **Don't use inconsistent casing** — pick snake_case or camelCase and stick with it (snake_case for URLs, camelCase for JSON bodies is common)

## Verification
- All endpoints follow the standard method/status mapping
- Error responses use the standard envelope format
- API is documented in OpenAPI 3.x specification
- Pagination works correctly with edge cases (empty results, last page)
- Versioning strategy is implemented and documented
- No sensitive data exposed in responses (passwords, tokens, internal fields)

## Quick Reference
```
RESOURCE DESIGN:
  Nouns, plural: /users, /posts, /comments
  Nest for ownership: /users/123/posts
  Actions as sub-resources: /posts/123/publish

HTTP METHODS: GET (read) | POST (create) | PUT/PATCH (update) | DELETE (remove)
STATUS: 200 OK | 201 Created | 204 No Content | 400 Bad Request | 404 Not Found | 422 Unprocessable

QUERY: ?status=active&sort=-created_at&limit=20&cursor=abc123
VERSION: /v1/ prefix (never break, deprecate with headers)
