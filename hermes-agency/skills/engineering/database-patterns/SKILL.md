---
name: database-patterns
description: Database schema design, query optimization, migrations, and data modeling best practices
tags: [engineering, database, sql, schema, migrations, postgres, optimization]
---

# Database Patterns

## When to Use
When designing database schemas, writing migrations, optimizing slow queries, choosing data models, or reviewing database-related code. This applies to relational (PostgreSQL, MySQL, SQLite) and document (MongoDB) databases, with emphasis on relational patterns.

## Prerequisites
- Understanding of the application's domain model and data requirements
- Access to the database and its schema files
- Knowledge of which database engine is used (PostgreSQL, MySQL, etc.)

## Steps

### Step 1: Design the Schema
Model entities and relationships before creating tables.

**Entity mapping template:**
```
## Entity: User
| Column       | Type         | Constraints              |
|-------------|-------------|--------------------------|
| id          | UUID        | PK, default gen_random_uuid() |
| email       | VARCHAR(255)| UNIQUE, NOT NULL         |
| name        | VARCHAR(100)| NOT NULL                 |
| status      | VARCHAR(20) | NOT NULL, default 'active' |
| created_at  | TIMESTAMPTZ | NOT NULL, default now()  |
| updated_at  | TIMESTAMPTZ | NOT NULL, default now()  |

## Relationships
- User 1:N Post (user_id FK on posts)
- User 1:1 Profile (user_id FK on profiles, UNIQUE)
- User N:M Role (via user_roles join table)
```

**Schema design rules:**
- Use UUIDs or ULIDs for primary keys (not auto-increment in distributed systems)
- Every table gets `created_at` and `updated_at` timestamps
- Use `TIMESTAMPTZ` (not `TIMESTAMP`) — always store timezone-aware times
- Use `VARCHAR(N)` or `TEXT` with check constraints, not `CHAR(N)`
- Prefer `BOOLEAN` for true/false, `ENUM` only for truly fixed sets
- Name tables plural (`users`), columns singular (`name`, `email`)
- Foreign keys: `user_id` referencing `users.id`

### Step 2: Write Migrations
Create reversible, safe migration files.

**Migration template (SQL):**
```sql
-- Migration: 001_create_users
-- Created: 2024-01-15

-- UP
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL,
    name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT users_email_unique UNIQUE (email),
    CONSTRAINT users_status_check CHECK (status IN ('active', 'inactive', 'suspended'))
);

CREATE INDEX idx_users_email ON users (email);
CREATE INDEX idx_users_status ON users (status) WHERE status != 'active';

-- DOWN
DROP TABLE IF EXISTS users;
```

**Migration rules:**
- Never modify a migration that has been applied to production
- Each migration is one atomic change (add column, create table, add index)
- Always write the DOWN/reverse migration
- Test migrations on a copy of production data before deploying
- For large tables, add columns with defaults in separate steps:
  1. Add column as nullable
  2. Backfill data
  3. Add NOT NULL constraint

### Step 3: Write Efficient Queries
Optimize common query patterns.

```sql
-- Use EXPLAIN ANALYZE to check query plans
EXPLAIN ANALYZE SELECT * FROM users WHERE email = 'alice@example.com';

-- Select only needed columns (not SELECT *)
SELECT id, name, email FROM users WHERE status = 'active';

-- Use indexes for WHERE and JOIN conditions
-- Partial index for common filtered queries
CREATE INDEX idx_active_users ON users (email) WHERE status = 'active';

-- Composite index for multi-column lookups
CREATE INDEX idx_posts_user_date ON posts (user_id, created_at DESC);

-- Use CTEs for complex queries (readability)
WITH recent_posts AS (
    SELECT user_id, count(*) as post_count
    FROM posts
    WHERE created_at > now() - interval '30 days'
    GROUP BY user_id
)
SELECT u.name, u.email, COALESCE(rp.post_count, 0) as recent_posts
FROM users u
LEFT JOIN recent_posts rp ON rp.user_id = u.id
WHERE u.status = 'active';

-- Avoid N+1: use JOIN or batch loading instead of queries in loops
-- BAD: loop { SELECT * FROM posts WHERE user_id = ? }
-- GOOD: SELECT * FROM posts WHERE user_id IN (1, 2, 3, ...)
```

### Step 4: Add Proper Indexes
Index strategy based on query patterns.

```sql
-- Check existing indexes
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename;

-- Check index usage
SELECT indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;

-- Check for missing indexes (slow queries)
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 20;

-- Index guidelines:
-- B-tree (default): equality, range, sorting
-- GIN: full-text search, JSONB containment
-- GiST: geometric, range types, nearest-neighbor
-- Partial: when you frequently filter on a condition
-- Expression: when you frequently use a function on a column
```

### Step 5: Implement Data Integrity
Enforce constraints at the database level.

```sql
-- Foreign keys with appropriate cascade behavior
ALTER TABLE posts
    ADD CONSTRAINT posts_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE;  -- or RESTRICT, SET NULL, SET DEFAULT

-- Check constraints for business rules
ALTER TABLE orders
    ADD CONSTRAINT orders_total_positive
    CHECK (total_amount >= 0);

-- Unique constraints (beyond primary keys)
ALTER TABLE user_emails
    ADD CONSTRAINT user_emails_email_unique
    UNIQUE (email);

-- NOT NULL for required fields
-- Default values for common cases
-- Triggers for complex validation (use sparingly)

-- Updated_at trigger (PostgreSQL)
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();
```

### Step 6: Review and Optimize
Regularly check database health.

```sql
-- Table bloat and dead tuples
SELECT schemaname, tablename, n_dead_tup, n_live_tup,
       round(n_dead_tup::numeric / GREATEST(n_live_tup, 1) * 100, 2) as dead_pct
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC;

-- Long-running queries
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE (now() - pg_stat_activity.query_start) > interval '5 minutes';

-- Table sizes
SELECT tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename))
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

## Tool Usage
- **terminal**: Run SQL queries, check query plans (EXPLAIN), manage migrations
- **file read**: Review schema files, migration scripts, ORM models
- **file write**: Create migration files, schema documentation
- **search_files**: Find existing models, migrations, and query patterns in code

## Pitfalls
1. **Don't use SELECT *** — always specify columns to avoid breaking when schema changes
2. **Don't store computed values** — calculate on read unless performance requires denormalization
3. **Don't skip foreign keys** — even with ORMs, enforce relationships at the database level
4. **Don't use auto-increment IDs in distributed systems** — use UUIDs or ULIDs
5. **Don't apply migrations without testing** — always test on production-like data first
6. **Don't ignore slow queries** — set up `pg_stat_statements` and monitor regularly

## Verification
- Schema has proper primary keys, foreign keys, and constraints on all tables
- Migrations are reversible and tested
- Common queries use appropriate indexes (verified with EXPLAIN ANALYZE)
- No N+1 query patterns in application code
- Updated_at triggers are in place for all user-facing tables

## Quick Reference
```
SCHEMA: UUID PKs | timestamps on every table | constraints at DB level
MIGRATIONS: One change per file | always write DOWN | test before prod
INDEXES: On WHERE/JOIN columns | partial for filtered queries | composite for multi-col
QUERIES: SELECT specific columns | EXPLAIN ANALYZE | avoid N+1
INTEGRITY: FKs | CHECK constraints | NOT NULL | defaults | triggers
```
