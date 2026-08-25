from rest_framework.test import APIClient

from accounts.models import ClinicUser

ADMIN_USERNAME = 'sefro_admin'
ADMIN_PASSWORD = 'SefroAdmin-Test-2026!'
EMPLOYEE_PASSWORD = 'Employee-Test-2026!'


def make_admin(username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    user, created = ClinicUser.objects.get_or_create(
        username=username,
        defaults={
            'role': ClinicUser.Role.ADMIN,
            'is_staff': True,
            'is_superuser': True,
        },
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


def login(client, username, password):
    response = client.post('/api/auth/token/', {
        'username': username,
        'password': password,
    }, format='json')
    assert response.status_code == 200, f'login failed for {username}: {response.status_code}'
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')
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
