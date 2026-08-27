"""Realistic, dependency-free data builders for performance scenarios.

Replaces the previous factory_boy-based factories which could not run
(factory_boy/Faker absent from the project). All values match the real
model constraints (unique mobile/national-id/SKU) and produce bulk
inserts sized for database benchmarking.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from customers.models import Customer, Payment, Service, Visit
from inventory.models import Product
from website.models import ContactMessage, SitePackage, SiteProduct, SiteService, TeamMember, Testimonial

User = get_user_model()

_ADMIN_USERNAME = 'sefro_admin'

STATUS_POOL = (
    [Visit.Status.COMPLETED] * 6
    + [Visit.Status.CONFIRMED] * 2
    + [Visit.Status.PENDING] * 1
    + [Visit.Status.CANCELED] * 1
)
METHOD_POOL = [Payment.Method.CASH, Payment.Method.CARD, Payment.Method.TRANSFER]
SATISFACTION_POOL = [3, 4, 5, 5, 4, 5, 2]


def make_admin():
    """Return the shared admin user, creating it on first use."""
    user = User.objects.filter(username=_ADMIN_USERNAME).first()
    if user is None:
        return User.objects.create_user(
            username=_ADMIN_USERNAME,
            password='SefroAdmin-Test-2026!',
            role=User.Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
    return user


def _staff_pool(size=5):
    """A small pool of employees used as visit staff."""
    staff = list(User.objects.filter(role=User.Role.EMPLOYEE)[:size])
    while len(staff) < size:
        idx = len(staff)
        staff.append(
            User.objects.create_user(
                username=f'perf_staff_{idx}',
                password='Staff-Perf-2026!',
                role=User.Role.EMPLOYEE,
            )
        )
    return staff


def ensure_services(count=25):
    services = list(Service.objects.all()[:count])
    next_id = Service.objects.count()
    while len(services) < count:
        services.append(
            Service.objects.create(
                name=f'خدمات پرفورمنس {next_id}',
                price=Decimal(f'{random.randint(200, 900)}0000.00'),
                time=random.choice([15, 30, 45, 60, 90]),
            )
        )
        next_id += 1
    return services


def create_customers(count):
    """Bulk-create ``count`` unique customers; returns queryset-independent ids."""
    existing = Customer.objects.count()
    batch = [
        Customer(
            first_name=f'مشتری{existing + i}',
            last_name=f'پرفورمنس{existing + i}',
            mobile_number=f'0914{existing + i:08d}'[:20],
            national_id=f'{(existing + i) % 1000:03d}-{existing + i:07d}',
            bitmoji_code=f'P{existing + i:06d}',
            satisfaction=random.choice(SATISFACTION_POOL),
            notes='نمونه یادداشت برای سناریو کارایی ' * 3,
        )
        for i in range(count)
    ]
    created = Customer.objects.bulk_create(batch, batch_size=2000)
    return created


def create_visits(customers, visits_per_customer=2, services=None, staff=None):
    """Bulk-create visits with an M2M service distribution."""
    services = services or ensure_services()
    staff = staff or _staff_pool()
    now = timezone.now()
    visits = []
    for c_idx, customer in enumerate(customers):
        base = now - timedelta(days=(c_idx % 120), hours=c_idx % 12)
        for v in range(visits_per_customer):
            start = base - timedelta(days=v * 23)
            visits.append(
                Visit(
                    customer=customer,
                    staff=random.choice(staff),
                    start_at=start,
                    end_at=start + timedelta(minutes=random.choice([30, 45, 60])),
                    status=random.choice(STATUS_POOL),
                    notes='',
                )
            )
    created = Visit.objects.bulk_create(visits, batch_size=2000)
    through = Visit.services.through
    links = []
    for visit in created:
        for service in random.sample(services, k=min(3, len(services))):
            links.append(through(visit=visit, service=service))
    through.objects.bulk_create(links, batch_size=5000)
    return created


def create_payments(customers, visits_by_customer=None, payments_per_customer=3):
    """Bulk-create payments spread over the trailing months."""
    visits_by_customer = visits_by_customer or {}
    payments = []
    now = timezone.now()
    for c_idx, customer in enumerate(customers):
        customer_visits = visits_by_customer.get(customer.id, [])
        for p in range(payments_per_customer):
            visit = random.choice(customer_visits) if customer_visits else None
            payments.append(
                Payment(
                    customer=customer,
                    visit=visit,
                    amount=Decimal(random.randint(30000, 5000000)),
                    payment_method=random.choice(METHOD_POOL),
                    paid_at=now - timedelta(days=(c_idx % 90), hours=p),
                )
            )
    return Payment.objects.bulk_create(payments, batch_size=2000)


def build_clinic_dataset(customers=200, visits_per_customer=2, payments_per_customer=2, services=25):
    """Create a coherent clinic dataset and return a summary dict.

    This is the default fixture behind API and load benchmarks: realistic
    relationship cardinality without million-row setup cost.
    """
    staff = _staff_pool()
    svc_objects = ensure_services(count=services)
    customer_rows = create_customers(customers)
    visit_rows = create_visits(
        customer_rows, visits_per_customer=visits_per_customer, services=svc_objects, staff=staff
    )
    visits_by_customer = {}
    for visit in visit_rows:
        visits_by_customer.setdefault(visit.customer_id, []).append(visit)
    payment_rows = create_payments(
        customer_rows, visits_by_customer=visits_by_customer, payments_per_customer=payments_per_customer
    )
    return {
        'customers': len(customer_rows),
        'visits': len(visit_rows),
        'payments': len(payment_rows),
        'services': len(svc_objects),
        'staff': len(staff),
    }


def create_products(count):
    """Bulk-create inventory products with deterministic SKUs."""
    start = Product.objects.count()
    rows = [
        Product(
            name=f'محصول انبار {start + i}',
            sku=f'SKU-{start + i:07d}',
            description='توضیح تست محصول برای سنجش کارایی. ',
            unit_price=Decimal(random.randint(50, 200)) * 1000,
            count=random.randint(0, 400),
            status=random.choice(['available'] * 7 + ['less', 'finished']),
            unit=random.choice(['عدد', 'بسته', 'میلی‌لیتر']),
        )
        for i in range(count)
    ]
    return Product.objects.bulk_create(rows, batch_size=2000)


def create_site_content(services=40, packages=12, products=30, team=10, testimonials=15):
    """Populate the public website v2 catalog tables."""
    svc_base = SiteService.objects.count()
    site_services = SiteService.objects.bulk_create(
        [
            SiteService(
                name=f'سرویس سایت {svc_base}-{i}',
                slug=f'site-service-{svc_base + i}',
                category=random.choice(list(SiteService.Category.values)),
                short_description='توضیح کوتاه خدمت',
                description='توضیح کامل خدمت کلینیک' * 8,
                price=Decimal(random.randint(150, 1500)) * 1000,
                duration_label='۴۵ دقیقه',
                is_active=True,
                sort_order=svc_base + i,
            )
            for i in range(services)
        ],
        batch_size=500,
    )
    pkg_base = SitePackage.objects.count()
    site_packages = SitePackage.objects.bulk_create(
        [
            SitePackage(
                name=f'پکیج سایت {pkg_base}-{i}',
                slug=f'site-package-{pkg_base + i}',
                tier=random.choice(list(SitePackage.Tier.values)),
                tagline='تگ‌لاین پکیج',
                badge='پیشنهاد ویژه',
                price=Decimal(random.randint(500, 8000)) * 10000,
                original_price=Decimal(random.randint(600, 9000)) * 10000,
                free_service_count=random.randint(0, 3),
                is_active=True,
                sort_order=pkg_base + i,
            )
            for i in range(packages)
        ],
        batch_size=200,
    )
    through = SitePackage.services.through
    SitePackage.services.through.objects.bulk_create(
        [through(sitepackage_id=p.id, siteservice_id=s.id) for p in site_packages for s in site_services[:5]],
        batch_size=1000,
    )
    prod_base = SiteProduct.objects.count()
    site_products = SiteProduct.objects.bulk_create(
        [
            SiteProduct(
                name=f'محصول فروشگاه {prod_base}-{i}',
                slug=f'site-product-{prod_base + i}',
                short_description='مرطوب‌کننده و ضدآفتاب',
                price=Decimal(random.randint(20, 200)) * 10000,
                is_active=True,
                sort_order=prod_base + i,
            )
            for i in range(products)
        ],
        batch_size=200,
    )
    team_rows = TeamMember.objects.bulk_create(
        [
            TeamMember(name=f'دکتر {i}', role='متخصص پوست', bio='سوابق حرفه‌ای ' * 15, sort_order=i)
            for i in range(team)
        ],
        batch_size=100,
    )
    testimonial_rows = Testimonial.objects.bulk_create(
        [
            Testimonial(customer_name=f'مراجعه‌کننده {i}', label='لیزر مو', text='تجربه عالی ' * 20, sort_order=i)
            for i in range(testimonials)
        ],
        batch_size=100,
    )
    return {
        'site_services': len(site_services),
        'site_packages': len(site_packages),
        'site_products': len(site_products),
        'team': len(team_rows),
        'testimonials': len(testimonial_rows),
    }


def contact_messages_for(user_count):
    """Pending website inquiries (public write endpoint load)."""
    return ContactMessage.objects.bulk_create(
        [
            ContactMessage(full_name=f'کاربر {i}', phone=f'0912{i:08d}', message='درخواست مشاوره ')
            for i in range(user_count)
        ],
        batch_size=500,
    )
