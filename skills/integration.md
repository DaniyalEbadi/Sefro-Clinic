# Django Integration Testing Skill

## Purpose

This skill defines how to design, implement, review, and maintain **integration tests** for this Django project.

The goal is to verify that multiple real application components work correctly together:

* Django models
* Database constraints
* Service-layer business logic
* Django REST Framework serializers
* ViewSets and API views
* Authentication and permissions
* Wallet and financial workflows
* Inventory and product workflows
* Visits and scheduling
* Expenses
* Exchange rates
* Reporting
* Transactions and rollback behavior
* API validation
* PostgreSQL behavior
* Redis/cache behavior when applicable
* Background/infrastructure integrations when applicable

Integration tests must test the application as a connected system rather than testing isolated functions only.

---

# 1. Project Context

This project is a Django 5.2 / Django REST Framework backend for a beauty clinic management system.

Major domains include:

* Accounts/users
* Customers
* Services
* Visits
* Packages
* Products
* Product inventory
* Wallets
* Wallet transactions
* Payments
* Sales
* Expenses
* Financial reporting
* Exchange rates
* Website/public APIs
* Logging/auditing

The API is divided into two major surfaces:

```text
/api/...
```

Legacy/internal dashboard API.

```text
/api/v2/...
```

Public-facing website API.

Authentication uses JWT with:

* Access token lifetime: 24 hours
* Refresh token lifetime: 7 days
* Refresh rotation
* Refresh token blacklist
* HttpOnly cookies
* Authorization header support
* CSRF enforcement for cookie authentication where applicable

The default API permission is authenticated access unless an endpoint explicitly allows public access.

---

# 2. What Integration Tests Must Prove

An integration test must answer questions such as:

> "When a real user performs this operation through the API, does the complete application correctly update all affected records?"

Examples:

```text
Client requests checkout
        ↓
Authentication
        ↓
Permission check
        ↓
Serializer validation
        ↓
View
        ↓
Service layer
        ↓
Database transaction
        ↓
Wallet changes
        ↓
Sale created
        ↓
Product usage recorded
        ↓
Historical cost preserved
        ↓
Response returned
```

The test should verify the important outcomes of the entire flow.

Do not stop after asserting HTTP 200/201.

---

# 3. Integration Test Philosophy

Integration tests should prioritize:

1. Real database interactions
2. Real Django ORM behavior
3. Real API routing
4. Real serializers
5. Real authentication
6. Real permissions
7. Real service-layer integration
8. Real transaction behavior
9. Real database constraints
10. Real application workflows

Avoid mocking internal application components unless there is a strong technical reason.

Bad:

```python
@patch("finance.services.wallet.WalletService")
def test_checkout(...):
    ...
```

This can make the test pass while the real wallet implementation is broken.

Prefer:

```python
response = client.post("/api/v2/checkout/", payload)
```

and verify the database afterwards.

---

# 4. Integration Test vs Unit Test

## Unit tests

Use unit tests for:

* Pure calculations
* Small helper functions
* Individual service functions
* Serialization helpers
* Mathematical calculations
* Business rules that do not require the database

Example:

```python
def test_calculate_employee_profit():
    assert calculate_employee_profit(100, 0.2) == Decimal("20")
```

## Integration tests

Use integration tests when multiple components interact.

Example:

```python
response = authenticated_client.post(
    "/api/v2/checkout/",
    checkout_payload,
)

assert response.status_code == 201

assert Sale.objects.filter(...).exists()

customer.refresh_from_db()

assert customer.wallet.balance == expected_balance
```

When uncertain, prefer integration coverage for critical business workflows.

---

# 5. Required Test Structure

Integration tests should generally live under:

```text
tests/
    integration/
        api/
        auth/
        customers/
        visits/
        wallet/
        finance/
        inventory/
        website/
        reports/
        security/
        transactions/
```

Use files that describe behavior rather than implementation details.

Good:

```text
test_checkout_flow.py
test_customer_api.py
test_wallet_transactions.py
test_employee_permissions.py
test_public_website_api.py
test_expense_workflow.py
```

Avoid:

```text
test_functions.py
test_misc.py
test_new.py
```

---

# 6. Integration Test Naming

Test names must explain the behavior being verified.

Good:

```python
def test_employee_can_complete_package_and_wallet_reward_is_added():
    ...
```

```python
def test_employee_cannot_manually_credit_customer_wallet():
    ...
```

```python
def test_admin_can_modify_customer_wallet():
    ...
```

```python
def test_failed_checkout_rolls_back_wallet_sale_and_inventory_changes():
    ...
```

Bad:

```python
def test_wallet():
    ...
```

```python
def test_api():
    ...
```

---

# 7. Database Strategy

Integration tests must use Django's real test database.

Do not replace database behavior with mocks.

Use Django's testing framework and pytest-django infrastructure if the project uses pytest.

Preferred:

```python
@pytest.mark.django_db
def test_customer_creation(...):
    ...
```

For transactional behavior, use appropriate database transaction handling.

Critical financial tests must verify:

* commits
* rollbacks
* database constraints
* atomicity
* concurrent-sensitive behavior where practical

---

# 8. PostgreSQL First

The production database is PostgreSQL.

Integration tests should preferably execute against PostgreSQL-compatible behavior.

Do not assume SQLite behavior is equivalent.

Avoid tests that accidentally pass only because SQLite is more permissive.

Tests must explicitly cover:

* Decimal precision
* Unique constraints
* Check constraints
* Foreign keys
* `NULL` behavior
* transactions
* locking where applicable
* PostgreSQL-specific behavior used by the application

---

# 9. Fixtures

Create reusable fixtures for common actors.

Minimum fixture concepts:

```text
admin_user
employee_user
customer
service
package
product
wallet
exchange_rate
authenticated_client
admin_client
employee_client
public_client
```

Example:

```python
@pytest.fixture
def admin_user(db):
    return ClinicUser.objects.create_user(
        username="admin",
        role=ClinicUser.Role.ADMIN,
    )
```

Use factories when the project has factory_boy.

Prefer factories for large test suites.

---

# 10. Test Users and Roles

Every permission-sensitive integration test must clearly identify the actor.

At minimum test:

```text
ADMIN
EMPLOYEE
UNAUTHENTICATED
```

Where relevant also test:

```text
OTHER EMPLOYEE
OTHER CUSTOMER
DISABLED USER
EXPIRED AUTHENTICATION
INVALID TOKEN
```

Never assume that authentication automatically means authorization.

---

# 11. Authentication Integration Tests

Authentication tests must verify the complete authentication flow.

Required coverage:

## Login

Verify:

* valid credentials succeed
* invalid username fails
* invalid password fails
* correct response format
* access token creation
* refresh token creation
* cookie behavior where applicable

## Access token lifetime

The project's required access lifetime is:

```text
24 hours
```

Integration tests must assert the configured lifetime.

Do not retain old tests expecting 30 minutes.

## Refresh

Test:

```text
valid refresh → new access token
expired refresh → rejected
blacklisted refresh → rejected
rotated refresh → old token invalid where rotation requires it
```

## Authentication header

Test:

```http
Authorization: Bearer <token>
```

## Cookie authentication

Test authenticated browser-style requests using the configured JWT cookies.

## CSRF

Where cookie authentication requires CSRF:

```text
missing CSRF → reject
invalid CSRF → reject
valid CSRF → allow
```

---

# 12. Permission Integration Tests

Permissions must be tested through the API.

Do not only test permission classes directly.

Example:

```python
response = employee_client.post(
    "/api/customers/",
    payload,
)

assert response.status_code == expected_status
```

Verify permissions for:

### Admin

Admin should be able to perform all intended administrative operations.

### Employee

Employees may perform allowed customer/business operations.

They must not:

* access logs when restricted
* create users when restricted
* view other users where restricted
* manually add money to customer wallets
* perform admin-only operations

Every restriction should have an integration test.

---

# 13. Customer Integration Tests

Required workflows:

## Create customer

Verify:

* request validation
* customer creation
* wallet creation if automatic
* default values
* response serialization

## Update customer

Verify allowed fields.

## Retrieve customer

Verify:

* authorized access
* serializer output
* related data
* visit information

## Employee restrictions

Verify precisely which customer operations employees may perform.

## Cross-user access

Attempt to access another customer's protected resources where object-level restriction applies.

Expected behavior must be explicit:

```text
403 or 404
```

depending on the API design.

---

# 14. Wallet Integration Tests

Wallet logic is critical.

Wallet changes must go through:

```text
finance/services/wallet.py
```

Do not create tests that bypass the wallet service unless specifically testing lower-level database constraints.

Integration tests must verify:

## Initial wallet

```text
customer created
→ wallet exists
→ balance initialized correctly
```

## Credit

Verify:

* balance increases
* WalletTransaction created
* transaction amount correct
* transaction metadata correct

## Debit

Verify:

* balance decreases
* WalletTransaction created

## Negative balance

Verify:

```text
insufficient funds
→ operation rejected
→ balance unchanged
→ transaction not created
```

## Admin wallet modification

Admin may perform permitted wallet operations.

Verify complete database state.

## Employee manual wallet credit

Must be rejected according to the project's business rules.

## Wallet transaction consistency

After every successful change verify:

```text
wallet.balance
=
previous balance + credits - debits
```

Never rely only on the API response.

---

# 15. Wallet Integrity Tests

Critical invariant:

```text
wallet.balance >= 0
```

Tests must attempt to break this invariant.

Examples:

```text
direct debit greater than balance
multiple simultaneous debits
invalid negative credit
negative transaction
decimal edge cases
```

Verify the database remains valid.

Where race conditions matter, add concurrency-oriented tests.

---

# 16. Checkout Integration Tests

Checkout is one of the most important integration workflows.

A checkout test should potentially cover:

```text
API request
→ authentication
→ permissions
→ validation
→ idempotency
→ wallet/payment handling
→ sale creation
→ product usage
→ cost snapshot
→ reward/profit
→ transaction commit
→ response
```

Test successful checkout.

Then test every important failure mode.

---

# 17. Idempotency Testing

Checkout uses:

```text
idempotency_key
```

Integration tests must verify:

```text
request A
request A repeated with same key
```

produces only one logical operation.

Verify that duplicate requests do not create:

* duplicate Sale
* duplicate wallet transaction
* duplicate ProductUsage
* duplicate reward
* duplicate inventory movement

The second request must return the system's defined idempotency response.

Also test:

```text
same idempotency key + different payload
```

and verify it is rejected rather than silently changing the original operation.

---

# 18. Transaction Rollback Tests

This is mandatory.

Create scenarios where a multi-step operation fails halfway.

Example:

```text
wallet debit
→ sale creation
→ inventory update
→ error
```

After failure verify:

```text
wallet unchanged
sale not persisted
inventory unchanged
reward unchanged
```

Use:

```python
with pytest.raises(...):
    ...
```

or API requests followed by state assertions.

Do not only assert the error response.

The database state is the actual test.

---

# 19. Product Cost History

Product costs are historical.

When product usage occurs, the application must preserve the historical cost snapshot.

Integration test:

```text
Product cost = 100
↓
checkout
↓
ProductUsage.cost_snapshot = 100
↓
Product cost changes to 150
↓
ProductUsage.cost_snapshot remains 100
```

Verify the report/profit calculation still uses the historical value.

---

# 20. Package Completion and Employee Profit

Where package completion generates employee/customer financial effects, test the complete workflow.

Verify:

```text
package completion
→ employee percentage applied
→ expected profit/reward calculated
→ customer wallet updated where required
→ ledger/transaction created
```

Use `Decimal`.

Never compare financial values using floating point.

Bad:

```python
assert balance == 100.1
```

Good:

```python
assert balance == Decimal("100.10")
```

---

# 21. Decimal Precision

All financial integration tests must use:

```python
from decimal import Decimal
```

Test:

* `.01`
* `.10`
* `.99`
* large amounts
* percentage calculations
* exchange-rate conversion
* rounding boundaries

Include cases where floating-point math would be incorrect.

---

# 22. Exchange Rate Integration Tests

The project contains USD → TOMAN exchange rates.

Integration tests should verify:

```text
stored exchange rate
→ price conversion
→ correct Decimal result
→ correct rounding
→ API representation
```

Test:

```text
missing exchange rate
invalid rate
zero rate where prohibited
multiple historical rates
current rate selection
```

When an API provider is integrated, keep external HTTP calls mocked at the network boundary, not internal business logic.

The goal is to test:

```text
provider response
→ parsing
→ validation
→ persistence
→ conversion service
```

without making the test suite depend on the live Internet.

---

# 23. Inventory Integration Tests

Verify:

```text
product exists
→ purchase/usage occurs
→ stock changes correctly
→ product usage recorded
→ cost snapshot preserved
```

Test:

* sufficient inventory
* insufficient inventory
* zero stock
* invalid quantity
* product deletion restrictions
* concurrent/duplicate usage where relevant

Failed operations must not partially modify inventory.

---

# 24. Visit Integration Tests

Test the complete visit workflow.

Examples:

```text
create visit
→ associate customer
→ associate service/package
→ validate scheduling
→ save
→ serialize
```

Verify:

* required fields
* customer association
* service association
* date/time handling
* Shamsi/Persian date logic where applicable
* visit number generation
* duplicate prevention where applicable
* employee permissions

The test must catch serializer regressions such as missing:

```text
visit_number
```

or invalid related-object access.

---

# 25. Expense Integration Tests

Expenses have an approval workflow.

Integration tests must cover the state machine.

For example:

```text
CREATED
→ APPROVED
```

and valid/invalid transitions.

Test:

```text
employee creates expense
employee attempts self-approval
admin approves
already-approved expense approved again
rejected expense approved
approved expense edited
```

Self-approval must be rejected.

Test both:

* API response
* database state

---

# 26. Reporting Integration Tests

Reports must be tested against realistic database data.

Do not only test an isolated calculation.

Create:

```text
customers
services
packages
sales
wallet transactions
product usages
expenses
exchange rates
```

Then call the reporting endpoint/service and verify:

* totals
* profit
* revenue
* costs
* wallet totals
* employee profit
* date filtering
* historical cost usage

Use deterministic fixtures.

---

# 27. Website API Integration Tests

The public website API under:

```text
/api/v2/
```

must have its own integration suite.

Test:

* public endpoints
* expected anonymous access
* authentication where required
* serializer shape
* validation
* pagination
* filtering
* ordering
* rate/abuse protections where configured
* information disclosure

Public endpoints must not accidentally expose:

* internal users
* logs
* private financial information
* credentials
* internal IDs where intentionally hidden
* administrative fields

---

# 28. Security Integration Tests

Security tests should exercise actual API endpoints.

Required areas:

## Authentication bypass

Try requests without authentication.

## Broken authorization

Employee attempts admin operation.

## IDOR / object access

Employee/customer attempts to access another user's resources.

## Mass assignment

Send fields the user should not control.

Example:

```json
{
    "role": "ADMIN"
}
```

Verify role escalation is impossible.

## Wallet manipulation

Attempt:

```json
{
    "amount": -100000
}
```

or invalid transaction structures.

## Input validation

Test:

* excessively large values
* invalid types
* malformed JSON
* invalid IDs
* unexpected fields
* SQL-like input
* HTML/script payloads where relevant

Do not confuse input reflection with successful injection.

The important assertion is that the application remains secure.

---

# 29. API Response Assertions

Do not write:

```python
assert response.status_code == 200
```

alone.

Prefer:

```python
assert response.status_code == 200
data = response.json()

assert data["id"] == customer.id
assert data["name"] == "Test Customer"
```

For lists:

```python
assert response.data["count"] == 2
assert len(response.data["results"]) == 2
```

Also verify important fields are absent when they must be hidden.

---

# 30. Status Code Expectations

Integration tests should explicitly document expected HTTP behavior.

Examples:

```text
200 → successful retrieval/update depending on endpoint
201 → creation
204 → successful deletion where applicable
400 → validation error
401 → unauthenticated
403 → authenticated but forbidden
404 → object not accessible/not found depending on API contract
409 → conflict/idempotency/business conflict where applicable
429 → rate limit
500 → should generally never be expected for normal invalid input
```

Never accept "any 4xx" unless the API contract genuinely permits multiple statuses.

Bad:

```python
assert response.status_code in range(400, 500)
```

Good:

```python
assert response.status_code == 403
```

---

# 31. Response Contract Testing

Integration tests should protect API contracts.

For important endpoints verify:

* field names
* field types
* required fields
* nullable fields
* nested relationships
* pagination format
* error format

Example:

```python
assert set(response.data) >= {
    "id",
    "name",
    "created_at",
}
```

Do not over-constrain responses with every optional field unless the contract requires it.

---

# 32. Query Count and N+1 Integration Tests

Critical endpoints must be protected against accidental N+1 queries.

Use Django query-count tools where useful.

Example concept:

```python
with assertNumQueries(expected):
    response = client.get("/api/customers/")
```

Do not blindly hard-code fragile query counts for every endpoint.

Use query budgets on performance-critical endpoints.

Tests must catch regressions caused by:

```text
serializer nested relationships
missing select_related
missing prefetch_related
report generation
large customer lists
```

---

# 33. Pagination Integration Tests

Test:

```text
page 1
page 2
page size
empty page
large dataset
invalid page
invalid page_size
```

Verify no duplicate or missing records across pages.

---

# 34. Filtering and Ordering

Where endpoints provide filtering:

Test combinations such as:

```text
single filter
multiple filters
invalid filter
date range
empty result
ordering ascending
ordering descending
```

Verify database results rather than trusting response status.

---

# 35. Date and Time Testing

The project uses Shamsi/Persian dates in some areas.

Integration tests should verify conversion between:

```text
Gregorian
↔
Shamsi/Persian
```

Test boundary values:

* beginning of month
* end of month
* year change
* leap-year-sensitive values
* timezone boundaries

Use explicit timezone-aware datetimes when appropriate.

Never rely on the machine's local timezone.

---

# 36. Concurrency and Race Conditions

Critical financial operations should have tests for duplicate or concurrent operations when practical.

Especially:

```text
wallet debit
checkout
idempotency
inventory deduction
reward creation
expense approval
```

The application should preserve invariants even when two requests happen nearly simultaneously.

Where true concurrency testing is expensive, create at least a regression test around the known race condition.

---

# 37. External Services

Never make integration tests depend on external production services.

For HTTP APIs:

```text
application
→ HTTP boundary mock
→ fake provider response
```

Test realistic provider responses:

* success
* timeout
* 400
* 401
* 429
* 500
* malformed response
* missing fields

Do not mock:

```text
Django ORM
Service layer
Serializer
View
Wallet logic
```

unless explicitly testing an isolation boundary.

---

# 38. Redis and Caching

When Redis is part of the production architecture, test integration behavior that depends on it.

Examples:

* cache invalidation
* cache expiration
* locking
* idempotency storage
* rate limiting

Tests should verify behavior rather than Redis implementation details.

If a test can work correctly without Redis, do not add Redis dependency unnecessarily.

---

# 39. Transaction Boundaries

Every critical service using:

```python
@transaction.atomic
```

must have integration tests proving the atomicity.

The test should deliberately cause failure after one or more database operations.

Verify:

```text
before state == after state
```

unless the API explicitly defines partial persistence.

---

# 40. Database Constraint Testing

Integration tests must test model constraints where they represent business invariants.

Examples:

```text
wallet balance >= 0
unique reward rule
unique idempotency key
foreign key relationships
required fields
valid expense transitions
```

Do not rely solely on application validation.

A database constraint test should attempt direct ORM insertion where appropriate.

Example:

```python
with pytest.raises(IntegrityError):
    Wallet.objects.create(
        customer=customer,
        balance=Decimal("-1"),
    )
```

---

# 41. Test Isolation

Every integration test must be independent.

Never depend on execution order.

Bad:

```text
test_create_customer
test_update_customer_created_by_previous_test
```

Good:

```text
each test creates its own required state
```

Never use a shared mutable global database object.

---

# 42. Deterministic Test Data

Avoid random test data unless randomness is the behavior being tested.

Prefer:

```python
Decimal("100.00")
```

rather than random monetary values.

If random data is used:

* seed it
* make failures reproducible
* include generated values in failure output

---

# 43. Time-Dependent Tests

Never write tests that depend on real wall-clock passage when avoidable.

Use controlled time utilities/freezing mechanisms where appropriate.

Bad:

```python
time.sleep(2)
```

Good:

```text
freeze time
→ execute
→ advance logical time
→ verify expiration
```

---

# 44. Test Factories

Factories should create valid domain objects.

A factory should not hide important business behavior.

Good:

```python
customer = CustomerFactory()
```

Then explicitly perform the operation being tested.

Avoid factories that secretly:

```text
add wallet money
perform checkout
create unrelated sales
```

unless that behavior is explicitly the factory's purpose.

---

# 45. Arrange / Act / Assert

Integration tests should follow:

```text
Arrange
Act
Assert
```

Example:

```python
def test_employee_cannot_credit_wallet(employee_client, customer):
    # Arrange
    payload = {
        "amount": "100.00",
    }

    # Act
    response = employee_client.post(
        f"/api/customers/{customer.id}/wallet/credit/",
        payload,
        format="json",
    )

    # Assert
    assert response.status_code == 403

    customer.refresh_from_db()

    assert customer.wallet.balance == Decimal("0.00")
```

Keep setup understandable.

---

# 46. State-Based Assertions

The most important assertions are often database-state assertions.

For financial operations verify:

```text
before balance
after balance
ledger entry
sale
product usage
inventory
profit
```

For user operations verify:

```text
role
permissions
relations
audit records
```

For API operations verify:

```text
database
response
side effects
```

---

# 47. Negative Testing

At least as much attention should be given to failure paths as success paths.

For every major endpoint ask:

```text
What happens with:
- missing field?
- invalid field?
- unauthorized user?
- forbidden employee?
- nonexistent object?
- duplicate request?
- invalid state?
- insufficient wallet?
- insufficient inventory?
- malformed input?
- database constraint violation?
- external service failure?
```

---

# 48. Critical Business Invariants

Integration tests must protect these invariants.

## Wallet

```text
balance >= 0
```

Wallet modifications must go through the official wallet service.

## Idempotency

```text
one idempotency key
→ one logical operation
```

## Historical cost

```text
ProductUsage cost snapshot
must not change when current product cost changes.
```

## Employee permissions

Employee cannot:

```text
view restricted logs
create users
view other users
manually credit wallet
perform admin-only actions
```

## Admin

Admin can perform authorized administrative operations.

## Expense workflow

Self-approval is forbidden.

Invalid state transitions are rejected.

## Financial precision

Use:

```text
Decimal
```

not float.

## Authentication

Access-token lifetime is:

```text
24 hours
```

Refresh lifetime is:

```text
7 days
```

---

# 49. Integration Test Matrix

Maintain coverage for the following matrix:

| Domain         |       Admin |    Employee |         Anonymous | Success | Failure |         Rollback |
| -------------- | ----------: | ----------: | ----------------: | ------: | ------: | ---------------: |
| Authentication |           ✓ |           ✓ |                 ✓ |       ✓ |       ✓ |                - |
| Customers      |           ✓ |           ✓ |  where applicable |       ✓ |       ✓ |                ✓ |
| Wallet         |           ✓ |  restricted |                 ✗ |       ✓ |       ✓ |                ✓ |
| Checkout       |           ✓ |           ✓ |                 ✗ |       ✓ |       ✓ |                ✓ |
| Packages       |           ✓ |           ✓ | public parts only |       ✓ |       ✓ |                ✓ |
| Products       |           ✓ |  restricted | public parts only |       ✓ |       ✓ |                ✓ |
| Inventory      |           ✓ |  restricted |                 ✗ |       ✓ |       ✓ |                ✓ |
| Visits         |           ✓ |           ✓ |                 ✗ |       ✓ |       ✓ |                ✓ |
| Expenses       |           ✓ |  restricted |                 ✗ |       ✓ |       ✓ |                ✓ |
| Reports        |           ✓ |  restricted |                 ✗ |       ✓ |       ✓ |                - |
| Website API    | as designed | as designed |                 ✓ |       ✓ |       ✓ | where applicable |
| Security       |           ✓ |           ✓ |                 ✓ |       ✓ |       ✓ |                ✓ |

This matrix is a guide, not a reason to create meaningless tests.

---

# 50. Test Naming Convention

Use:

```text
test_<actor>_<action>_<expected_result>
```

Examples:

```python
test_admin_can_update_customer()
test_employee_can_update_customer()
test_employee_cannot_create_user()
test_anonymous_user_cannot_access_private_wallet()
test_duplicate_checkout_is_idempotent()
test_failed_checkout_rolls_back_wallet()
```

---

# 51. API Client Helpers

Create reusable test helpers for:

```text
authenticated_client
admin_client
employee_client
public_client
```

Example:

```python
@pytest.fixture
def admin_client(api_client, admin_user):
    api_client.force_authenticate(user=admin_user)
    return api_client
```

Use `force_authenticate` for permission-focused tests when token mechanics are not what the test is testing.

Use real JWT authentication for authentication integration tests.

This distinction is important.

---

# 52. Authentication Test Separation

For a permission test:

```python
client.force_authenticate(user=employee)
```

is acceptable.

For an authentication test:

```text
login
→ obtain JWT
→ send JWT
→ refresh JWT
```

must be used.

Do not use `force_authenticate` in tests intended to validate the authentication implementation.

---

# 53. Integration Test Layers

Structure tests into three useful layers.

## Layer 1 — API Integration

```text
HTTP request
→ URL
→ authentication
→ permission
→ serializer
→ view
→ service
→ database
```

## Layer 2 — Service + DB Integration

```text
service
→ ORM
→ transaction
→ constraints
```

## Layer 3 — System/Workflow Integration

```text
multiple services
→ financial workflows
→ inventory
→ wallet
→ reporting
```

Critical business flows should have Layer 1 tests.

---

# 54. Avoid Over-Mocking

Do not mock these in ordinary integration tests:

```text
Model.objects
Wallet service
Checkout service
Serializer
View
Permission classes
Django transaction
```

These are exactly the components the integration test is supposed to verify together.

Mock only boundaries such as:

```text
external HTTP APIs
third-party SDKs
email providers
SMS providers
payment gateways
cloud storage
```

when those external systems are outside the test environment.

---

# 55. Error Handling

Tests must verify that errors do not leak sensitive information.

Bad:

```text
database traceback
secret key
environment variable
password
JWT
stack trace
```

must never be returned to normal clients.

Test important production-like error responses.

---

# 56. Logging and Audit Integration

For business-critical actions, where audit logging exists, verify that the expected log/audit record is created.

Examples:

```text
wallet modification
expense approval
user administration
important financial action
```

Also verify employees cannot retrieve restricted logs through API endpoints.

---

# 57. Performance Integration Tests

Integration tests should include a small number of high-value performance checks.

Test:

```text
large customer list
large transaction history
report generation
nested serializer endpoints
```

Check:

* query budget
* response behavior
* obvious N+1 regressions

Do not turn every integration test into a performance benchmark.

---

# 58. Regression Tests

Every production bug should result in a regression test.

Workflow:

```text
bug found
↓
write failing integration test
↓
fix implementation
↓
test passes
↓
keep regression test permanently
```

Example:

```text
Serializer raises KeyError for visit_number
↓
add integration test for customer API
↓
fix serializer
↓
test remains permanently
```

---

# 59. Existing Test Suite Compatibility

Before adding new integration tests:

1. Read the existing test structure.
2. Reuse existing factories and fixtures.
3. Reuse API URL patterns.
4. Reuse authentication helpers.
5. Reuse existing domain utilities.
6. Do not duplicate test infrastructure.
7. Respect current project conventions.

Never rewrite the project's entire test architecture merely to add integration tests.

---

# 60. Test Commands

If pytest is used:

```bash
pytest
```

Integration only:

```bash
pytest tests/integration/
```

Specific domain:

```bash
pytest tests/integration/finance/
```

Verbose:

```bash
pytest -v tests/integration/
```

Specific test:

```bash
pytest tests/integration/finance/test_wallet.py::test_admin_can_credit_wallet
```

Stop after first failure:

```bash
pytest -x tests/integration/
```

Coverage:

```bash
pytest --cov=. --cov-report=term-missing
```

Use the project's actual configured commands if they differ.

---

# 61. CI Requirements

Integration tests must run in CI.

CI should provide services matching production assumptions, particularly PostgreSQL.

Typical structure:

```text
GitHub Actions
    ↓
PostgreSQL service
    ↓
Django migrations
    ↓
integration tests
    ↓
coverage
```

If Redis is required:

```text
PostgreSQL
Redis
Django
pytest
```

All CI environment variables should use test-safe values.

Never place real production secrets in CI tests.

---

# 62. CI Test Categories

Recommended CI stages:

```text
lint
↓
unit tests
↓
integration tests
↓
security tests
↓
coverage
```

For pull requests, critical integration tests must run before merge.

---

# 63. Parallelization

Tests should be safe to run in parallel when possible.

Avoid:

* shared hard-coded database rows
* global mutable state
* fixed external ports
* filesystem collisions
* test-order dependencies

If PostgreSQL parallel test workers are used, verify that database isolation remains correct.

---

# 64. Coverage Philosophy

Do not optimize for percentage alone.

A 95% coverage suite can still miss the most important business workflow.

Prioritize:

```text
financial logic
authentication
authorization
wallet
checkout
inventory
expenses
reports
public API security
transaction rollback
```

A critical workflow with lower line coverage is more important than a trivial utility with 100% coverage.

---

# 65. Required Integration Test Checklist

Before declaring an integration suite complete, verify:

```text
[ ] Authentication flow tested
[ ] JWT 24-hour access lifetime tested
[ ] Refresh flow tested
[ ] Token blacklist tested
[ ] Cookie authentication tested where applicable
[ ] CSRF tested where applicable

[ ] Admin permissions tested
[ ] Employee permissions tested
[ ] Anonymous restrictions tested
[ ] Object-level authorization tested
[ ] Mass-assignment protection tested

[ ] Customer CRUD tested
[ ] Customer serializer contract tested
[ ] Visit workflow tested
[ ] visit_number regression covered

[ ] Wallet creation tested
[ ] Wallet credit tested
[ ] Wallet debit tested
[ ] Negative balance prevented
[ ] Ledger integrity tested
[ ] Employee wallet restriction tested
[ ] Admin wallet permissions tested

[ ] Checkout success tested
[ ] Checkout validation tested
[ ] Checkout idempotency tested
[ ] Duplicate idempotency key tested
[ ] Rollback tested
[ ] Product usage tested
[ ] Historical cost snapshot tested
[ ] Employee profit/reward tested

[ ] Inventory success tested
[ ] Inventory failure tested
[ ] Inventory rollback tested

[ ] Expense creation tested
[ ] Expense approval tested
[ ] Self-approval forbidden
[ ] Invalid state transitions tested

[ ] Exchange-rate conversion tested
[ ] Decimal precision tested
[ ] Rounding tested

[ ] Reporting tested with realistic data
[ ] Date filtering tested
[ ] Profit calculation tested

[ ] Public website API tested
[ ] Sensitive information exposure tested

[ ] PostgreSQL integration verified
[ ] Query regression tests added where valuable
[ ] CI execution verified
```

---

# 66. How an AI Agent Should Implement Tests

When asked to add integration tests, follow this process.

## Step 1 — Inspect

Read:

```text
manage.py
pyproject.toml / requirements
pytest configuration
settings
URLs
models
serializers
views
permissions
services
existing tests
CI workflows
```

Understand the real architecture before writing tests.

## Step 2 — Map Business Flows

Build an internal map:

```text
endpoint
→ serializer
→ view
→ service
→ models
→ side effects
```

Identify critical invariants.

## Step 3 — Inspect Existing Tests

Do not duplicate existing tests.

Find what is already covered.

Identify gaps.

## Step 4 — Write Integration Tests

Start with the highest-risk flows:

```text
authentication
authorization
wallet
checkout
transactions
inventory
financial calculations
public API security
```

## Step 5 — Run Tests

Run the smallest relevant test group first.

Then run the entire integration suite.

Then run the complete suite.

## Step 6 — Investigate Failures

Do not immediately modify tests to make them pass.

First determine whether:

```text
test is wrong
implementation is wrong
business requirement changed
fixture is wrong
environment is wrong
```

## Step 7 — Preserve Existing Contracts

Do not silently alter API behavior just to satisfy a test.

If the behavior conflicts with the project's defined business rule, fix the implementation.

## Step 8 — Add Regression Coverage

Every discovered bug should receive a permanent regression test.

---

# 67. Rules for Test Fixes

When an existing integration test fails:

### Do not

* weaken assertions
* accept multiple status codes unnecessarily
* mock the failing implementation
* delete the test
* skip the test
* increase timeouts without understanding the problem
* change expected financial values without confirming the business rule

### Do

* inspect the implementation
* inspect the model constraints
* inspect the service logic
* inspect the serializer
* reproduce the behavior
* determine the intended business rule
* fix the root cause
* preserve the regression test

---

# 68. Test Data Rules

Do not use real customer data.

Never place:

```text
real names
real phone numbers
real emails
real financial records
real credentials
real API keys
```

in integration tests.

Use deterministic fake data.

---

# 69. Secrets

Tests must never require production secrets.

Use environment variables such as:

```text
DJANGO_SECRET_KEY=test-secret
DATABASE_URL=test-database
```

or CI-provided safe secrets.

Never hardcode:

```text
production API key
JWT secret
database password
real provider credential
```

---

# 70. Final Integration Test Standard

An integration test is complete when it proves not merely that an endpoint responds correctly, but that the system remains correct after the operation.

For important workflows always verify:

```text
HTTP response
+
database state
+
business invariants
+
side effects
+
permissions
+
transaction behavior
```

The test suite must make regressions difficult to introduce.

The strongest integration test is one that would fail if a developer accidentally breaks the real business behavior.

---

# 71. Agent Output Expectations

When an AI coding agent uses this skill, its implementation report should contain:

```text
Integration Tests Added
-----------------------
<files>

Scenarios Covered
-----------------
<critical workflows>

Business Rules Verified
-----------------------
<rules>

Failures Found
--------------
<issues>

Implementation Fixes
---------------------
<root-cause fixes>

Final Test Results
------------------
<result>
```

Do not claim all tests pass unless they were actually executed.

If some tests could not run, explicitly state why.

---

# 72. Definition of Done

Integration testing work is complete only when:

1. Critical business workflows are covered.
2. Authentication and authorization are tested through real APIs.
3. Database effects are asserted.
4. Rollback behavior is tested.
5. Financial invariants are tested.
6. Idempotency is tested.
7. Employee/admin restrictions are tested.
8. Public API security is tested.
9. PostgreSQL-compatible behavior is verified.
10. Important query regressions are protected.
11. CI can run the integration suite.
12. Tests are isolated and deterministic.
13. Existing tests still pass.
14. No production secrets are required.
15. New bugs discovered during implementation have regression tests.

---

# 73. Golden Rule

For this project, integration tests must always answer:

> "Can a real authenticated actor perform this business operation through the real Django application, and after the request finishes, is the entire database and business state exactly correct?"

If the answer is not proven by the test, the integration test is incomplete.
