---
name: django-api-full-audit
description: Perform a comprehensive, evidence-based audit of an entire Django/DRF API codebase. Inventory every endpoint, trace request-to-database execution paths, analyze architecture, authentication/authorization, validation, business rules, transactions, ORM usage, performance, security, API correctness, documentation, observability, configuration, dependencies, migrations, backwards compatibility, dead code, and test coverage. Produce a complete audit report with endpoint-level findings, cross-cutting findings, risk severity, evidence, and prioritized remediation actions. Do not assume behavior from filenames or conventions; verify it from executable code, routing, serializers, services, models, permissions, settings, and tests.
---

# Django API Full Audit Skill

## Role

Act as a senior Django + Django REST Framework (DRF) backend architect, API security reviewer, database/ORM reviewer, reliability engineer, and test strategist.

Your job is to analyze the **entire API surface and the complete execution path behind it**.

Do not perform a shallow code review.

Do not judge a feature as implemented merely because:
- an endpoint exists,
- a serializer exists,
- a model exists,
- Swagger/OpenAPI lists it,
- a test name suggests coverage,
- a TODO says it is planned,
- or the code "looks correct."

Every important conclusion must be supported by concrete code evidence.

---

# Primary Objective

Determine whether the Django API is:

1. Functionally correct
2. Architecturally coherent
3. Secure
4. Correctly authenticated and authorized
5. Correctly validated
6. Transaction-safe
7. Consistent in API behavior
8. Efficient at the database and application layers
9. Correct under concurrency and retries
10. Properly tested
11. Properly documented
12. Observable and operable
13. Maintainable
14. Free of obsolete/duplicated domain logic
15. Safe to evolve without breaking existing clients

The final audit must explain not only **what is wrong**, but also:
- where it is,
- why it matters,
- how the behavior currently works,
- what evidence proves the finding,
- what could break,
- and what concrete remediation is appropriate.

---

# Core Audit Principle

## Evidence over assumptions

For every meaningful conclusion, trace the implementation.

Preferred evidence chain:

`URL/router → view/viewset → authentication → permission → serializer → service/use-case → model/queryset → database constraints → side effects → response → tests`

When applicable also trace:

`settings → middleware → exception handler → throttling → pagination/filtering → caching → signals → tasks → external services → logs/metrics`

If behavior is unclear, mark it as:

`UNKNOWN — requires runtime verification`

Never silently infer behavior.

---

# Scope

Inspect the complete project, including where relevant:

- Django apps
- DRF endpoints
- routers
- URLConfs
- API versions
- function-based views
- APIView
- GenericAPIView
- ViewSets
- ModelViewSets
- mixins
- serializers
- serializer fields
- validators
- permissions
- authentication classes
- throttling
- filters
- pagination
- renderers/parsers
- exception handlers
- services
- use-case/application layers
- domain logic
- model managers/querysets
- models
- database constraints
- indexes
- migrations
- signals
- Celery/tasks
- management commands
- scheduled jobs
- external integrations
- email/SMS/payment providers
- storage
- cache
- Redis
- configuration
- settings
- environment handling
- middleware
- logging
- audit logging
- OpenAPI/schema configuration
- tests
- fixtures/factories
- test utilities
- CI configuration
- dependency versions
- Docker/container configuration
- deployment-related API configuration

Also inspect code that is not directly reachable from an endpoint but can affect API behavior.

---

# Phase 1 — Repository Reconnaissance

Before making API conclusions, build a project map.

## Identify

- Django project package
- settings modules
- environment-specific settings
- installed apps
- middleware
- root URL configuration
- API URL modules
- every Django app
- every API version
- every API namespace
- serializers
- views/viewsets
- services
- models
- permissions
- authentication
- tests
- OpenAPI configuration
- task queues
- external integrations
- database configuration
- cache configuration

## Detect

- duplicated settings
- duplicated business logic
- legacy apps
- legacy models
- deprecated endpoints
- compatibility layers
- dead modules
- unused serializers
- unused permissions
- abandoned API versions
- duplicate routes
- conflicting endpoint implementations

Do not remove code during analysis unless explicitly instructed.

---

# Phase 2 — Build a Complete Endpoint Inventory

Create an exhaustive inventory from actual Django routing.

Inspect:

- `urlpatterns`
- `include(...)`
- DRF routers
- `DefaultRouter`
- `SimpleRouter`
- nested routers
- manually registered routes
- `@api_view`
- custom `as_view()`
- custom actions
- versioning
- namespaced URLs

For every endpoint record:

| Field | Required |
|---|---|
| HTTP method | Yes |
| URL/path | Yes |
| Name/route name | Yes |
| API version | Yes |
| App | Yes |
| View/ViewSet | Yes |
| Action | Yes |
| Authentication | Yes |
| Permission classes | Yes |
| Serializer(s) | Yes |
| Request schema | Yes |
| Response schema | Yes |
| Database models touched | Yes |
| Services called | Yes |
| External calls | Yes |
| Side effects | Yes |
| Transaction boundary | Yes |
| Pagination/filtering | If applicable |
| Throttling | If applicable |
| Expected status codes | Yes |
| Error behavior | Yes |
| Tests | Yes |
| Documentation | Yes |
| Risk notes | Yes |

Do not rely solely on OpenAPI to create this inventory.

The routing code is the source of truth for reachability.

---

# Phase 3 — Trace Every Endpoint End-to-End

For each endpoint, follow the complete execution path.

## Request path

Analyze:

1. URL resolution
2. middleware
3. authentication
4. permission checks
5. throttling
6. parser
7. input validation
8. serializer
9. view logic
10. service/use-case logic
11. model operations
12. external integrations
13. transactions
14. signals
15. tasks/background work
16. response serialization
17. exception transformation
18. logging/auditing

## Identify

- duplicated validation
- validation in wrong layers
- business rules inside serializers
- business rules inside views
- business rules hidden inside signals
- service logic bypassed by direct model writes
- multiple paths producing the same domain state
- unexpected side effects
- hidden writes
- implicit database queries
- implicit network calls
- inconsistent response behavior

---

# Phase 4 — HTTP/API Contract Audit

Check every endpoint for correct API semantics.

## HTTP methods

Verify that:

- GET does not mutate state unexpectedly
- POST is used for creation/actions where appropriate
- PUT behaves as full replacement where claimed
- PATCH behaves as partial update where claimed
- DELETE semantics are explicit
- custom actions have consistent semantics

## Status codes

Audit correctness and consistency of:

- 200
- 201
- 202
- 204
- 400
- 401
- 403
- 404
- 409
- 422 where intentionally used
- 429
- 500
- other project-specific codes

Find cases where identical failures produce different status codes across endpoints.

## Response contract

Check:

- shape consistency
- field naming
- nullability
- date/time format
- Decimal/money serialization
- IDs
- nested resource behavior
- error structure
- pagination structure
- metadata
- ordering
- backwards compatibility

Flag accidental contract drift.

---

# Phase 5 — Authentication Audit

Analyze all authentication mechanisms.

Possible mechanisms include:

- JWT
- SessionAuthentication
- TokenAuthentication
- OAuth2/OIDC
- API keys
- custom authentication
- service-to-service authentication
- cookie authentication

Check:

- token lifetime
- refresh behavior
- rotation
- revocation strategy
- logout semantics
- cookie security
- CSRF implications
- Authorization header handling
- anonymous endpoint exposure
- authentication precedence
- failure behavior
- user deactivation handling
- staff/admin authentication
- service credentials
- secret management

Look for:

- endpoints accidentally accessible anonymously
- weak authentication fallback
- inconsistent auth classes
- token configuration mismatch
- insecure cookies
- credentials in source control/logs
- authentication checks performed too late

Never assume authentication is correct because JWT or another package is installed.

---

# Phase 6 — Authorization and Object-Level Access Control

For every protected endpoint determine:

`Who can call it?`

Then determine:

`Which objects can they access?`

Audit:

- IsAuthenticated
- IsAdminUser
- custom permissions
- role-based access
- ownership checks
- organization/tenant checks
- staff restrictions
- object-level permissions
- queryset filtering
- serializer field restrictions
- action-specific permissions

Explicitly test conceptually for:

- IDOR/BOLA
- privilege escalation
- horizontal privilege escalation
- vertical privilege escalation
- cross-tenant access
- unauthorized update
- unauthorized delete
- unauthorized state transitions

Critical rule:

A permission that checks only authentication does **not** prove object authorization.

Trace object access all the way to the queryset/object retrieval and mutation.

---

# Phase 7 — Serializer and Validation Audit

For every serializer inspect:

- field inclusion
- read-only fields
- write-only fields
- required fields
- defaults
- null handling
- blank handling
- custom validation
- `validate()`
- `validate_<field>()`
- create/update behavior
- hidden fields
- `source=`
- nested serializers
- writable nested serializers
- model serializer defaults
- error messages
- field leakage

Find:

- writable fields that should be immutable
- sensitive fields exposed in responses
- client-controlled ownership fields
- client-controlled status fields
- client-controlled financial totals
- trusting derived values
- missing cross-field validation
- validation dependent on stale state
- inconsistent validation across endpoints

Security-sensitive values should generally be derived from trusted server-side state rather than blindly accepted from clients.

---

# Phase 8 — Business Logic Audit

Map important business invariants.

Examples:

- lifecycle state transitions
- financial rules
- booking rules
- inventory rules
- payout rules
- refund rules
- cancellation rules
- permissions
- limits
- uniqueness
- timing constraints
- eligibility rules

For every invariant determine:

1. Where is it enforced?
2. Is it enforced in one place or multiple places?
3. Can another endpoint bypass it?
4. Is it enforced transactionally?
5. Is it enforced by the database where appropriate?
6. Does retrying the request break it?
7. Can concurrent requests violate it?

Flag "business logic fragmentation."

A critical invariant should not exist only in one endpoint if another write path can bypass it.

---

# Phase 9 — State Machine and Lifecycle Audit

For every domain entity with statuses, build a transition table.

Example:

`PENDING → CONFIRMED → COMPLETED`

Also identify:

- cancellation transitions
- refund transitions
- failure transitions
- reactivation transitions
- invalid backward transitions

For each transition determine:

- who may trigger it
- required preconditions
- database changes
- side effects
- idempotency behavior
- transaction boundary
- emitted events/tasks
- audit logging

Flag:

- arbitrary status updates
- status exposed as writable serializer field
- missing transition validation
- duplicate transition logic
- transitions that can be skipped
- state transitions that are not atomic

---

# Phase 10 — Database and ORM Audit

Inspect every important query path.

Check for:

- N+1 queries
- missing `select_related`
- missing `prefetch_related`
- unnecessary joins
- unnecessary model hydration
- repeated count queries
- repeated existence checks
- inefficient annotations
- unbounded querysets
- large `IN` clauses
- accidental full-table scans
- Python-side filtering instead of DB filtering
- unnecessary `save()`
- repeated serialization queries
- hidden queries in properties/methods
- query duplication

Analyze:

- indexes
- unique constraints
- check constraints
- foreign keys
- on_delete behavior
- nullable relations
- ordering
- database-level enforcement
- migration quality

For hot paths, reason about query count and query shape.

Where project tooling allows it, use:

- Django `assertNumQueries`
- `QuerySet.explain()`
- database query plans
- profiling
- request benchmarking

Do not claim a performance problem without evidence or a clear query-path explanation.

---

# Phase 11 — Transaction and Concurrency Audit

Audit every multi-write operation.

Look for:

- `transaction.atomic`
- nested transactions
- `select_for_update`
- unique constraints
- race conditions
- check-then-act logic
- duplicate creation
- inventory races
- balance races
- payout races
- double-refund scenarios
- concurrent booking collisions

Typical dangerous pattern:

```python
if not Model.objects.filter(...).exists():
    Model.objects.create(...)
```

Determine whether concurrent requests can both pass the check.

For financial or irreversible operations, explicitly inspect:

- atomicity
- idempotency
- retry safety
- lock strategy
- consistency after partial failure

---

# Phase 12 — Idempotency Audit

Identify endpoints where retries must not create duplicate effects.

Examples:

- payments
- refunds
- booking creation
- webhooks
- payout generation
- inventory deductions
- external API calls
- emails/messages with financial consequences

For each relevant endpoint determine:

- whether an idempotency key exists
- where it is stored
- whether uniqueness is enforced
- whether concurrent duplicates are prevented
- whether a repeated request returns the original result
- whether partial failures can create duplicates

Do not treat "frontend won't retry" as an idempotency strategy.

---

# Phase 13 — Financial and Money Handling Audit

When money or financial state exists, inspect it separately.

Check:

- Decimal vs float
- currency representation
- precision
- rounding
- currency conversion
- totals
- taxes/discounts
- client-supplied totals
- payment splitting
- refunds
- sale/payment relationships
- accounting state
- balance calculations
- payout calculations
- atomicity
- audit trail
- immutable financial records
- reconciliation

Verify that server-side calculations derive authoritative totals from trusted source data.

Look for:

- floating-point arithmetic
- trust in client totals
- mutable historical transactions
- orphan payments
- orphan sales
- duplicate financial records
- refund overpayment
- partial-payment inconsistencies

---

# Phase 14 — Security Audit

Perform a Django/DRF-focused security review aligned with the current OWASP web/API threat landscape.

At minimum inspect for:

- broken access control
- authentication weaknesses
- object-level authorization failures
- injection risks
- SQL injection
- command injection
- template injection
- unsafe deserialization
- XSS
- CSRF
- SSRF
- insecure file uploads
- path traversal
- mass assignment
- sensitive data exposure
- excessive data exposure
- security misconfiguration
- rate-limit weaknesses
- business logic abuse
- unsafe redirects
- weak password handling
- secret leakage
- debug leakage
- insecure CORS
- insecure cookie configuration
- insecure headers
- unsafe URL fetching
- unsafe redirects
- unrestricted resource consumption
- denial-of-service vectors
- dependency vulnerabilities

## Django-specific checks

Inspect:

- `DEBUG`
- `SECRET_KEY`
- `ALLOWED_HOSTS`
- `CSRF_*`
- `SESSION_*`
- `SECURE_*`
- `CORS_*`
- password hashing
- session settings
- CSRF middleware
- security middleware
- clickjacking protection
- HSTS
- proxy/secure header configuration
- file upload validation
- media access
- admin exposure
- browsable API exposure
- serializer over-posting
- ORM raw SQL usage
- `extra()`
- unsafe `RawSQL`
- shell/subprocess execution
- `mark_safe`
- `safe`
- template rendering
- `eval`
- `exec`
- pickle
- unsafe YAML loading
- unsafe object deserialization

Never assume the ORM eliminates all injection risks. Inspect raw queries and dynamic SQL construction.

---

# Phase 15 — API Abuse and Resource Exhaustion

Audit for abuse cases such as:

- unbounded list endpoints
- missing pagination
- huge page sizes
- expensive search
- regex search without limits
- expensive sorting
- unrestricted file sizes
- repeated expensive validation
- bulk endpoints without limits
- recursive/nested payload abuse
- expensive annotations
- expensive exports
- expensive reports
- brute force login
- password reset abuse
- OTP abuse
- webhook abuse

Check throttling where appropriate.

---

# Phase 16 — Filtering, Searching, Ordering, and Pagination

For every list endpoint inspect:

- pagination
- maximum page size
- default ordering
- user-controlled ordering
- allowed filter fields
- search fields
- regex behavior
- date-range filters
- numeric range filters
- filter authorization
- tenant/ownership restrictions

Flag cases where clients can use filtering/search parameters to bypass authorization or cause expensive queries.

---

# Phase 17 — File Upload and Download Audit

Where files exist, inspect:

- content type validation
- extension validation
- magic-byte/content verification
- file size limits
- storage backend
- generated filenames
- path traversal protection
- executable file risks
- SVG risks
- archive risks
- direct/public access
- authorization on downloads
- signed URLs
- media URL leakage
- image processing
- PDF processing
- antivirus scanning where appropriate

Do not equate filename extension with content validation.

---

# Phase 18 — External Services and Integrations

Trace every external call.

Examples:

- payment providers
- email
- SMS
- storage
- identity/KYC services
- analytics
- maps
- webhooks
- third-party APIs

For each integration inspect:

- timeout
- retry
- backoff
- idempotency
- authentication
- secret handling
- response validation
- failure behavior
- transaction interaction
- circuit breaking where appropriate
- logging
- sensitive data transmission
- SSRF implications
- webhook verification

Pay special attention to database writes combined with external network calls.

---

# Phase 19 — Signals and Hidden Side Effects

Inspect:

- `post_save`
- `pre_save`
- `post_delete`
- `m2m_changed`
- custom model methods
- overridden `save()`
- overridden `delete()`

Determine whether important behavior is hidden in signals.

Flag cases where:

- creating a model unexpectedly creates financial records
- saving triggers external calls
- deletes cause hidden cascades
- signals perform non-idempotent operations
- signal behavior is difficult to discover from the endpoint

For critical business operations, clearly document hidden side effects.

---

# Phase 20 — Async Tasks and Background Processing

Inspect Celery/tasks/job queues.

For every task determine:

- trigger
- input
- retry policy
- max retries
- idempotency
- transaction coordination
- duplicate execution safety
- timeouts
- failure handling
- observability
- dead-letter/recovery strategy where applicable

Look for database state being assumed to exist after asynchronous scheduling.

---

# Phase 21 — Error Handling

Audit:

- DRF exception handling
- custom exception handlers
- validation errors
- business exceptions
- permission errors
- not-found behavior
- conflict handling
- external-service failures
- database integrity errors
- unexpected exceptions

Verify that:

- internal stack traces are not exposed
- secrets are not exposed
- database details are not leaked
- errors have stable schemas
- clients can distinguish validation/auth/conflict/server failures
- expected domain errors are not returned as generic 500s

---

# Phase 22 — Logging, Auditability, and Observability

Inspect:

- structured logging
- request IDs/correlation IDs
- security logging
- audit logs
- error tracking
- metrics
- latency tracking
- database query monitoring
- authentication failures
- permission denials
- financial events

Flag:

- passwords/tokens/secrets in logs
- sensitive personal data in logs
- missing audit trail for critical financial/state changes
- inconsistent request identifiers
- logs that cannot correlate a failure across services

---

# Phase 23 — OpenAPI / Documentation Audit

Compare actual implementation against API documentation.

Check:

- every route documented
- every documented route still exists
- HTTP methods match
- request bodies match
- required fields match
- response schemas match
- status codes match
- authentication requirements match
- examples are valid
- deprecated routes are marked
- API versioning is clear

Important:

**Implementation is the source of truth for reachability.**

Documentation is a contract artifact that must not contradict it.

---

# Phase 24 — Testing Audit

Do not merely count tests.

Map tests to the API inventory.

For every endpoint identify:

- unit tests
- serializer tests
- permission tests
- integration/API tests
- database tests
- security tests
- business-rule tests
- edge-case tests
- concurrency tests where required
- performance tests where required

Build a matrix:

| Endpoint | Happy path | Validation | Auth | Authorization | Edge cases | DB | Security | Regression | Performance |
|---|---|---|---|---|---|---|---|---|---|

Look for:

- endpoints with no tests
- status transitions with no tests
- permission branches with no tests
- serializers with no negative tests
- financial operations with weak coverage
- tests that mock away the behavior they claim to verify
- tests that do not assert database state
- missing transaction tests
- missing idempotency tests
- missing object-level authorization tests
- missing regression tests for past bugs

If coverage tooling is available, inspect actual coverage.

Do not equate line coverage with behavioral coverage.

---

# Phase 25 — Test Quality Audit

Inspect whether tests are trustworthy.

Check for:

- meaningful assertions
- false-positive tests
- excessive mocking
- brittle fixtures
- shared mutable state
- missing isolation
- hidden dependencies
- nondeterminism
- time-dependent failures
- race-condition blindness
- untested error branches

A passing test that never asserts the important outcome is not meaningful coverage.

---

# Phase 26 — Architecture Audit

Determine whether the API has a coherent architecture.

Analyze separation between:

- presentation layer
- API layer
- validation layer
- application/service layer
- domain logic
- persistence layer
- integrations

Look for:

- fat views
- fat serializers
- fat models
- duplicated services
- circular dependencies
- business logic in URL/view plumbing
- direct DB writes from multiple unrelated layers
- domain logic hidden in signals
- inconsistent service usage
- architecture drift between apps

Do not enforce a particular architecture for stylistic reasons. Judge whether the current architecture remains understandable, testable, and safe.

---

# Phase 27 — Legacy / Duplication / Dead-Code Audit

Search for:

- duplicate models
- duplicate serializers
- duplicate payment concepts
- legacy database fields
- obsolete endpoints
- compatibility wrappers
- old APIs still reachable
- old permissions
- duplicate service functions
- migration leftovers
- comments contradicting implementation
- unused dependencies
- unused settings
- dead code paths

For each suspected legacy item determine whether it is:

- actually unused
- still reachable
- referenced by tests
- required for migrations
- required by external clients
- safe to remove

Never recommend deletion solely because something "looks old."

---

# Phase 28 — Dependency and Configuration Audit

Inspect:

- `requirements.txt`
- `pyproject.toml`
- lock files
- Django/DRF versions
- security-sensitive packages
- authentication packages
- database packages
- task packages

Look for:

- outdated dependencies
- incompatible package versions
- duplicate packages
- unused dependencies
- risky packages
- insecure configuration defaults

Where security tools are available, run or inspect:

- `pip-audit`
- package vulnerability scanners
- Bandit
- Ruff
- other project-defined static analysis

Do not claim a dependency is vulnerable without evidence from project tooling or authoritative vulnerability data.

---

# Phase 29 — Migration and Data Integrity Audit

Inspect all relevant migrations.

Look for:

- schema drift
- missing constraints
- unsafe data migrations
- non-atomic migrations
- table locks
- destructive operations
- default-value problems
- nullable/blank inconsistencies
- duplicate/index issues
- migration order problems

For important invariants, prefer database-level constraints where practical.

---

# Phase 30 — Performance Audit

Analyze at three levels.

## API level

- response latency
- pagination
- serialization cost
- repeated work
- response size

## Application level

- loops over querysets
- repeated function calls
- inefficient transformations
- expensive Python computation
- repeated external requests

## Database level

- N+1
- indexes
- query plans
- joins
- aggregations
- sorts
- full-table scans
- lock contention

Where runtime tools are available, measure before declaring a bottleneck.

---

# Phase 31 — Reliability Audit

Check:

- timeouts
- retries
- idempotency
- atomic transactions
- partial failures
- external dependency failures
- database failures
- cache failures
- queue failures
- duplicate requests
- repeated webhooks
- service restarts
- deployment migration safety

Pay special attention to operations that cannot safely be repeated.

---

# Phase 32 — Compatibility and API Evolution

Inspect:

- versioning strategy
- deprecation policy
- backwards compatibility
- field removals
- status code changes
- response shape changes
- route changes
- serializer behavior changes
- database migration compatibility
- old clients

Flag breaking changes that are undocumented or unsupported.

---

# Phase 33 — Endpoint Risk Model

Each endpoint should receive a **risk classification**, not a subjective quality score.

Use categories:

- CRITICAL
- HIGH
- MEDIUM
- LOW
- INFO

Risk must be based on evidence and potential impact.

Examples:

### CRITICAL
- unauthenticated access to sensitive financial/user data
- arbitrary privilege escalation
- double-payment/refund vulnerability
- destructive action without authorization

### HIGH
- IDOR/BOLA
- race condition affecting money/inventory
- serious sensitive-data exposure
- missing transaction boundaries in critical workflows
- exploitable injection

### MEDIUM
- missing pagination on non-critical endpoint
- inconsistent error semantics
- N+1 query with bounded dataset
- missing negative test coverage

### LOW / INFO
- documentation inconsistency
- minor naming inconsistency
- non-critical refactoring opportunity

Never assign severity based on aesthetics alone.

---

# Phase 34 — Evidence Format

Every finding must use this structure:

```text
Finding:
[precise problem]

Severity:
[CRITICAL/HIGH/MEDIUM/LOW/INFO]

Location:
[file:line or symbol]

Affected Endpoint(s):
[exact routes]

Evidence:
[what the code actually does]

Impact:
[what can go wrong]

Attack/Failure Scenario:
[concrete example]

Root Cause:
[architectural or implementation cause]

Recommended Remediation:
[specific fix]

Regression Test:
[test that should prove the fix]

Confidence:
[HIGH/MEDIUM/LOW]
```

Never report a vague finding such as:

> "Security could be improved."

Be specific.

---

# Phase 35 — Special Endpoint Classes

Give additional scrutiny to:

## Authentication

- login
- logout
- refresh
- password reset
- password change
- OTP
- registration
- email/phone verification

## User/Profile

- profile
- account settings
- identity data
- credentials

## Administrative

- staff
- admin
- employee management
- impersonation
- configuration

## Financial

- checkout
- payments
- refunds
- sales
- payouts
- balances
- wallets
- invoices

## State-changing actions

- confirm
- complete
- cancel
- approve
- reject
- activate
- deactivate
- archive

## Bulk endpoints

- bulk update
- bulk delete
- imports
- exports

## File endpoints

- upload
- download
- document processing

## External/webhook endpoints

- provider callbacks
- payment webhooks
- inbound integrations

---

# Phase 36 — Cross-Endpoint Consistency Audit

After endpoint-level analysis, compare the whole API.

Look for inconsistent:

- authentication
- permissions
- naming
- status codes
- validation
- error response schemas
- pagination
- filtering
- date formats
- currency formats
- IDs
- serializer patterns
- transaction behavior
- service usage
- logging
- audit behavior

Important:

A single endpoint can appear correct while the API as a whole is inconsistent and bypassable.

---

# Phase 37 — Build Domain Workflow Maps

For major workflows, reconstruct the actual lifecycle.

Example:

```text
Reserve
  ↓
Pending
  ↓
Confirm
  ↓
Completed
  ↓
Checkout
  ↓
Sale + Payment
```

Then verify every alternate path:

```text
Pending → Cancel
Confirmed → Cancel
Completed → Refund
Checkout retry → ?
Checkout failure → ?
Refund retry → ?
```

For every path ask:

- Can the path happen twice?
- Can it happen out of order?
- Can another endpoint bypass it?
- Is it atomic?
- Is it authorized?
- Is it audited?
- Is it tested?

---

# Phase 38 — Legacy Side-Effect Detection

Explicitly search for side effects that may indicate architectural duplication.

Examples:

- finance operation also writes customer-domain records
- customer operation creates finance records unexpectedly
- signal creates unrelated domain records
- serializer save creates financial entities
- model save triggers external API calls
- endpoint silently mutates inventory
- deletion causes hidden financial effects

For each one document:

```text
Source operation
→ hidden side effect
→ target model
→ whether intentional
→ whether duplicated
→ whether tested
→ whether removable
```

---

# Phase 39 — Automated Verification

Use repository tooling where available.

Potential commands:

```bash
python manage.py check
python manage.py show_urls
python manage.py test
pytest
pytest --cov
ruff check .
bandit -r .
pip-audit
```

Also use targeted inspection/search for:

```text
APIView
ViewSet
ModelViewSet
@api_view
router.register
urlpatterns
permission_classes
authentication_classes
serializer_class
get_queryset
perform_create
perform_update
transaction.atomic
select_for_update
select_related
prefetch_related
RawSQL
cursor(
save(
delete(
post_save
pre_save
m2m_changed
requests.
httpx.
urllib
subprocess
os.system
eval(
exec(
mark_safe
csrf_exempt
AllowAny
IsAuthenticated
```

Do not run destructive commands.

Do not change production data.

Do not call real external payment or production APIs.

Use safe/read-only analysis whenever possible.

---

# Phase 40 — Runtime Verification

When a local test environment exists, verify critical claims with executable checks.

Preferred verification techniques:

- Django test client
- DRF APIClient
- isolated test database
- pytest
- `assertNumQueries`
- serializer tests
- permission tests
- transaction tests
- concurrency tests
- benchmark scripts
- OpenAPI generation
- schema validation

For security-sensitive behavior, verify both:

- authorized scenario
- unauthorized scenario

For important object-access behavior, verify:

- owner
- another regular user
- staff
- admin
- anonymous user

where those roles exist.

---

# Phase 41 — Do Not Modify the Project by Default

This skill is an **analysis skill**.

Unless the user explicitly asks for implementation:

- do not rewrite production code
- do not delete models
- do not modify migrations
- do not change permissions
- do not change dependencies
- do not change settings
- do not silently "fix" findings

The output should first establish the evidence.

When the user later asks for implementation, use the audit as the source for targeted changes.

---

# Required Final Deliverables

Produce all of the following.

## 1. Executive Summary

Include:

- API scope analyzed
- total endpoints discovered
- total apps involved
- authentication mechanisms
- major domains
- critical/high-risk areas
- major architectural patterns
- major testing gaps
- major performance concerns
- major security concerns
- unknowns / unverified areas

Do not hide uncertainty.

---

## 2. Complete Endpoint Inventory

Provide a table containing every endpoint.

Minimum columns:

| Method | Path | View | Auth | Permissions | Serializer | Main Models | Transaction | Tests | Risk |
|---|---|---|---|---|---|---|---|---|---|

Do not omit "boring" endpoints.

---

## 3. Endpoint Findings

For each endpoint with findings, use the required Evidence Format.

Group by endpoint or domain.

---

## 4. Cross-Cutting Findings

Group into:

- Security
- Architecture
- Database
- Transactions
- Business logic
- API contract
- Performance
- Reliability
- Testing
- Documentation
- Configuration
- Dependencies
- Legacy/duplication

---

## 5. Workflow Maps

Document the major business workflows and state transitions.

Highlight:

- valid transitions
- invalid transitions
- missing checks
- bypass paths
- duplicate paths
- non-atomic operations

---

## 6. Security Matrix

Create:

| Threat Area | Affected Endpoints | Evidence | Risk | Verification/Test |
|---|---|---|---|---|

Focus on Django/DRF-specific attack surfaces.

---

## 7. Test Coverage Matrix

Create:

| Endpoint/Workflow | Functional | Validation | Auth | Authorization | Security | DB | Concurrency | Performance |
|---|---|---|---|---|---|---|---|---|

Use:

- COVERED
- PARTIAL
- MISSING
- UNKNOWN

Do not invent test coverage.

---

## 8. Data Model / API Dependency Map

Show important relationships:

```text
Endpoint
  → Serializer
  → Service
  → Model
  → Related Models
  → Side Effects
```

Identify duplicated domain concepts and legacy models.

---

## 9. Prioritized Remediation Plan

Organize actions as:

### Immediate
Critical/high-risk issues that should be addressed before relying on the affected functionality.

### Near-term
Important correctness, security, reliability, or testing improvements.

### Structural
Architecture and maintainability improvements.

### Hardening
Performance, observability, documentation, and developer-experience improvements.

Do not rank code quality subjectively. Prioritize based on impact, exploitability, likelihood, dependency, and remediation urgency.

---

# Final Quality Rules

Before finishing, verify that:

1. Every route discovered from routing is accounted for.
2. Every protected endpoint has an explicit authorization analysis.
3. Every state-changing workflow has transition analysis.
4. Every financial workflow has transaction + idempotency analysis where relevant.
5. Every list endpoint has pagination/resource-consumption analysis.
6. Every serializer has mass-assignment/data-exposure analysis.
7. Every raw SQL/external input path has injection analysis.
8. Every critical workflow has corresponding test analysis.
9. Every finding contains concrete evidence.
10. Unknown behavior is labeled UNKNOWN rather than guessed.
11. Documentation is compared against implementation.
12. Legacy/duplicate behavior is explicitly investigated.
13. The report distinguishes confirmed facts from inferred risks.
14. No endpoint is declared "secure" merely because tests pass.
15. No component is declared "unused" without reachability/reference evidence.

---

# Output Style

Be precise, technical, and direct.

Prefer:

> `POST /api/finance/checkout/` accepts a client-provided `amount_usd`, and the service does not recompute the authoritative total from the visit's services before creating the Sale. This creates a potential integrity issue because ...`

Avoid:

> "The payment system seems insecure."

Prefer exact file/symbol/line references whenever available.

Use tables for inventories and matrices.

Use concise code excerpts only when they strengthen the evidence.

The final result should be useful to a senior engineer who must decide what to fix first without rereading the entire repository.
