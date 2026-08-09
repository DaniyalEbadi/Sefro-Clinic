import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured(
        'DJANGO_SECRET_KEY is not set. Copy .env.example to .env and fill in the values.'
    )
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('1', 'true', 'yes')
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'drf_spectacular',
    'drf_spectacular_sidecar',
    'corsheaders',
    'accounts',
    'customers',
    'inventory',
    'logs',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
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

STATIC_URL = 'static/'

AUTH_USER_MODEL = 'accounts.ClinicUser'

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
}

JWT_AUTH_COOKIE = 'access_token'
JWT_AUTH_REFRESH_COOKIE = 'refresh_token'
JWT_AUTH_COOKIE_SECURE = False
JWT_AUTH_COOKIE_HTTP_ONLY = True
JWT_AUTH_COOKIE_SAMESITE = 'Lax'

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
    ],
    'SWAGGER_UI_DIST': 'SIDECAR',
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
    'DISABLE_ERRORS_AND_WARNINGS': True,
}

# Apply Windows/Farsi locale fix for drf-spectacular (after REST_FRAMEWORK/SPECTACULAR_SETTINGS are defined)
import Sefro_Clinic.spectacular_fix  # noqa

CORS_ALLOW_ALL_ORIGINS = True

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

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
