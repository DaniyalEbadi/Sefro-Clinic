from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from django.test import TestCase

from accounts.models import ClinicUser
from customers.models import Customer, Service, Visit, Payment


class CustomersE2ETest(TestCase):
    def _ensure_admin(self):
        admin, _ = ClinicUser.objects.get_or_create(
            username='sefro_admin',
            defaults={'role': ClinicUser.Role.ADMIN, 'is_staff': True, 'is_superuser': True},
        )
        if not admin.check_password('SefroClinic@2026'):
            admin.set_password('SefroClinic@2026')
            admin.save()
        return admin

    def setUp(self):
        self.client = APIClient()
        self._ensure_admin()
        login_resp = self.client.post('/api/auth/token/', {
            'username': 'sefro_admin', 'password': 'SefroClinic@2026',
        }, format='json')
        self.token = login_resp.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

        self.service = Service.objects.create(name='Consultation', description='General check')
        self.customer = Customer.objects.create(
            first_name='Ali', last_name='Rezaei',
            mobile_number='09121111111', national_id='001-0000001',
            bitmoji_code='B001',
        )

    def test_01_dashboard(self):
        resp = self.client.get('/api/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('customer_count', resp.data)

    def test_02_customer_full_crud(self):
        list_resp = self.client.get('/api/customers/')
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(list_resp.data['results']), 1)

        create_resp = self.client.post('/api/customers/', {
            'first_name': 'Sara', 'last_name': 'Mohammadi',
            'mobile_number': '09122222222', 'national_id': '002-0000002',
            'bitmoji_code': 'B002',
        }, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        cid = create_resp.data['id']

        detail_resp = self.client.get(f'/api/customers/{cid}/')
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_resp.data['first_name'], 'Sara')

        update_resp = self.client.put(f'/api/customers/{cid}/', {
            'first_name': 'Sara Updated', 'last_name': 'Mohammadi',
            'mobile_number': '09122222222', 'national_id': '002-0000002',
            'bitmoji_code': 'B002',
        }, format='json')
        self.assertEqual(update_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(update_resp.data['first_name'], 'Sara Updated')

        patch_resp = self.client.patch(f'/api/customers/{cid}/', {
            'notes': 'VIP customer',
        }, format='json')
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_resp.data['notes'], 'VIP customer')

        delete_resp = self.client.delete(f'/api/customers/{cid}/')
        self.assertEqual(delete_resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_03_service_full_crud(self):
        list_resp = self.client.get('/api/services/')
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(list_resp.data['count'], 1)

        create_resp = self.client.post('/api/services/', {
            'name': 'Massage', 'description': 'Relaxing massage',
        }, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        sid = create_resp.data['id']

        detail_resp = self.client.get(f'/api/services/{sid}/')
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)

        update_resp = self.client.put(f'/api/services/{sid}/', {
            'name': 'Deep Massage', 'description': 'Deep tissue massage',
        }, format='json')
        self.assertEqual(update_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(update_resp.data['name'], 'Deep Massage')

        patch_resp = self.client.patch(f'/api/services/{sid}/', {
            'description': 'Updated description',
        }, format='json')
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)

        delete_resp = self.client.delete(f'/api/services/{sid}/')
        self.assertEqual(delete_resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_04_visit_full_crud(self):
        now = timezone.now()
        start_at = '1404-03-23 14:00'
        end_at = '1404-03-23 15:00'

        create_resp = self.client.post('/api/visits/', {
            'customer': self.customer.id,
            'start_at': start_at,
            'end_at': end_at,
            'services': [self.service.id],
        }, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        vid = create_resp.data['id']

        list_resp = self.client.get('/api/visits/')
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)

        detail_resp = self.client.get(f'/api/visits/{vid}/')
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)

        update_resp = self.client.put(f'/api/visits/{vid}/', {
            'customer': self.customer.id,
            'start_at': '1404-04-10 10:00',
            'end_at': '1404-04-10 11:00',
            'services': [self.service.id],
            'notes': 'Follow-up needed',
            'status': 'confirmed',
        }, format='json')
        self.assertEqual(update_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(update_resp.data['notes'], 'Follow-up needed')
        self.assertEqual(update_resp.data['status'], 'confirmed')

        patch_resp = self.client.patch(f'/api/visits/{vid}/', {
            'status': 'completed',
        }, format='json')
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_resp.data['status'], 'completed')

        delete_resp = self.client.delete(f'/api/visits/{vid}/')
        self.assertEqual(delete_resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_05_visit_search_by_customer_name(self):
        start_at = '1404-05-01 10:00'
        end_at = '1404-05-01 11:00'
        self.client.post('/api/visits/', {
            'customer': self.customer.id,
            'start_at': start_at,
            'end_at': end_at,
            'services': [self.service.id],
        }, format='json')

        search_resp = self.client.get('/api/visits/?search=Ali')
        self.assertEqual(search_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(search_resp.data['results']), 1)

        search_resp = self.client.get('/api/visits/?search=Rezaei')
        self.assertEqual(search_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(search_resp.data['results']), 1)

    def test_06_visit_filter_by_status(self):
        start_at = '1404-06-01 10:00'
        end_at = '1404-06-01 11:00'
        self.client.post('/api/visits/', {
            'customer': self.customer.id,
            'start_at': start_at,
            'end_at': end_at,
            'services': [self.service.id],
            'status': 'confirmed',
        }, format='json')

        filter_resp = self.client.get('/api/visits/?status=confirmed')
        self.assertEqual(filter_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(filter_resp.data['results']), 1)

        filter_resp = self.client.get('/api/visits/?status=canceled')
        self.assertEqual(filter_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(filter_resp.data['results']), 0)

    def test_07_visit_custom_actions(self):
        start_at = '1404-07-01 10:00'
        end_at = '1404-07-01 11:00'
        create_resp = self.client.post('/api/visits/', {
            'customer': self.customer.id,
            'start_at': start_at,
            'end_at': end_at,
            'services': [self.service.id],
        }, format='json')
        vid = create_resp.data['id']
        self.assertEqual(create_resp.data['status'], 'pending')

        confirm_resp = self.client.post(f'/api/visits/{vid}/confirm/')
        self.assertEqual(confirm_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(confirm_resp.data['status'], 'confirmed')

        complete_resp = self.client.post(f'/api/visits/{vid}/complete/')
        self.assertEqual(complete_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(complete_resp.data['status'], 'completed')

        create_resp2 = self.client.post('/api/visits/', {
            'customer': self.customer.id,
            'start_at': '1404-08-01 10:00',
            'end_at': '1404-08-01 11:00',
            'services': [self.service.id],
        }, format='json')
        vid2 = create_resp2.data['id']

        cancel_resp = self.client.post(f'/api/visits/{vid2}/cancel/')
        self.assertEqual(cancel_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(cancel_resp.data['status'], 'canceled')

    def test_05_payment_full_crud(self):
        now = timezone.now()
        visit = Visit.objects.create(
            customer=self.customer, start_at=now, end_at=now
        )
        visit.services.add(self.service)

        create_resp = self.client.post('/api/payments/', {
            'customer': self.customer.id,
            'visit': visit.id,
            'amount': '150000',
            'payment_method': 'cash',
            'paid_at': '1404-03-23 14:00',
        }, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        pid = create_resp.data['id']

        list_resp = self.client.get('/api/payments/')
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)

        detail_resp = self.client.get(f'/api/payments/{pid}/')
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)

        update_resp = self.client.put(f'/api/payments/{pid}/', {
            'customer': self.customer.id,
            'visit': visit.id,
            'amount': '200000',
            'payment_method': 'card',
            'paid_at': '1404-04-01 12:00',
        }, format='json')
        self.assertEqual(update_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(update_resp.data['amount'], '200000.00')

        patch_resp = self.client.patch(f'/api/payments/{pid}/', {
            'notes': 'Paid in full',
        }, format='json')
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)

        delete_resp = self.client.delete(f'/api/payments/{pid}/')
        self.assertEqual(delete_resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_06_unauthenticated_access_fails(self):
        self.client.credentials()
        self.client.cookies.clear()
        resp = self.client.get('/api/customers/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
