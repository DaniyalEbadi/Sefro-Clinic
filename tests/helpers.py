import uuid

from rest_framework.test import APIClient

from accounts.models import ClinicUser
from customers.models import Customer

ADMIN_USERNAME = 'sefro_admin'
ADMIN_PASSWORD = 'SefroAdmin-Test-2026!'
EMPLOYEE_PASSWORD = 'Employee-Test-2026!'


def make_customer(**overrides):
    base = {
        'first_name': 'Test',
        'last_name': 'Customer',
        'mobile_number': '09120000000',
        'national_id': '000-0000000',
        'file_sys_id': f'FS{uuid.uuid4().hex[:36]}',
    }
    base.update(overrides)
    return Customer.objects.create(**base)


def make_admin(username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    try:
        user = ClinicUser.objects.get(username=username)
    except ClinicUser.DoesNotExist:
        return ClinicUser.objects.create_user(
            username=username,
            password=password,
            role=ClinicUser.Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
    if not user.check_password(password):
        user.set_password(password)
        user.save()
    return user


def make_employee(username='emp_user', password=EMPLOYEE_PASSWORD):
    try:
        user = ClinicUser.objects.get(username=username)
    except ClinicUser.DoesNotExist:
        return ClinicUser.objects.create_user(
            username=username,
            password=password,
            role=ClinicUser.Role.EMPLOYEE,
        )
    if not user.check_password(password):
        user.set_password(password)
        user.save()
    return user


def get_access_token(response):
    """Access token from the JSON body or the auth cookie.

    `RETURN_TOKENS_IN_BODY` decides the transport: dev/CI may return tokens in
    the body while production (and CI without .env) ships them as HTTP-only
    cookies only. Tests must accept either so they pass in both modes.
    """
    token = getattr(response, 'data', {}).get('access') or None
    if not token:
        cookie = response.cookies.get('access_token')
        token = cookie.value if cookie else None
    return token


def get_refresh_token(response):
    """Refresh token from the JSON body or the auth cookie (see get_access_token)."""
    token = getattr(response, 'data', {}).get('refresh') or None
    if not token:
        cookie = response.cookies.get('refresh_token')
        token = cookie.value if cookie else None
    return token


def login(client, username, password):
    response = client.post('/api/auth/token/', {
        'username': username,
        'password': password,
    }, format='json')
    assert response.status_code == 200, f'login failed for {username}: {response.status_code} {response.data}'
    access = get_access_token(response)
    assert access, f'no access token in response for {username}: data={response.data} cookies={list(response.cookies.keys())}'
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
    return response


def admin_client():
    client = APIClient()
    make_admin()
    login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    return client


def employee_client(username='emp_user', password=EMPLOYEE_PASSWORD):
    client = APIClient()
    make_employee(username=username, password=password)
    login(client, username, password)
    return client
