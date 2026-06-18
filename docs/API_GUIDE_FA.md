# راهنمای کوتاه API کلینیک سفرو

آدرس Swagger:
`http://127.0.0.1:8000/api/docs/`

بیشتر endpointها نیاز به توکن دارند. با endpoint ورود، توکن‌های `access` و `refresh` داخل کوکی‌های `HttpOnly` ذخیره می‌شوند و مرورگر در درخواست‌های بعدی آن‌ها را خودکار می‌فرستد.

اگر خواستید به‌صورت دستی با header کار کنید، بعد از گرفتن توکن در Swagger روی `Authorize` بزنید و مقدار زیر را وارد کنید:

```text
Bearer YOUR_ACCESS_TOKEN
```

## Authentication

این بخش برای ورود کاربر، تمدید توکن و گرفتن اطلاعات کاربر لاگین‌شده است.

| Method | Endpoint | توضیح |
| --- | --- | --- |
| POST | `/api/auth/token/` | با `username` و `password` لاگین می‌کند، `access` و `refresh` token می‌دهد و هر دو را در کوکی ذخیره می‌کند. |
| POST | `/api/auth/token/refresh/` | با `refresh` token داخل body یا کوکی، یک `access` token جدید می‌دهد و کوکی `access_token` را تازه می‌کند. |
| POST | `/api/auth/logout/` | کوکی‌های `access_token` و `refresh_token` را پاک می‌کند. |
| GET | `/api/auth/me/` | اطلاعات کاربر فعلی را برمی‌گرداند. |

## Employees

این بخش برای مدیریت کارمندهاست. ساخت کارمند فقط برای ادمین مجاز است.

| Method | Endpoint | توضیح |
| --- | --- | --- |
| POST | `/api/auth/employees/` | یک کارمند جدید می‌سازد. فیلدهای اصلی: `username`, `password`, `first_name`, `last_name`, `phone_number`. |

## Dashboard

این بخش خلاصه وضعیت کلینیک را نشان می‌دهد؛ مثل تعداد مشتری، مشتری وفادار، فروش روزانه، هفتگی، ماهانه، سالانه و هشدار کمبود موجودی.

| Method | Endpoint | توضیح |
| --- | --- | --- |
| GET | `/api/dashboard/` | آمار کلی داشبورد و نمودارهای فروش را برمی‌گرداند. |

## Customers

این بخش برای ثبت، مشاهده، جستجو، و ویرایش مشتری‌هاست. مشتری شامل نام، موبایل، کد ملی، کد `bitmoji` و اطلاعات محاسبه‌شده مثل تعداد مراجعه و مشتری وفادار است.

| Method | Endpoint | توضیح |
| --- | --- | --- |
| GET | `/api/customers/` | لیست مشتری‌ها را می‌دهد. برای جستجو از `?search=` استفاده کنید. |
| POST | `/api/customers/` | مشتری جدید ثبت می‌کند. |
| GET | `/api/customers/{id}/` | جزئیات یک مشتری، مراجعات و پرداخت‌های او را می‌دهد. |
| PUT | `/api/customers/{id}/` | تمام اطلاعات مشتری را ویرایش می‌کند. |
| PATCH | `/api/customers/{id}/` | بخشی از اطلاعات مشتری را ویرایش می‌کند. |
| DELETE | `/api/customers/{id}/` | مشتری را حذف می‌کند. |

## Services

این بخش لیست خدمات کلینیک را مدیریت می‌کند؛ مثل مراجعه پزشک، Facial، Laser و کربن‌تراپی.

| Method | Endpoint | توضیح |
| --- | --- | --- |
| GET | `/api/services/` | لیست خدمات را می‌دهد. |
| POST | `/api/services/` | خدمت جدید ثبت می‌کند. |
| GET | `/api/services/{id}/` | جزئیات یک خدمت را می‌دهد. |
| PUT | `/api/services/{id}/` | تمام اطلاعات خدمت را ویرایش می‌کند. |
| PATCH | `/api/services/{id}/` | بخشی از اطلاعات خدمت را ویرایش می‌کند. |
| DELETE | `/api/services/{id}/` | خدمت را حذف می‌کند. |

## Visits

این بخش برای ثبت مراجعه مشتری است. هر مراجعه می‌تواند چند خدمت داشته باشد و باعث افزایش تعداد مراجعه مشتری می‌شود. بعد از ۵ مراجعه، مشتری وفادار حساب می‌شود.

| Method | Endpoint | توضیح |
| --- | --- | --- |
| GET | `/api/visits/` | لیست مراجعات را می‌دهد. |
| POST | `/api/visits/` | مراجعه جدید ثبت می‌کند. فیلدهای اصلی: `customer`, `staff`, `visit_date`, `services`. |
| GET | `/api/visits/{id}/` | جزئیات یک مراجعه را می‌دهد. |
| PUT | `/api/visits/{id}/` | تمام اطلاعات مراجعه را ویرایش می‌کند. |
| PATCH | `/api/visits/{id}/` | بخشی از اطلاعات مراجعه را ویرایش می‌کند. |
| DELETE | `/api/visits/{id}/` | مراجعه را حذف می‌کند. |

## Payments

این بخش پرداخت‌های مشتری را مدیریت می‌کند و در داشبورد برای محاسبه فروش استفاده می‌شود.

| Method | Endpoint | توضیح |
| --- | --- | --- |
| GET | `/api/payments/` | لیست پرداخت‌ها را می‌دهد. |
| POST | `/api/payments/` | پرداخت جدید ثبت می‌کند. فیلدهای اصلی: `customer`, `visit`, `amount`, `payment_method`, `paid_at`. |
| GET | `/api/payments/{id}/` | جزئیات یک پرداخت را می‌دهد. |
| PUT | `/api/payments/{id}/` | تمام اطلاعات پرداخت را ویرایش می‌کند. |
| PATCH | `/api/payments/{id}/` | بخشی از اطلاعات پرداخت را ویرایش می‌کند. |
| DELETE | `/api/payments/{id}/` | پرداخت را حذف می‌کند. |

## Products

این بخش برای تعریف محصولات کلینیک است. محصول شامل نام، کد `SKU`، توضیح و قیمت واحد است.

| Method | Endpoint | توضیح |
| --- | --- | --- |
| GET | `/api/inventory/products/` | لیست محصولات را می‌دهد. |
| POST | `/api/inventory/products/` | محصول جدید ثبت می‌کند. |
| GET | `/api/inventory/products/{id}/` | جزئیات یک محصول را می‌دهد. |
| PUT | `/api/inventory/products/{id}/` | تمام اطلاعات محصول را ویرایش می‌کند. |
| PATCH | `/api/inventory/products/{id}/` | بخشی از اطلاعات محصول را ویرایش می‌کند. |
| DELETE | `/api/inventory/products/{id}/` | محصول را حذف می‌کند. |

## Inventory

این بخش موجودی هر محصول را نگه می‌دارد و مشخص می‌کند موجودی کم شده یا نه.

| Method | Endpoint | توضیح |
| --- | --- | --- |
| GET | `/api/inventory/items/` | لیست آیتم‌های انبار و موجودی آن‌ها را می‌دهد. |
| POST | `/api/inventory/items/` | برای یک محصول، آیتم انبار ثبت می‌کند. |
| GET | `/api/inventory/items/{id}/` | جزئیات یک آیتم انبار را می‌دهد. |
| PUT | `/api/inventory/items/{id}/` | تمام اطلاعات آیتم انبار را ویرایش می‌کند. |
| PATCH | `/api/inventory/items/{id}/` | بخشی از اطلاعات آیتم انبار را ویرایش می‌کند. |
| DELETE | `/api/inventory/items/{id}/` | آیتم انبار را حذف می‌کند. |

## Stock Movements

این بخش ورود و خروج کالا از انبار را ثبت می‌کند. با ثبت حرکت `in` موجودی زیاد می‌شود و با `out` موجودی کم می‌شود.

| Method | Endpoint | توضیح |
| --- | --- | --- |
| GET | `/api/inventory/movements/` | لیست گردش‌های انبار را می‌دهد. |
| POST | `/api/inventory/movements/` | ورود یا خروج کالا را ثبت می‌کند. فیلدهای اصلی: `inventory_item`, `movement_type`, `quantity`. |
| GET | `/api/inventory/movements/{id}/` | جزئیات یک گردش انبار را می‌دهد. |
| PUT | `/api/inventory/movements/{id}/` | تمام اطلاعات گردش انبار را ویرایش می‌کند. |
| PATCH | `/api/inventory/movements/{id}/` | بخشی از اطلاعات گردش انبار را ویرایش می‌کند. |
| DELETE | `/api/inventory/movements/{id}/` | گردش انبار را حذف می‌کند. |
