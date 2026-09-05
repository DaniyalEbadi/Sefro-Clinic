# Django End-to-End Testing Skill

## Purpose

This skill defines how to design, implement, execute, review, and maintain **End-to-End (E2E) tests** for this project.

E2E tests verify complete user workflows from the perspective of a real client.

Unlike unit tests or integration tests, an E2E test should simulate an actual user interacting with the application from beginning to end.

The objective is to prove:

```text
User
 ↓
Client / Browser
 ↓
Frontend
 ↓
HTTP / API
 ↓
Authentication
 ↓
Django / DRF
 ↓
Business Logic
 ↓
Database
 ↓
External Services / Infrastructure
 ↓
Final User-visible Result
```

An E2E test should fail when the complete product workflow is broken, even if every individual component appears to work in isolation.

---

# 1. Project Context

This project is a Django 5.2 / Django REST Framework clinic management backend.

Major business domains include:

```text
Accounts
Customers
Visits
Services
Packages
Products
Inventory
Wallet
Wallet Transactions
Sales
Payments
Expenses
Financial Reporting
Exchange Rates
Website API
Logging / Auditing
```

The application exposes:

```text
/api/...
```

for the internal/dashboard API and:

```text
/api/v2/...
```

for the public website API.

Authentication uses JWT with:

```text
Access token: 24 hours
Refresh token: 7 days
Refresh rotation
Blacklist
HttpOnly cookies
Authorization header
CSRF protection where cookie authentication applies
```

E2E tests must validate the complete behavior of these systems together.

---

# 2. What E2E Testing Means

E2E testing asks:

> "Can a real user successfully complete an important business task using the real application?"

Example:

```text
Admin logs in
↓
Creates customer
↓
Creates / selects service
↓
Schedules visit
↓
Customer receives service
↓
Checkout occurs
↓
Wallet/payment is processed
↓
Product usage is recorded
↓
Profit is calculated
↓
Report displays the correct result
```

This is one E2E workflow.

Do not split this into isolated assertions that no longer represent a real workflow.

---

# 3. E2E vs Integration Tests

## Unit Test

Tests one small component.

```text
function
```

## Integration Test

Tests multiple backend components together.

```text
API → service → database
```

## E2E Test

Tests a complete user journey.

```text
user → browser/client → frontend/API → backend → database → visible result
```

E2E tests should be fewer than unit/integration tests.

They are slower and more expensive.

Use E2E tests for the most important user journeys.

---

# 4. E2E Test Philosophy

E2E tests should:

* use realistic user behavior
* use real application routing
* use real authentication
* use real APIs
* use real database state
* verify final observable outcomes
* minimize internal implementation assumptions
* avoid mocking application internals
* remain deterministic
* cover business-critical workflows

The test should behave as much like a real client as practical.

---

# 5. Primary E2E Tooling

Use the project's existing browser automation technology.

Preferred browser automation:

```text
Playwright
```

if the project has a browser-based frontend.

If the project already uses another E2E framework, preserve the existing framework rather than introducing a second competing framework without a reason.

For API-only E2E workflows where no browser is necessary, use a real HTTP client against the running application.

Examples:

```text
Playwright
HTTPX
Requests
Postman/Newman
Cypress
```

Use the project's established tooling first.

---

# 6. E2E Environment

E2E tests must run against a dedicated test environment.

Example:

```text
E2E Environment
    ↓
Frontend
    ↓
Django API
    ↓
PostgreSQL
    ↓
Redis if required
    ↓
Safe test external-service boundaries
```

Never run destructive E2E tests against production.

Never use production customer data.

---

# 7. E2E Environment Rules

The E2E environment must use:

```text
test database
test credentials
test API keys
test email provider
test payment provider
test exchange-rate provider
```

External services should use:

```text
sandbox
mock server
stub server
test provider
```

depending on the service.

Production secrets must never be required.

---

# 8. E2E Test Directory

Recommended:

```text
tests/
    e2e/
        auth/
        customers/
        visits/
        wallet/
        checkout/
        inventory/
        expenses/
        reports/
        website/
        security/
        smoke/
        fixtures/
        helpers/
        pages/
```

For Playwright:

```text
tests/e2e/
    auth.spec.ts
    customer.spec.ts
    checkout.spec.ts
    wallet.spec.ts
    expense.spec.ts
    reports.spec.ts
```

Use the project's language/tooling convention.

---

# 9. E2E Test Naming

Names must describe the user journey.

Good:

```text
admin_can_create_customer_and_schedule_visit
employee_can_complete_package_for_customer
admin_can_complete_checkout_and_see_updated_wallet
employee_cannot_manually_credit_customer_wallet
failed_checkout_does_not_change_customer_balance
admin_can_approve_expense_and_see_it_in_report
```

Bad:

```text
test_page
test_api
test_customer
test_button
```

---

# 10. E2E Test Categories

Use four categories.

## Smoke

Very small set of tests proving the deployment is alive.

Example:

```text
application loads
login works
authenticated dashboard loads
public website API works
```

## Critical Journey

High-value workflows.

Example:

```text
login
→ customer
→ visit
→ checkout
→ wallet
→ report
```

## Security Journey

User attempts forbidden actions.

Example:

```text
employee
→ wallet page
→ attempts manual credit
→ rejected
```

## Regression Journey

Permanent reproduction of an important real-world bug.

---

# 11. E2E Test Priority

Prioritize:

```text
P0
Authentication
Checkout
Wallet
Critical customer workflow

P1
Visits
Packages
Inventory
Expenses
Reports

P2
Less critical CRUD
UI edge cases
Rare administrative operations
```

Do not create hundreds of E2E tests for trivial CRUD.

---

# 12. User Personas

At minimum create E2E personas for:

```text
ADMIN
EMPLOYEE
ANONYMOUS VISITOR
```

Where required:

```text
CUSTOMER
SECOND EMPLOYEE
```

Each test should explicitly identify which persona is acting.

---

# 13. Authentication E2E

Authentication must be tested from the user's perspective.

## Login

Test:

```text
open login page
↓
enter valid credentials
↓
submit
↓
authentication succeeds
↓
dashboard loads
```

Verify:

* correct page transition
* authenticated state
* user identity
* protected data becomes accessible

## Invalid login

Test:

```text
wrong credentials
↓
login rejected
↓
user remains unauthenticated
```

Do not only verify HTTP 401.

Verify the UI/application state.

---

# 14. JWT E2E

The project requires:

```text
Access token = 24 hours
Refresh token = 7 days
```

E2E authentication tests should verify practical behavior rather than reproducing every JWT implementation detail.

Test:

```text
login
→ authenticated request
→ access expiration behavior
→ refresh
→ session continues where expected
```

Also test:

```text
expired/invalid session
→ protected page/API
→ user is appropriately redirected or rejected
```

Do not make tests depend on sleeping for 24 hours.

Use controlled expiration or test configuration where possible.

---

# 15. Admin Login Journey

A canonical admin E2E journey should be:

```text
Open application
↓
Login as admin
↓
Verify dashboard
↓
Navigate to customers
↓
Create customer
↓
Open customer
↓
Create or schedule visit
↓
Perform required business action
↓
Verify resulting financial state
```

The exact UI should follow the actual application.

Do not invent UI elements that do not exist.

---

# 16. Employee Login Journey

Canonical employee flow:

```text
Login as employee
↓
Open dashboard
↓
View permitted customer data
↓
Perform permitted operation
↓
Verify operation succeeds
↓
Attempt restricted operation
↓
Verify operation is denied
```

This verifies both positive and negative authorization.

---

# 17. Customer E2E Workflow

Critical customer workflow:

```text
Admin/employee login
↓
Customers
↓
Create customer
↓
Search for customer
↓
Open customer
↓
Verify profile
↓
Create/schedule visit
↓
Verify visit
```

Verify the information shown in the UI matches backend state.

---

# 18. Visit E2E Workflow

Test:

```text
Login
↓
Customers
↓
Select customer
↓
Create visit
↓
Select service/package
↓
Set date/time
↓
Save
↓
Reopen customer
↓
Verify visit appears
```

Where `visit_number` is exposed, verify it exists and remains stable.

Test important date conversions if the UI supports Shamsi/Persian dates.

---

# 19. Package Completion E2E

Critical workflow:

```text
Employee logs in
↓
Opens customer
↓
Opens package
↓
Completes package/service
↓
System applies configured employee percentage
↓
Financial side effects occur
↓
Customer wallet / reward state updates where defined
↓
User sees successful result
```

Verify database state after the UI flow.

Do not rely only on toast notifications.

---

# 20. Wallet E2E

Wallet is a critical financial system.

Test:

```text
Admin login
↓
Customer
↓
Wallet
↓
View current balance
↓
Perform permitted wallet operation
↓
Verify updated balance
↓
Verify transaction history
```

The final assertions should compare:

```text
UI balance
=
database balance
=
expected balance
```

---

# 21. Employee Wallet Restriction E2E

Mandatory workflow:

```text
Employee login
↓
Customer
↓
Wallet
↓
Attempt manual wallet credit
```

Expected:

```text
operation denied
```

Verify:

* action is unavailable or rejected
* no wallet balance change
* no wallet transaction created

This test protects both UI authorization and backend authorization.

---

# 22. Admin Wallet E2E

Mandatory:

```text
Admin login
↓
Customer
↓
Wallet
↓
Perform authorized wallet action
↓
Success
↓
Verify transaction
↓
Verify new balance
```

Test both UI and backend state.

---

# 23. Checkout E2E

Checkout is one of the highest-priority E2E scenarios.

Canonical flow:

```text
Login
↓
Open customer
↓
Select service/package/product
↓
Start checkout
↓
Review price
↓
Choose payment/wallet method
↓
Confirm
↓
Checkout succeeds
↓
Sale appears
↓
Wallet/payment changes
↓
Inventory changes
↓
Product usage appears
↓
Profit/reporting reflects transaction
```

The final state must be internally consistent.

---

# 24. Checkout Failure E2E

A critical negative journey:

```text
Customer attempts checkout
↓
Invalid condition occurs
↓
Checkout fails
↓
User receives correct error
↓
No partial financial state remains
```

Verify:

```text
wallet unchanged
sale unchanged
inventory unchanged
product usage unchanged
profit unchanged
```

This is especially important for transactional financial operations.

---

# 25. Checkout Idempotency E2E

Simulate duplicate submission:

```text
User clicks checkout
↓
request submitted
↓
same operation submitted again
```

Expected:

```text
one logical transaction
```

Verify:

```text
one Sale
one wallet transaction
one ProductUsage
one reward where applicable
one inventory deduction
```

The UI should not show two completed transactions.

---

# 26. Product / Inventory E2E

Test realistic behavior:

```text
Admin/employee login
↓
Product
↓
Select product
↓
Use/sell product
↓
Complete workflow
↓
Stock decreases
↓
Usage record exists
↓
Historical cost remains correct
```

Also test:

```text
insufficient stock
```

and verify that the workflow is rejected without partial changes.

---

# 27. Product Cost History E2E

A regression-quality journey:

```text
Create product
cost = 100
↓
Use product
↓
Change current product cost to 150
↓
Open historical sale/usage
↓
Verify historical cost remains 100
```

The user-facing report should reflect historical cost, not the new cost.

---

# 28. Expense E2E

Canonical flow:

```text
Employee/Admin login
↓
Expenses
↓
Create expense
↓
Submit
↓
Admin reviews
↓
Admin approves
↓
Expense appears in approved totals/report
```

Also test:

```text
Employee tries to approve own expense
```

Expected:

```text
denied
```

---

# 29. Reporting E2E

Reporting tests must start with realistic data.

Example:

```text
Create customer
↓
Complete service
↓
Create product usage
↓
Complete checkout
↓
Create expense
↓
Open financial report
↓
Verify revenue
↓
Verify cost
↓
Verify profit
↓
Verify wallet totals
```

Do not seed the final report value directly unless the workflow being tested specifically requires setup.

The report should be produced by real application behavior.

---

# 30. Public Website E2E

For the public site:

```text
Anonymous visitor
↓
Open website
↓
Browse services/products/content
↓
Call public API endpoints
↓
Verify expected content
```

Ensure public users cannot access:

```text
admin functionality
private financial information
internal users
logs
customer wallet information
```

---

# 31. Security E2E

Security must be tested from an attacker's perspective.

Examples:

## Anonymous access

```text
anonymous
→ private customer endpoint
→ rejected
```

## Employee privilege escalation

```text
employee
→ attempt admin operation
→ rejected
```

## Direct URL access

Do not rely on hidden UI buttons.

Example:

```text
employee
→ manually opens restricted admin URL
→ access denied
```

## API manipulation

Send forbidden fields through the frontend/API boundary.

Example:

```json
{
    "role": "ADMIN"
}
```

Verify privilege cannot be escalated.

---

# 32. Broken Object-Level Authorization E2E

This is mandatory for systems containing customer-specific financial data.

Scenario:

```text
Employee/user A
↓
Attempts to access customer/resource belonging to another restricted scope
```

Verify:

```text
request rejected
```

Also verify:

```text
no sensitive information leaked
```

Do not rely on the UI hiding the resource.

---

# 33. Navigation E2E

For important workflows verify actual navigation:

```text
login
→ dashboard
→ customers
→ customer detail
→ wallet
→ checkout
→ report
```

Ensure browser back/forward behavior does not expose stale or unauthorized information where relevant.

---

# 34. UI State Assertions

E2E tests should verify user-visible state.

Good:

```text
"Customer created successfully"
"Balance: 500.00"
"Expense approved"
"Checkout completed"
```

But visible notifications are not enough.

Always combine them with backend/state assertions for critical operations.

---

# 35. Backend State Assertions in E2E

E2E tests may query the database or backend API for final validation.

Example:

```text
Browser:
    user completes checkout

Then:
    API/database verification
```

This is especially important for:

* money
* inventory
* permissions
* financial reports
* transaction rollback
* audit records

---

# 36. Test IDs

Prefer stable selectors.

Use:

```html
data-testid="customer-create-button"
```

or equivalent stable attributes.

Good:

```text
[data-testid="customer-create-button"]
```

Avoid relying on:

```text
nth-child()
CSS layout
dynamic generated classes
deep DOM structure
pixel coordinates
```

Bad:

```text
div > div:nth-child(4) > button
```

Tests should survive reasonable UI refactoring.

---

# 37. Page Objects

Use Page Object Models when the frontend has enough complexity to justify them.

Example:

```text
pages/
    LoginPage
    DashboardPage
    CustomerPage
    WalletPage
    CheckoutPage
    ExpensePage
    ReportsPage
```

Page objects should encapsulate:

* navigation
* stable selectors
* common interactions

Do not hide entire assertions inside page objects.

Keep business scenario assertions in the test.

---

# 38. API Helpers

For setup that is not the behavior under test, using API helpers can reduce test time.

Example:

```text
Create test customer through API
↓
Open browser
↓
Test UI workflow
```

This is acceptable when the UI is not specifically testing customer creation.

However:

```text
customer creation UI E2E test
```

must create the customer through the UI.

The setup method should not bypass the behavior being tested.

---

# 39. E2E Fixture Strategy

Use dedicated E2E fixtures.

Examples:

```text
admin credentials
employee credentials
test customer
test service
test package
test product
test exchange rate
```

Fixtures should be deterministic.

Do not depend on data left behind by previous tests.

---

# 40. Test Isolation

Every E2E test must be independently runnable.

Avoid:

```text
test A creates customer
↓
test B assumes customer exists
```

Instead:

```text
test A creates its customer
test B creates its customer
```

Parallel test execution must not cause collisions.

Use unique test identifiers where needed.

---

# 41. Test Data Cleanup

The E2E environment should be reset between test runs or use isolated records.

Possible strategies:

```text
temporary database
database reset
transaction cleanup
unique test namespace
API cleanup
Docker environment reset
```

Choose the project's infrastructure.

Never implement cleanup that can accidentally delete production data.

---

# 42. Email E2E

If important workflows send email:

```text
application
→ test email provider
→ email captured
→ verify recipient
→ verify subject
→ verify important content
```

Do not send real emails to customers.

Where email is not part of the user journey, do not make every E2E test dependent on email delivery.

---

# 43. SMS E2E

If SMS functionality exists:

```text
trigger action
↓
test SMS provider
↓
capture message
↓
verify expected message
```

Use sandbox/test infrastructure.

Do not contact real phone numbers.

---

# 44. External API E2E

For exchange rates or other third-party services:

Test the full application boundary:

```text
application
→ provider adapter
→ test provider
→ response
→ persistence
→ user-visible result
```

Do not call live production APIs during ordinary CI E2E tests.

Maintain a separate optional environment for true external-system verification if required.

---

# 45. Exchange Rate E2E

Example:

```text
Admin login
↓
Open pricing/exchange settings
↓
Fetch/update exchange rate
↓
Store rate
↓
Create/use product price
↓
Verify USD → TOMAN conversion
↓
Verify displayed amount
```

Use deterministic test rates.

Example:

```text
USD rate = 100,000 TOMAN
```

Then verify exact Decimal-based results.

---

# 46. Date/Time E2E

Test real user interactions involving dates.

Important cases:

```text
date picker
Shamsi date
Gregorian date
timezone
month boundaries
year boundaries
```

Avoid hard-coding assumptions about the machine's local time.

Use fixed clocks when necessary.

---

# 47. Responsive E2E Testing

If the website supports multiple screen sizes, run a small high-value matrix:

```text
Desktop
Tablet
Mobile
```

Focus on:

* login
* navigation
* customer lookup
* checkout
* important forms
* financial confirmation

Do not attempt every possible viewport.

---

# 48. Browser Matrix

Use a practical browser matrix.

For example:

```text
Chromium
Firefox
WebKit
```

Run all browsers for critical smoke tests if the project supports them.

For full E2E coverage, one primary browser plus a smaller cross-browser smoke suite may be more efficient.

---

# 49. Accessibility E2E

Where accessibility is part of the frontend, test critical workflows for:

* keyboard navigation
* form labels
* focus management
* button accessibility
* error announcements
* modal behavior

Use automated accessibility tooling where appropriate.

Do not treat automated accessibility checks as a replacement for manual accessibility review.

---

# 50. Loading State Tests

Critical asynchronous operations should be tested.

Example:

```text
click checkout
↓
loading state appears
↓
submit cannot accidentally create duplicate operation
↓
request finishes
↓
success displayed
```

This is particularly important for idempotent financial actions.

---

# 51. Error State Tests

Verify user-visible error handling.

Examples:

```text
network failure
validation error
403
404
500
timeout
expired session
insufficient wallet
insufficient inventory
duplicate operation
```

The UI should display a useful safe message.

Do not expose stack traces or secrets.

---

# 52. Network Failure E2E

Important frontend workflows should have controlled network failure tests.

Example:

```text
submit checkout
↓
API returns 500/timeout
↓
UI displays failure
↓
user can recover
↓
no duplicate operation
```

Use controlled network interception rather than breaking the entire test environment.

---

# 53. Session Expiration

Test:

```text
authenticated user
↓
session expires
↓
user attempts protected action
↓
refresh/reauthentication behavior
↓
application returns to valid authenticated state or login
```

The application must not silently display stale protected data as valid.

---

# 54. Double-Click Protection

For important mutations:

```text
click submit twice
```

Verify:

```text
one business operation
```

This is especially important for:

```text
checkout
wallet operations
expense submission
customer creation where duplicates are costly
```

---

# 55. Browser Reload Tests

Important persistent states should survive reload appropriately.

Example:

```text
login
↓
open customer
↓
reload
↓
session remains valid
↓
customer page works
```

For completed transactions:

```text
checkout
↓
reload
↓
transaction still appears exactly once
```

---

# 56. Browser Back/Forward Tests

For important navigation:

```text
open customer
→ open wallet
→ back
→ forward
```

Verify no incorrect state or unauthorized information appears.

Do not write these tests unless the workflow is actually sensitive to browser navigation.

---

# 57. Idempotency and Refresh

E2E tests should ensure browser retries do not duplicate business operations.

Scenarios:

```text
double click
refresh during completion
retry after timeout
browser reconnect
```

Where the API supports idempotency, verify the business state remains correct.

---

# 58. Financial E2E Assertions

Financial workflows require stronger verification.

For every critical financial E2E:

```text
UI result
+
API result
+
database result
```

must agree.

For example:

```text
Expected = 950.00

UI balance = 950.00
API balance = 950.00
DB balance = 950.00
```

Use Decimal-safe comparisons.

Never use floating-point tolerance for monetary values unless explicitly justified.

---

# 59. Wallet E2E Invariant

After a successful wallet operation:

```text
wallet.balance >= 0
```

After a failed wallet operation:

```text
wallet.balance unchanged
```

After a duplicate operation:

```text
wallet.balance changes exactly once
```

---

# 60. Checkout E2E Invariants

After successful checkout:

```text
Sale exists
Wallet/payment state correct
Inventory correct
ProductUsage exists
Historical cost preserved
Profit correct
```

After failed checkout:

```text
No partial transaction
```

After duplicate checkout:

```text
One logical transaction
```

---

# 61. Permissions E2E Matrix

Maintain the following behavioral matrix:

| Action                   | Admin |           Employee |        Anonymous |
| ------------------------ | ----: | -----------------: | ---------------: |
| Login                    |     ✓ |                  ✓ |                - |
| View permitted customers |     ✓ |                  ✓ | according to API |
| Create customer          |     ✓ | according to rules |                ✗ |
| Modify customer          |     ✓ | according to rules |                ✗ |
| Manual wallet credit     |     ✓ |                  ✗ |                ✗ |
| Admin user management    |     ✓ |                  ✗ |                ✗ |
| Restricted logs          |     ✓ |                  ✗ |                ✗ |
| Financial reports        |     ✓ | according to rules |                ✗ |
| Public website API       |     ✓ |                  ✓ |   ✓ where public |

Always use the actual project authorization rules if they differ.

---

# 62. E2E Security Principle

Never consider a workflow secure because:

```text
button is hidden
```

A secure E2E test should attempt the operation anyway.

Example:

```text
employee
→ manually navigate to admin URL
→ directly call API
→ verify backend rejects
```

UI restrictions and backend authorization are separate layers.

Both matter.

---

# 63. E2E Test Orchestration

A standard E2E run should look conceptually like:

```text
Build frontend
↓
Build backend
↓
Start PostgreSQL
↓
Start Redis if required
↓
Run migrations
↓
Create safe E2E data
↓
Start Django
↓
Start frontend
↓
Wait for health checks
↓
Run smoke tests
↓
Run critical E2E tests
↓
Collect artifacts
↓
Destroy environment
```

Never begin browser tests before services are healthy.

---

# 64. Health Checks

Before E2E:

```text
GET health endpoint
```

or equivalent.

Verify:

```text
frontend available
backend available
database connected
Redis available where required
```

Do not let hundreds of E2E tests fail because Django was never started.

---

# 65. Retry Policy

Do not blindly configure huge retries.

Retries can hide flaky tests.

Recommended principle:

```text
CI retry = limited
local debugging = minimal
test itself = deterministic
```

A test that passes only after multiple retries should be considered unstable.

---

# 66. Flaky Test Management

A flaky test is a defect in the test suite.

When a test intermittently fails:

1. Reproduce it repeatedly.
2. Determine whether the application or test is nondeterministic.
3. Inspect timing.
4. Inspect network requests.
5. Inspect database state.
6. Inspect race conditions.
7. Fix the underlying problem.

Do not permanently hide the problem with:

```text
sleep()
```

or excessive retries.

---

# 67. Waiting Strategy

Never use arbitrary delays such as:

```javascript
await page.waitForTimeout(5000)
```

unless there is a very specific unavoidable reason.

Prefer:

```text
wait for element
wait for network response
wait for URL
wait for state
wait for expected text
wait for API condition
```

Example:

```javascript
await expect(page.getByTestId("checkout-success")).toBeVisible();
```

---

# 68. Stable Assertions

Prefer semantic assertions:

```text
expect button to be visible
expect customer name to appear
expect balance to equal expected amount
expect request to return expected status
```

Avoid:

```text
expect pixel coordinate
expect exact DOM hierarchy
expect arbitrary timing
expect implementation-generated CSS
```

---

# 69. Screenshots

Capture screenshots when:

* a test fails
* important regression tests fail
* visual regression is explicitly being tested

Do not capture enormous quantities of screenshots on every successful step unless needed.

---

# 70. Video and Trace

For CI failures, enable useful debugging artifacts.

Recommended:

```text
screenshot
trace
video where useful
console logs
network information
```

These make E2E failures diagnosable.

---

# 71. Browser Console Errors

E2E tests should monitor critical browser console errors.

Unexpected:

```text
TypeError
ReferenceError
Unhandled promise rejection
failed network request
```

should not silently pass the test.

Do not fail for harmless known messages without first understanding them.

---

# 72. API Errors During E2E

Monitor critical API responses.

Unexpected 500 errors should fail relevant E2E runs.

A UI can appear visually correct while an important API call silently failed.

---

# 73. Visual Regression

Use visual regression selectively.

Good candidates:

```text
login
dashboard
customer profile
checkout
report
public homepage
```

Do not snapshot every component.

Visual tests should complement behavioral E2E tests.

---

# 74. E2E Smoke Suite

The smoke suite should be fast.

Recommended minimum:

```text
[ ] Application loads
[ ] Login as admin
[ ] Dashboard loads
[ ] Login as employee
[ ] Employee dashboard loads
[ ] Public website loads
[ ] Public API responds
[ ] One critical customer flow
[ ] One critical checkout flow
```

Run this suite after every deployment.

---

# 75. Critical E2E Suite

The critical suite should include:

```text
[ ] Admin authentication
[ ] Employee authentication
[ ] Customer creation
[ ] Customer update
[ ] Visit creation
[ ] Package/service completion
[ ] Wallet operation
[ ] Employee wallet restriction
[ ] Checkout success
[ ] Checkout rollback
[ ] Checkout idempotency
[ ] Inventory update
[ ] Expense approval
[ ] Self-approval rejection
[ ] Report verification
[ ] Authorization bypass attempt
[ ] Public/private boundary
```

---

# 76. E2E Security Suite

Minimum security journeys:

```text
[ ] Anonymous → private endpoint
[ ] Employee → admin URL
[ ] Employee → admin API
[ ] Employee → restricted wallet operation
[ ] Employee → restricted logs
[ ] Employee → user administration
[ ] Cross-object access attempt
[ ] Role escalation attempt
[ ] Forbidden field injection
[ ] Expired authentication
[ ] Invalid authentication
```

---

# 77. CI Pipeline

Recommended:

```text
lint
↓
unit tests
↓
integration tests
↓
build
↓
start E2E environment
↓
smoke E2E
↓
critical E2E
↓
security E2E
↓
artifacts
```

For pull requests, run an appropriately sized suite.

For releases, run the complete E2E suite.

---

# 78. GitHub Actions Requirements

The CI workflow should:

* install exact dependencies
* start PostgreSQL
* start Redis if required
* build frontend
* run migrations
* create E2E users
* start backend
* start frontend
* wait for health checks
* run Playwright/browser tests
* upload screenshots on failure
* upload traces on failure
* report test results
* clean up services

Do not include production credentials.

---

# 79. Test Parallelization

Parallelize independent E2E tests carefully.

Tests must not share mutable resources.

Avoid hard-coded:

```text
customer name
email
phone number
idempotency key
```

Use unique deterministic identifiers:

```text
E2E_ADMIN_CUSTOMER_<worker>
```

or equivalent.

---

# 80. Database Strategy for E2E

E2E tests should run against a real PostgreSQL database.

Recommended:

```text
dedicated E2E database
```

Reset between suites/runs.

For highly isolated environments, use:

```text
Docker PostgreSQL
```

Start from a known clean state.

---

# 81. E2E Test Accounts

Create dedicated accounts:

```text
e2e-admin
e2e-employee
```

Use strong random passwords generated for the test environment.

Never reuse real user accounts.

Never commit real passwords into source control.

---

# 82. Test Secrets

Use:

```text
CI secret store
environment variables
test-only secret files
```

Never commit:

```text
production JWT secret
production database password
production API key
real email credentials
```

---

# 83. E2E Data Naming

Use recognizable prefixes:

```text
E2E_
```

Example:

```text
E2E Customer 001
E2E Service 001
E2E Product 001
```

This makes debugging test database state easier.

---

# 84. Debugging Failed E2E Tests

When an E2E fails, inspect in this order:

```text
1. Browser screenshot
2. Playwright trace/video
3. Browser console
4. Network response
5. Backend logs
6. Database state
7. Application implementation
```

Do not immediately change the assertion.

Determine why the user journey failed.

---

# 85. Root Cause Classification

Every failure should be classified as:

```text
TEST BUG
APPLICATION BUG
ENVIRONMENT BUG
DATA BUG
TIMING/RACE CONDITION
EXTERNAL SERVICE FAILURE
```

Fix the correct layer.

---

# 86. E2E Regression Tests

Every important production bug should become an E2E regression test when it represents a user-visible workflow.

Example:

```text
User could submit checkout twice
↓
duplicate Sale
↓
fix implementation
↓
add E2E double-submit test
↓
permanently protect workflow
```

---

# 87. Avoid Overusing E2E

Do not create E2E tests for:

```text
every model field
every serializer field
every service function
every simple CRUD variation
every status code permutation
```

Those belong in unit/integration tests.

E2E should remain focused on user journeys.

---

# 88. Ideal E2E Test Pyramid

Use approximately:

```text
          E2E
        /     \
      few     few

    Integration
   /             \
 many             many

       Unit
  very many
```

The majority of tests should be faster unit/integration tests.

The E2E layer should protect the most important complete workflows.

---

# 89. Example Canonical E2E

Conceptual Playwright example:

```typescript
test("admin can complete customer checkout", async ({ page }) => {
    // Login
    await page.goto("/login");

    await page.getByTestId("username").fill(E2E_ADMIN_USERNAME);
    await page.getByTestId("password").fill(E2E_ADMIN_PASSWORD);

    await page.getByTestId("login-button").click();

    // Customer
    await page.getByTestId("customers-link").click();
    await page.getByTestId("create-customer-button").click();

    await page.getByTestId("customer-name").fill("E2E Customer");
    await page.getByTestId("customer-save-button").click();

    // Checkout
    await page.getByTestId("checkout-button").click();

    await page.getByTestId("checkout-confirm-button").click();

    // User-visible assertion
    await expect(
        page.getByTestId("checkout-success")
    ).toBeVisible();

    // Backend-state verification should additionally confirm:
    // Sale
    // wallet
    // inventory
    // ProductUsage
    // profit
});
```

The actual selectors and routes must be derived from the real application.

Never invent selectors simply to make the example fit.

---

# 90. API-Only E2E

If a complete frontend does not exist for a workflow, E2E can still be performed through a real HTTP client.

Example:

```text
Create authentication session
↓
POST customer
↓
POST visit
↓
POST checkout
↓
GET customer
↓
GET wallet
↓
GET report
```

This is an E2E API workflow because it exercises the deployed application through its public API boundary.

However, do not call it UI E2E.

---

# 91. E2E vs API E2E

Use precise names:

```text
UI E2E
Browser → Frontend → Backend

API E2E
HTTP Client → API → Backend
```

Both are valuable.

---

# 92. API E2E Example

A critical API E2E flow:

```text
POST /auth/login
↓
obtain token/session
↓
POST /customers
↓
POST /visits
↓
POST /checkout
↓
GET /wallet
↓
GET /reports
```

Verify final state.

Use real running services.

Do not call internal Python functions directly.

---

# 93. Health and Readiness

The application should expose a readiness mechanism where practical.

E2E infrastructure should wait for:

```text
backend ready
database ready
frontend ready
```

before starting tests.

---

# 94. Timeouts

Use realistic timeouts.

Do not globally configure huge values to hide slow or broken behavior.

Investigate unexpectedly slow operations.

Critical workflows should have explicitly reasonable limits.

---

# 95. Performance E2E

E2E performance checks should focus on major user-facing actions:

```text
login
dashboard load
customer search
checkout
report generation
```

Use them as regression signals rather than precise load-testing infrastructure.

Dedicated load tests belong elsewhere.

---

# 96. Mobile E2E

For mobile workflows verify:

```text
login
navigation
forms
customer lookup
checkout
confirmation
```

Do not duplicate all desktop tests on mobile.

Use a prioritized mobile suite.

---

# 97. Accessibility and Keyboard E2E

At minimum test critical forms through keyboard interaction where practical:

```text
Tab
Enter
Escape
```

Verify focus moves logically and important dialogs can be operated without a mouse.

---

# 98. E2E Data Verification

For every important mutation:

```text
User-visible result
+
backend result
+
database result
```

should be consistent.

Example:

```text
UI:
Checkout successful
Balance: 800.00

API:
balance = 800.00

Database:
wallet.balance = 800.00
```

---

# 99. Financial Exactness

Financial assertions must use exact decimal values.

Example:

```text
Expected: 1250.50
Actual:   1250.50
```

Do not convert values to floating point.

---

# 100. Business Invariants

E2E tests must protect:

```text
wallet balance cannot become negative
one idempotency key creates one logical operation
historical product cost does not mutate
employees cannot perform admin-only actions
self-approval is forbidden
financial values retain Decimal precision
public users cannot access private data
```

---

# 101. E2E Completion Checklist

Before declaring E2E coverage complete:

```text
[ ] E2E environment is isolated
[ ] PostgreSQL is used
[ ] No production secrets are required
[ ] Admin login tested
[ ] Employee login tested
[ ] Anonymous access tested
[ ] Critical customer journey tested
[ ] Visit workflow tested
[ ] Package/service workflow tested
[ ] Wallet workflow tested
[ ] Employee wallet restriction tested
[ ] Checkout success tested
[ ] Checkout failure tested
[ ] Checkout idempotency tested
[ ] Inventory workflow tested
[ ] Historical cost tested
[ ] Expense workflow tested
[ ] Self-approval tested
[ ] Financial report workflow tested
[ ] Public/private boundaries tested
[ ] Authorization bypass tested
[ ] Cross-object authorization tested
[ ] Session expiration tested
[ ] Error states tested
[ ] Double submission tested
[ ] Browser reload tested where important
[ ] Stable selectors used
[ ] No arbitrary waits
[ ] Flaky tests investigated
[ ] Screenshots captured on failure
[ ] Trace/video available where useful
[ ] CI execution verified
[ ] Test data isolated
[ ] Complete suite is reproducible
```

---

# 102. Definition of Done

E2E work is complete when:

1. The application can be started in a dedicated E2E environment.
2. Critical user journeys can be completed automatically.
3. Authentication is tested from the user boundary.
4. Admin and employee authorization are tested.
5. Critical financial workflows are tested end-to-end.
6. Checkout success/failure/idempotency are covered.
7. Wallet integrity is verified.
8. Inventory and historical costs are verified.
9. Expense workflows are verified.
10. Reports reflect real workflow-generated data.
11. Public/private boundaries are tested.
12. Important security attacks are represented as user journeys.
13. Tests are deterministic.
14. Tests do not depend on production systems.
15. CI can execute the suite automatically.
16. Failures produce enough artifacts to diagnose the problem.
17. Every important user-visible production bug can be converted into a regression E2E test.

---

# 103. AI Agent Workflow

When an AI coding agent is instructed to implement E2E tests, it must follow this process.

## Step 1 — Inspect the Repository

Read:

```text
frontend
backend
URLs
API routes
authentication
permissions
models
services
serializers
existing unit tests
existing integration tests
existing E2E tests
Docker configuration
CI workflows
environment configuration
```

Never invent application behavior.

## Step 2 — Identify Real User Journeys

Map:

```text
persona
→ entry point
→ navigation
→ action
→ backend effect
→ visible result
```

## Step 3 — Reuse Existing Infrastructure

Reuse:

```text
fixtures
factories
test users
API helpers
Docker configuration
CI services
test environment
```

Do not create duplicate infrastructure unnecessarily.

## Step 4 — Implement High-Value E2E Tests

Start with:

```text
login
customer workflow
wallet
checkout
employee restrictions
expense approval
reports
security
```

## Step 5 — Run Locally

Run:

```text
smoke
→ critical suite
→ full E2E suite
```

## Step 6 — Investigate Failures

Never weaken an E2E test simply because the application currently fails.

Determine the root cause.

## Step 7 — Fix Application Bugs Separately

When the test exposes a real application defect:

```text
failing E2E
↓
identify root cause
↓
fix application
↓
rerun E2E
↓
keep regression test
```

## Step 8 — Verify CI

Run the same core E2E suite through CI.

---

# 104. Rules for AI Agents

The AI agent must NOT:

```text
- invent pages
- invent buttons
- invent API routes
- invent permissions
- invent financial rules
- mock the entire backend
- test only screenshots
- use arbitrary sleep delays
- disable flaky tests
- skip failing critical tests
- change expected values without verifying business rules
- use production credentials
- call production payment services
- claim tests pass without running them
```

The AI agent SHOULD:

```text
- inspect the actual application
- use real selectors
- use stable test IDs where possible
- use real authentication
- verify backend state
- preserve isolation
- create regression tests
- capture failure artifacts
- report exact test results
```

---

# 105. Reporting Format

After implementing E2E tests, the AI agent should report:

```text
E2E Tests Added
---------------

<files>

User Journeys Covered
---------------------

<journeys>

Security Scenarios
------------------

<scenarios>

Financial Workflows
-------------------

<workflows>

Infrastructure
--------------

<services>

Tests Executed
--------------

<commands>

Results
-------

<passed / failed / skipped>

Failures
--------

<exact failures>

Application Fixes
-----------------

<root-cause fixes>

CI Status
---------

<result>
```

Never report an unexecuted test as passing.

---

# 106. Golden Rule

The ultimate E2E question is:

> "Can a real user complete this important task through the actual application, and does the system end in exactly the correct business and user-visible state?"

For critical workflows, verify:

```text
User action
+
Frontend state
+
HTTP/API behavior
+
Authentication
+
Authorization
+
Business logic
+
Database state
+
Financial invariants
+
Final user-visible result
```

An E2E test is successful only when the entire chain is correct.
