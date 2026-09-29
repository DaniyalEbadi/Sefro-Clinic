# Spec: Doctor Fixed Payment Per Visit

## Business Rule

A doctor receives a **fixed, pre-defined payment** for each visit they complete. This is **not** a percentage commission — it is a flat fee agreed upon in advance, paid per visit regardless of the service price or products used.

**Key distinction:** The doctor's payment is decoupled from the service price. A visit may generate $200 in revenue but the doctor earns a fixed $50. Another visit may generate $80 but the doctor still earns $50.

---

## Current State (What Exists Today)

| Concept | Model | Notes |
|---|---|---|
| Visit | `customers.Visit` | Has `staff` (doctor), `start_at`, `end_at`, `status` |
| Service | `customers.Service` | Has `price_usd` |
| Sale | `finance.Sale` | Links to `visit`, has `amount_usd`, `status` |
| ProductUsage | `finance.ProductUsage` | Has `is_commission` flag (currently used for commission tracking) |
| Expense | `finance.Expense` | Employee-submitted claims (DRAFT → SUBMITTED → APPROVED → PAID) |
| OperatingExpense | `finance.OperatingExpense` | Direct clinic costs, never touches Wallet/Sale |

**What does NOT exist:** A model that tracks "doctor earned $X for visit Y" as a first-class financial event.

---

## What Needs to Be Built

### 1. New Model: `DoctorPayment` (or `VisitPayment`)

```
finance.DoctorPayment
├── id
├── visit (FK → customers.Visit, unique=True)   # one payment per visit
├── doctor (FK → settings.AUTH_USER_MODEL)     # denormalized from visit.staff for query speed
├── amount_usd (Decimal)                         # the fixed fee
├── amount_toman (Decimal)                       # snapshot at creation
├── exchange_rate (Decimal)                      # snapshot
├── status (CharField)                           # PENDING → APPROVED → PAID
├── approved_by (FK → User, nullable)
├── approved_at (DateTime, nullable)
├── paid_at (DateTime, nullable)
├── created_at
└── updated_at
```

**Why `unique=True` on visit:** A doctor can only be paid once per visit. This prevents double-payment bugs.

### 2. Configuration: How Is the Fixed Amount Determined?

The architect must decide. Options:

| Option | Pros | Cons |
|---|---|---|
| **A. Fixed amount on the Doctor's user profile** | Simple; one field | Can't change per service or over time |
| **B. Fixed amount per Service** | Different services can pay different amounts | More flexible; needs a `doctor_payment_usd` field on `Service` |
| **C. Fixed amount per Doctor + Service pair** | Most flexible | Most complex; needs a through/join table |
| **D. Global flat rate for all doctors** | Simplest | Not realistic for different seniority levels |

**Recommendation:** Option B — add `doctor_payment_usd` to the `Service` model. This allows the clinic to set different fixed fees per service while keeping the data model simple. If a service has no `doctor_payment_usd`, the visit generates no doctor payment.

### 3. When Is the Doctor Payment Created?

**Trigger:** When a visit's status transitions to `COMPLETED`.

This should be implemented as a **Django signal** (`post_save` on `Visit`) or explicitly in the service layer function that completes the visit. The signal approach is cleaner:

```python
# customers/signals.py or finance/signals.py
@receiver(post_save, sender=Visit)
def create_doctor_payment(sender, instance, created, **kwargs):
    if instance.status == Visit.Status.COMPLETED and instance.staff:
        service = instance.services.first()  # or determine which service
        if service and service.doctor_payment_usd:
            DoctorPayment.objects.get_or_create(
                visit=instance,
                defaults={
                    'doctor': instance.staff,
                    'amount_usd': service.doctor_payment_usd,
                    ...
                }
            )
```

**Edge case:** What if a visit has multiple services? The architect must decide:
- Pay the highest `doctor_payment_usd` among the services?
- Pay the sum?
- Pay only for the primary service?

**Recommendation:** Pay the **highest** single service fee. A doctor does one visit, gets one payment.

### 4. Payment Workflow

The doctor payment should follow a similar approval flow to `Expense`:

```
PENDING → APPROVED → PAID
```

| Status | Meaning |
|---|---|
| `PENDING` | Auto-created when visit is completed; awaiting review |
| `APPROVED` | Admin/manager has confirmed the payment is valid |
| `PAID` | Money has been disbursed to the doctor |

**Who approves?** An admin or manager (not the doctor themselves — same rule as `Expense.approve_expense`).

### 5. Integration with Reporting

The `financial_summary` in `reporting.py` should include doctor payments as a cost line item. Currently it tracks:
- Product costs
- Welcome pack costs
- Employee expenses
- Operating expenses

**Add:** `doctor_payments` total (filtered by status=PAID or APPROVED, depending on accounting basis).

### 6. What About the Existing `is_commission` Flag?

The `ProductUsage.is_commission` flag currently exists. The architect must decide:

- **Option A:** Repurpose it to also track doctor payments (add a `DOCTOR_PAYMENT` value to the `is_commission` choices or a new field).
- **Option B:** Leave it as-is for product-level commission tracking, and keep `DoctorPayment` completely separate.

**Recommendation:** Option B — keep them separate. Doctor payment is a visit-level event, not a product-level event. Mixing them would create confusing semantics.

---

## Summary of Changes Needed

| File | Change |
|---|---|
| `customers/models.py` | Add `doctor_payment_usd` field to `Service` |
| `finance/models.py` | Add `DoctorPayment` model |
| `finance/services/doctor_payments.py` | New service module: create, approve, pay, cancel |
| `customers/signals.py` | Signal to auto-create `DoctorPayment` on visit completion |
| `finance/services/reporting.py` | Add doctor payment totals to `financial_summary` |
| Admin panels | Register `DoctorPayment` for admin management |
| Migrations | Auto-generated |

---

## Open Questions for the Architect

1. **Multiple services per visit:** Which service's `doctor_payment_usd` is used? (Recommend: highest)
2. **Rescheduled/cancelled visits:** If a visit is completed then later cancelled, should the doctor payment be reversed?
3. **Payment timing:** Is the doctor paid immediately on completion, or batched (e.g., monthly payroll)?
4. **Tax/deductions:** Are doctor payments gross or net? Does the clinic deduct anything?
5. **Historical data:** Do we need to backfill doctor payments for past visits?
