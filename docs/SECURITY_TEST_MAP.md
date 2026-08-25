# Security Test Coverage — OWASP Top 10 (2021) Map

| OWASP Category | Covered By | Status |
|---|---|---|
| A01 Broken Access Control | `tests/security/test_authorization_security.py` (IDOR, vertical/horizontal escalation, admin hiding, mass assignment), `tests/integration/test_reports_api.py::ReportsAccessTests`, `customers/tests/e2e` unauth tests | ✅ |
| A02 Cryptographic Failures | Argon2 hashing + password validators (`tests/security/test_input_validation_security.py::WeakPasswordPolicyTests`, bootstrap policy), cookie Secure/HttpOnly/SameSite + HSTS/SSL-redirect (`test_headers_cookies.py`) | ✅ |
| A03 Injection | SQLi payloads on search/login (`test_input_validation_security.py::SqlInjectionTests`), stored XSS round-trip, NUL-byte/surrogate rejection (`test_audit_and_input_hardening.py::NullByteInjectionTests`), type-confusion & 500-hardening (`ReserveEndpointRobustnessTests`) | ✅ |
| A04 Insecure Design | Brute-force throttle test, overlap double-booking prevention (`tests/integration/test_visit_overlap.py`); residual design risks recorded as **accepted** by the owner (see Accepted Risks below) | ✅ accepted-risk |
| A05 Security Misconfiguration | DEBUG-off default + headers suite (`test_headers_cookies.py`), docs gating (`test_docs_admin_security.py`), removed-admin regression, whitenoise middleware check | ✅ |
| A06 Vulnerable & Outdated Components | CI `security.yml`: pip-audit on runtime + dev requirements; local gate documented in README | ✅ |
| A07 Identification & Authentication Failures | `tests/security/test_auth_security.py` (brute force, tampered/expired/forged-key tokens, blacklist replay, credential-equivalence anti-enumeration), CSRF flow (`test_csrf_security.py`) | ✅ |
| A08 Software & Data Integrity Failures | HS256 forgery vs honest-signature pair (`test_auth_security.py`), gitleaks secret scan in CI, secrets-hygiene scanner (`test_secrets_hygiene.py`) incl. burned-credential canary | ✅ |
| A09 Security Logging & Monitoring Failures | Audit-trail integrity E2E (`tests/e2e/test_clinic_workflow.py::AuditTrailIntegrityE2ETests`), audit hash-leakage guards, failed-login/refresh log emission (`tests/security/test_owasp_monitoring.py`) | ✅ |
| A10 Server-Side Request Forgery | N/A — codebase performs zero outbound HTTP; no URL-fetch features exist. Revisit if integrations are added | ➖ N/A |

Run everything with:

```bash
python manage.py test --noinput          # full suite
python manage.py test tests.security     # security-only
```

## Accepted Risks (owner decisions, 2026-08-25)

1. **PII encryption-at-rest (F-08)** — national IDs / mobile numbers are stored in plaintext.
   Owner accepted residual risk for current clinic scale. Revisit if staff count grows,
   backups leave controlled infrastructure, or regulation requires it.
   Mitigations in place: host access control, `.env`/DB never committed, gitleaks scanning.
2. **Employee read-access to payment aggregates** — all authenticated staff can read
   `/api/payments/` and `/api/payments/by_service/`. Owner accepted: small trusted team;
   writes remain admin-only; reports stay admin-only.
3. **Tokens in login response body (F-05)** — kept for frontend compatibility;
   set `DJANGO_RETURN_TOKENS_IN_BODY=False` on the host once the frontend is
   confirmed cookie-only.

