# Sefro Clinic 🏥

**سیستم مدیریت کلینیک زیبایی** — یک API قدرتمند و امن برای مدیریت جامع کلینیک‌های زیبایی و بهداشتی.

A comprehensive RESTful backend API for beauty clinics, built with **Django 5.0** & **Django REST Framework**.

---

## ✨ ویژگی‌ها (Features)

- **مدیریت کاربران و کارمندان** — احراز هویت با JWT (Token + HttpOnly Cookie)
- **مدیریت مشتریان** — ثبت مشخصات، تاریخچه مراجعات و پرداخت‌ها
- **نوبت‌دهی آنلاین** — سیستم رزرو وقت با وضعیت‌های مختلف
- **مدیریت خدمات** — تعریف و مدیریت خدمات کلینیک
- **انبارداری** — کنترل موجودی کالا، ردیابی ورود/خروج
- **داشبورد تحلیلی** — آمار فروش، مشتریان وفادار، هشدار موجودی
- **مستندات خودکار API** — Swagger UI و Redoc
- **زبان: فارسی** — پیش‌فرض: `fa-ir`، منطقه زمانی: `Asia/Tehran`

---

## 🛠 تکنولوژی‌ها (Tech Stack)

| تکنولوژی | توضیح |
|-----------|---------|
| Python 3.12+ | زبان برنامه‌نویسی |
| Django 5.0.14 | فریم‌ورک وب |
| Django REST Framework | ساخت API |
| SimpleJWT | احراز هویت JWT |
| drf-spectacular | مستندات Swagger/OpenAPI |
| Argon2 | هش کردن رمز عبور (امن‌ترین روش) |
| SQLite | پایگاه داده (قابل ارتقا به PostgreSQL) |

---

## 🚀 نصب و راه‌اندازی (Installation)

### پیش‌نیازها (Prerequisites)

- Python 3.12 یا بالاتر
- pip (Python package manager)

### مراحل نصب

```bash
# 1. کلون کردن پروژه
git clone https://github.com/DaniyalEbadi/Sefro-Clinic.git
cd Sefro-Clinic

# 2. ایجاد محیط مجازی
python -m venv venv

# 3. فعال‌سازی محیط مجازی
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 4. نصب وابستگی‌ها
pip install -r requirements.txt

# 5. اجرای مایگریشن‌ها
python manage.py migrate

# 6. اجرای سرور توسعه
python manage.py runserver
```

### کاربر پیش‌فرض ادمین (Default Admin)

> پس از اجرای `migrate`، کاربر ادمین به صورت خودکار ساخته می‌شود.

| کاربر | رمز عبور |
|-------|-----------|
| `sefro_admin` | `SefroClinic@2026` |

---

## 📖 مستندات API

پس از اجرای سرور:

| سرویس | آدرس |
|--------|-------|
| **Swagger UI** | http://127.0.0.1:8000/api/docs/ |
| **OpenAPI Schema** | http://127.0.0.1:8000/api/schema/ |
| **Django Admin** | http://127.0.0.1:8000/admin/ |

---

## 🔌 ساختار API (API Endpoints)

### 🔐 احراز هویت (`/api/auth/`)

| متد | مسیر | توضیح |
|------|------|---------|
| POST | `/api/auth/token/` | ورود و دریافت JWT |
| POST | `/api/auth/token/refresh/` | تمدید توکن |
| POST | `/api/auth/logout/` | خروج و پاک کردن کوکی‌ها |
| GET | `/api/auth/me/` | اطلاعات کاربر فعلی |

### 👥 کارمندان (`/api/auth/employees/`)

| متد | مسیر | توضیح |
|------|------|---------|
| GET | `/api/auth/employees/list/` | لیست کارمندان |
| POST | `/api/auth/employees/` | ایجاد کارمند جدید |
| GET/PUT/PATCH/DELETE | `/api/auth/employees/{id}/` | مدیریت کارمند |

### 👤 مشتریان (`/api/customers/`)

| متد | مسیر | توضیح |
|------|------|---------|
| GET | `/api/customers/` | لیست مشتریان (با قابلیت جستجو) |
| POST | `/api/customers/` | ثبت مشتری جدید |
| GET/PUT/PATCH/DELETE | `/api/customers/{id}/` | مدیریت مشتری |

### 💇 خدمات (`/api/services/`)

| متد | مسیر | توضیح |
|------|------|---------|
| GET | `/api/services/` | لیست خدمات |
| POST | `/api/services/` | تعریف خدمت جدید |
| GET/PUT/PATCH/DELETE | `/api/services/{id}/` | مدیریت خدمات |

### 📅 نوبت‌ها (`/api/appointments/`)

| متد | مسیر | توضیح |
|------|------|---------|
| GET | `/api/appointments/` | لیست نوبت‌ها |
| POST | `/api/appointments/` | ثبت نوبت جدید |
| GET/PUT/PATCH/DELETE | `/api/appointments/{id}/` | مدیریت نوبت |

### 🏪 انبار (`/api/inventory/`)

| متد | مسیر | توضیح |
|------|------|---------|
| GET | `/api/inventory/products/` | لیست محصولات |
| POST | `/api/inventory/products/` | ثبت محصول جدید |
| GET | `/api/inventory/items/` | موجودی انبار |
| POST | `/api/inventory/items/` | ثبت آیتم انبار |
| GET | `/api/inventory/movements/` | گردش انبار |
| POST | `/api/inventory/movements/` | ثبت ورود/خروج کالا |

### 📊 داشبورد (`/api/dashboard/`)

| متد | مسیر | توضیح |
|------|------|---------|
| GET | `/api/dashboard/` | آمار کلینیک (مشتریان، فروش، هشدارها) |

---

## 📂 ساختار پروژه (Project Structure)

```
Sefro_Clinic/
├── accounts/              # مدیریت کاربران و احراز هویت
│   ├── models.py          # مدل کاربر سفارشی (ClinicUser)
│   ├── serializers.py     # سریالایزرهای کاربران
│   ├── views.py           # ویوهای احراز هویت و کارمندان
│   ├── authentication.py  # احراز هویت JWT با Cookie
│   └── signals.py         # ایجاد خودکار ادمین
├── customers/             # مدیریت مشتریان
│   ├── models.py          # Customer, Visit, Payment, Service
│   ├── serializers.py
│   └── views.py           # ModelViewSet + Dashboard
├── appointments/          # سیستم نوبت‌دهی
│   ├── models.py          # Appointment
│   ├── serializers.py
│   └── views.py
├── inventory/             # مدیریت انبار
│   ├── models.py          # Product, InventoryItem, StockMovement
│   ├── serializers.py
│   └── views.py
├── Sefro_Clinic/          # تنظیمات اصلی پروژه
│   ├── settings.py        # تنظیمات (زبان فارسی، JWT، CORS و ...)
│   ├── urls.py            # مسیریابی اصلی
│   └── middleware.py
├── docs/                  # مستندات پروژه
├── manage.py              # ابزار مدیریت Django
└── requirements.txt       # وابستگی‌ها
```

---

## 🧪 اجرای تست‌ها (Running Tests)

```bash
python manage.py test
```

تست‌ها در سه سطح نوشته شده‌اند:
- **Unit Tests**: تست مدل‌ها و سریالایزرها
- **Integration Tests**: تست ویوها
- **E2E Tests**: تست سناریوهای کامل API

---

## 🤝 مشارکت (Contributing)

1. Fork کنید
2. Branch بسازید (`git checkout -b feature/your-feature`)
3. Commit کنید (`git commit -m 'Add feature'`)
4. Push کنید (`git push origin feature/your-feature`)
5. Pull Request ثبت کنید

---

## 📜 مجوز (License)

این پروژه برای استفاده شخصی و تجاری آزاد است.

---

ساخته شده با ❤️ توسط **Sefro Clinic Team**
