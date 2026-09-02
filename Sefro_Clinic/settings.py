import os
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')


def env_bool(name, default='False'):
    return os.environ.get(name, default).strip().lower() in ('1', 'true', 'yes')


def env_list(name, default=''):
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


# Throttling must not interfere with the test suite.
TESTING = any(
        s in {'test', 'pytest', 'pytest-django'}
        for s in sys.argv
    )

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured(
        'DJANGO_SECRET_KEY is not set. Copy .env.example to .env and fill in the values.'
    )

DEBUG = env_bool('DJANGO_DEBUG')

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost')

CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',
    'drf_spectacular_sidecar',
    'corsheaders',
    'accounts',
    'customers',
    'inventory',
    'logs',
    'website',
    'finance',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'logs.middleware.RequestUserMiddleware',
]

ROOT_URLCONF = 'Sefro_Clinic.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'Sefro_Clinic' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'Sefro_Clinic.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'sefro_clinic'),
        'USER': os.environ.get('POSTGRES_USER', 'postgres'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
        'HOST': os.environ.get('POSTGRES_HOST', '127.0.0.1'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.ScryptPasswordHasher',
]

LANGUAGE_CODE = 'fa-ir'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

AUTH_USER_MODEL = 'accounts.ClinicUser'

# --- HTTPS / transport security (enable on the host, behind TLS) -------------
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT')
SECURE_HSTS_SECONDS = 31536000 if SECURE_SSL_REDIRECT and not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_SSL_REDIRECT
SECURE_HSTS_PRELOAD = SECURE_SSL_REDIRECT
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

# --- JWT --------------------------------------------------------------------
# Access token lifetime: prod default 15 min (900s), dev/test can override via env.
# REFRESH_TOKEN_LIFETIME 7d is standard.
ACCESS_TOKEN_LIFETIME = int(os.environ.get('JWT_ACCESS_TOKEN_LIFETIME', '900') or 900)
REFRESH_TOKEN_LIFETIME = int(os.environ.get('JWT_REFRESH_TOKEN_LIFETIME', '604800') or 604800)

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(seconds=ACCESS_TOKEN_LIFETIME),
    'REFRESH_TOKEN_LIFETIME': timedelta(seconds=REFRESH_TOKEN_LIFETIME),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': False,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

JWT_AUTH_COOKIE = 'access_token'
JWT_AUTH_REFRESH_COOKIE = 'refresh_token'
JWT_AUTH_COOKIE_SECURE = env_bool('DJANGO_JWT_COOKIE_SECURE', str(SECURE_SSL_REDIRECT))
JWT_AUTH_COOKIE_HTTP_ONLY = True
JWT_AUTH_COOKIE_SAMESITE = 'Lax'

# When cookies are the transport, keep tokens out of the JSON body so XSS
# cannot read them from a parseable response. Prod default False.
RETURN_TOKENS_IN_BODY = env_bool('DJANGO_RETURN_TOKENS_IN_BODY', 'False')

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'accounts.authentication.CookieJWTAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'EXCEPTION_HANDLER': 'rest_framework.views.exception_handler',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        # Login/refresh endpoints use the scoped 'auth' rate; keep it strict outside tests.
        'auth': '100000/min' if TESTING else os.environ.get('THROTTLE_AUTH_RATE', '10/min'),
        'contact': '100000/min' if TESTING else os.environ.get('THROTTLE_CONTACT_RATE', '5/min'),
        'anon': '100000/min' if TESTING else os.environ.get('THROTTLE_ANON_RATE', '60/min'),
        'user': '100000/min' if TESTING else os.environ.get('THROTTLE_USER_RATE', '600/min'),
    },
}

# --- CORS -------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS')
CORS_ALLOW_ALL_ORIGINS = env_bool('CORS_ALLOW_ALL_ORIGINS')
CORS_ALLOW_CREDENTIALS = True

# --- API docs ---------------------------------------------------------------
DOCS_PUBLIC = env_bool('DJANGO_DOCS_PUBLIC')

SPECTACULAR_SETTINGS = {
    'TITLE': 'Sefro Clinic API',
    'DESCRIPTION': 'Backend API for clinic management, customers, payments, and inventory.',
    'VERSION': '1.0.0',
    'TAGS': [
        {'name': 'Authentication', 'description': 'Login, token refresh, and current user endpoints.'},
        {'name': 'Employees', 'description': 'Employee account management.'},
        {'name': 'Dashboard', 'description': 'Sales and operational summaries.'},
        {'name': 'Customers', 'description': 'Customer profile and search endpoints.'},
        {'name': 'Services', 'description': 'Clinic service catalog.'},
        {'name': 'Visits', 'description': 'Customer visit records and selected services.'},
        {'name': 'Payments', 'description': 'Customer payments and totals.'},
        {'name': 'Products', 'description': 'Product catalog.'},
        {'name': 'Finance', 'description': 'Accounting, exchange rates, and financial reports.'},
        {'name': 'Wallet', 'description': 'Customer wallet ledger and rewards.'},
        {'name': 'Exchange Rates', 'description': 'USD/Toman exchange rate configuration.'},
        {'name': 'Packages', 'description': 'Service and product bundles.'},
        {'name': 'Expenses', 'description': 'Operational expense recording and approval.'},
        {'name': 'Reports', 'description': 'Profit, revenue, and wallet reporting.'},
    ],
    'SWAGGER_UI_DIST': 'SIDECAR',
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
    'DISABLE_ERRORS_AND_WARNINGS': True,
}

CLINIC_ADMIN_USERNAME = os.environ.get('CLINIC_ADMIN_USERNAME', '')
CLINIC_ADMIN_PASSWORD = os.environ.get('CLINIC_ADMIN_PASSWORD', '')
if not CLINIC_ADMIN_USERNAME or not CLINIC_ADMIN_PASSWORD:
    raise ImproperlyConfigured(
        'CLINIC_ADMIN_USERNAME and CLINIC_ADMIN_PASSWORD must be set in .env.'
    )
CLINIC_ADMIN = {
    'username': CLINIC_ADMIN_USERNAME,
    'password': CLINIC_ADMIN_PASSWORD,
    'first_name': 'System',
    'last_name': 'Admin',
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '{levelname} {asctime} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
    },
    'loggers': {
        'django.request': {
            'level': 'WARNING',
            'propagate': True,
        },
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Finance / accounting defaults ------------------------------------------
# Fallback exchange rate (Toman per 1 USD) used only when no ExchangeRate row
# is configured. Always prefer configuring a real rate via the finance API.
FINANCE_DEFAULT_USD_TO_TOMAN_RATE = Decimal(
    os.environ.get('FINANCE_DEFAULT_USD_TO_TOMAN_RATE', '100000')
)

# --- Exchange-rate provider --------------------------------------------------
# Provider abstraction: 'database' (default, DB-cached) or 'external' (HTTP fetch + DB cache).
# External provider uses standard library urllib; no extra deps.
EXCHANGE_RATE_PROVIDER = os.environ.get('EXCHANGE_RATE_PROVIDER', 'database')
EXCHANGE_RATE_API_URL = os.environ.get('EXCHANGE_RATE_API_URL', '')
EXCHANGE_RATE_API_KEY = os.environ.get('EXCHANGE_RATE_API_KEY', '')
EXCHANGE_RATE_TIMEOUT = int(os.environ.get('EXCHANGE_RATE_TIMEOUT', '5') or 5)
EXCHANGE_RATE_CACHE_TTL = int(os.environ.get('EXCHANGE_RATE_CACHE_TTL', '3600') or 3600)
EXCHANGE_RATE_BACKUP_API_URL = os.environ.get('EXCHANGE_RATE_BACKUP_API_URL', '')
EXCHANGE_RATE_BACKUP_API_KEY = os.environ.get('EXCHANGE_RATE_BACKUP_API_KEY', '')
