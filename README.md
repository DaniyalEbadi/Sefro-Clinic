# Sefro Clinic 🏥

**سیستم مدیریت کلینیک زیبایی** — یک API قدرتمند و امن برای مدیریت جامع کلینیک‌های زیبایی و بهداشتی.

A comprehensive RESTful backend API for beauty clinics, built with **Django 5.0** & **Django REST Framework**.

[![CI/CD](https://github.com/DaniyalEbadi/Sefro-Clinic/actions/workflows/ci.yml/badge.svg)](https://github.com/DaniyalEbadi/Sefro-Clinic/actions)

---

## 🧪 اجرای تست‌ها (Running Tests)

```bash
# نصب ابزارهای توسعه
pip install -r requirements-dev.txt

# کل مجموعه تست (188 تست)
python manage.py test --noinput

# فقط تست‌های امنیتی
python manage.py test tests.security

# فقط تست‌های واحد / یکپارچه / E2E
python manage.py test tests.unit
python manage.py test tests.integration
python manage.py test tests.e2e

# پوشش کد (Coverage) با حد آستانه ۹۰٪
coverage run --source=accounts,customers,logs,Sefro_Clinic manage.py test --noinput
coverage report --fail-under=90
coverage html

# لینت
ruff check .

# اسکن امنیتی
bandit -q -r accounts customers logs Sefro_Clinic -x "**/migrations/*" -ll
pip-audit -r requirements.txt --no-deps

# تست عملکرد (اختیاری)
$env:SEFRO_PERF='1'; python manage.py test tests.performance   # Windows
SEFRO_PERF=1 python manage.py test tests.performance           # Linux/Mac
```

ساختار تست‌ها:
- `accounts/tests/`, `customers/tests/`, `logs/tests.py` — تست‌های موجود هر اپ (unit/integration/e2e)
- `tests/unit/` — تبدیل تاریخ شمسی و کلیدهای دوره‌ای گزارش‌ها
- `tests/integration/` — گزارش‌ها، داشبورد، تجمیع پرداخت‌ها، محدودیت‌های دیتابیس
- `tests/e2e/` — چرخه کامل ویزیت از رزرو تا پرداخت و لاگ ممیز
- `tests/security/` — احراز هویت، مجوزها/IDOR، CSRF، هدرهای امنیتی، تزریق، XSS، افشای اسرار
- `tests/performance/` — دود عملکردی (فقط با متغیر `SEFRO_PERF=1` اجرا می‌شود)

## ⚙️ CI/CD

دو ورک‌فلو در GitHub Actions اجرا می‌شود:

| ورک‌فلو | فایل | کاری که می‌کند |
|---------|------|----------------|
| **Tests** | `.github/workflows/tests.yml` | لینت (ruff)، کل تست‌ها روی PostgreSQL 16، حداقل پوشش ۹۰٪، بیلد Docker |
| **Security** | `.github/workflows/security.yml` | SAST با bandit، ممیزی وابستگی‌ها با pip-audit، جستجوی رمز لو رفته با gitleaks (هر دوشنبه زمان‌بندی‌شده) |

هر دو ورک‌فلو روی Pull Request و push به `master` اجرا می‌شوند؛ شکست هر مرحله باعث قرمز شدن CI می‌شود.

متغیرهای لازم برای CI: هیچ Secret واقعی لازم نیست؛ فقط مقادیر ساختگی تست در خود ورک‌فلو تعریف شده‌اند. برای انتشار Docker Image، دو Secret به نام‌های `DOCKERHUB_USERNAME` و `DOCKERHUB_TOKEN` را در تنظیمات ریپو اضافه کنید.

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
