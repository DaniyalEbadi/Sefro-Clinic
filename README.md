# Sefro Clinic 🏥

**سیستم مدیریت کلینیک زیبایی** — یک API قدرتمند و امن برای مدیریت جامع کلینیک‌های زیبایی و بهداشتی.

A comprehensive RESTful backend API for beauty clinics, built with **Django 5.0** & **Django REST Framework**.

[![CI/CD](https://github.com/DaniyalEbadi/Sefro-Clinic/actions/workflows/ci.yml/badge.svg)](https://github.com/DaniyalEbadi/Sefro-Clinic/actions)

---

## ✨ ویژگی‌ها (Features)

- **مدیریت کاربران و کارمندان** — احراز هویت با JWT (Token + HttpOnly Cookie)
- **مدیریت مشتریان** — ثبت مشخصات، تاریخچه مراجعات و پرداخت‌ها
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
| PostgreSQL | پایگاه داده |
| Docker | اجرای کل پروژه با یک دستور |
| Gunicorn | سرور WSGI درون کانتینر |

---

## 🚀 نصب و راه‌اندازی (Installation)

> حداقل پیش‌نیاز: فقط **Docker Desktop**. بقیه چیزها (Python، PostgreSQL، Django) خودکار نصب می‌شوند.

---

### ✅ روش ۱ — اجرا با Docker (ساده‌ترین روش، پیشنهادی)

**قدم ۱ — نصب Docker Desktop:**
از https://www.docker.com/products/docker-desktop/ نصب و اجرا کنید (اگر نصب است، فقط مطمئن شوید باز است — آیکونش در تسک‌بار باشد).

**قدم ۲ — کلون کردن پروژه** (در PowerShell یا Terminal):

```powershell
git clone https://github.com/DaniyalEbadi/Sefro-Clinic.git
cd Sefro-Clinic
```

**قدم ۳ — ساختن فایل `.env`** (تنظیمات و رمزهای امن):

```powershell
# Windows PowerShell:
copy .env.example .env

# Linux / Mac:
cp .env.example .env
```

**قدم ۴ — پر کردن فایل `.env`:** فایل را با هر ویرایشگر متنی (Notepad) باز کنید و مقادیر زیر را عوض کنید:

| متغیر | چه چیزی بگذارم؟ |
|--------|----------------|
| `DJANGO_SECRET_KEY` | یک متن تصادفی بلند (حداقل ۵۰ حرف/عدد) — از https://djecrety.ir بگیرید یا خودتان تایپ کنید |
| `POSTGRES_PASSWORD` | یک رمز دلخواه برای دیتابیس (مثلاً `MyDb@12345`) |
| `CLINIC_ADMIN_USERNAME` | نام کاربری ادمین (مثلاً `admin`) |
| `CLINIC_ADMIN_PASSWORD` | رمز عبور ادمین (مثلاً `Admin@12345`) |

> ⚠️ بدون این فایل پروژه بالا نمی‌آید — این کار عمدی است (امنیتی). فایل `.env` هرگز در Git ذخیره نمی‌شود و فقط روی کامپیوتر شماست.

**قدم ۵ — اجرای کامل پروژه:**

```powershell
docker compose up -d --build
```

- بار اول ۲–۳ دقیقه طول می‌کشد (دانلود Python و نصب پکیج‌ها). دفعات بعد سریع است:
- فقط برای روشن/خاموش کردن بعدی: `docker compose up -d` و `docker compose down`

**قدم ۶ — باز کردن در مرورگر:**

| سرویس | آدرس |
|--------|------|
| **مستندات API (Swagger)** | http://127.0.0.1:8000/api/docs/ |
| **Django Admin** | http://127.0.0.1:8000/admin/ |

وارد شوید با **نام کاربری و رمزی که در `.env` گذاشتید** (کاربر ادمین هنگام اولین اجرا خودکار ساخته می‌شود).

**دستورهای مفید بعدی:**

```powershell
docker compose ps            # وضعیت سرویس‌ها (باید Up / Healthy باشد)
docker compose logs -f web   # دیدن لاگ‌های برنامه (خروج با Ctrl+C)
docker compose down          # متوقف کردن (داده‌ها حفظ می‌شوند)
docker compose down -v       # متوقف کردن + پاک کردن کامل دیتابیس
```

---

### 🐍 روش ۲ — اجرای دستی (بدون Docker، با venv)

**پیش‌نیازها:** Python 3.10 تا 3.12 و PostgreSQL نصب شده.

**قدم ۱ — ساخت دیتابیس** در PostgreSQL (با psql یا pgAdmin):

```sql
CREATE DATABASE sefro_clinic;
```

**قدم ۲ — کلون و آماده‌سازی:**

```powershell
git clone https://github.com/DaniyalEbadi/Sefro-Clinic.git
cd Sefro-Clinic
python -m venv venv
venv\Scripts\activate          # Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env         # Linux/Mac: cp .env.example .env
```

**قدم ۳ — ویرایش `.env`:** `DJANGO_SECRET_KEY` و `CLINIC_ADMIN_*` را پر کنید؛ `POSTGRES_PASSWORD` را رمز PostgreSQL خودتان بگذارید (اگر کاربر/نام دیتابیس متفاوت است، `POSTGRES_USER` و `POSTGRES_DB` را هم عوض کنید).

**قدم ۴ — اجرا:**

```powershell
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

---

### 🆘 رفع مشکلات (Troubleshooting)

| مشکل | راه‌حل |
|------|--------|
| خطای `DJANGO_SECRET_KEY is not set` یا `set POSTGRES_PASSWORD in .env` | فایل `.env` را از روی `.env.example` ساختی و مقادیرش را پر کردی؟ |
| خطای `port 8000 is already in use` | برنامه دیگری روی پورت ۸۰۰۰ است؛ آن را ببندید یا در `docker-compose.yml` خط `"8000:8000"` را به `"8080:8000"` تغییر دهید و آدرس http://127.0.0.1:8080 را باز کنید |
| مرورگر صفحه را باز نمی‌کند | اول `docker compose ps` بزنید (STATUS باید `Up`/`Healthy` باشد)، بعد `docker compose logs web` را ببینید |

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
Sefro-Clinic/
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
├── inventory/             # مدیریت انبار
│   ├── models.py          # Product, InventoryItem, StockMovement
│   ├── serializers.py
│   └── views.py
├── Sefro_Clinic/          # تنظیمات اصلی پروژه
│   ├── settings.py        # تنظیمات (زبان فارسی، JWT، CORS، .env و ...)
│   ├── urls.py            # مسیریابی اصلی
│   └── middleware.py
├── docs/                  # مستندات پروژه
├── Dockerfile             # ساخت ایمیج برنامه
├── docker-compose.yml     # اجرای کامل (web + PostgreSQL) با یک دستور
├── .env.example           # الگوی فایل تنظیمات امن (باید کپی شود به .env)
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
