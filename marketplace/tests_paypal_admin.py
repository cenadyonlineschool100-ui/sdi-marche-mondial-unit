from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Order, PayPalPayment, PayPalWebhookEvent


@override_settings(
    PAYPAL_MODE='sandbox',
    PAYPAL_CLIENT_ID='private-client-id-value',
    PAYPAL_CLIENT_SECRET='private-client-secret-value',
    PAYPAL_WEBHOOK_ID='private-webhook-id-value',
    PAYPAL_CHECKOUT_ENABLED=True,
)
class PayPalPaymentAdminTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username='paypal-admin',
            email='paypal-admin@example.test',
            password='test-password',
            is_staff=True,
            is_superuser=True,
        )
        self.staff = user_model.objects.create_user(
            username='paypal-staff',
            email='paypal-staff@example.test',
            password='test-password',
            is_staff=True,
        )
        self.customer = user_model.objects.create_user(
            username='paypal-customer',
            email='paypal-customer@example.test',
            password='test-password',
        )
        self.url = reverse('paypal_payment_admin')

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_regular_user_is_denied(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_staff_without_paypal_permission_is_denied(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_admin_sees_sandbox_status_transactions_and_webhook_events_without_secrets(self):
        order = Order.objects.create(
            buyer=self.customer,
            total_amount=Decimal('19.99'),
            delivery_address='Test address',
            payment_method='int_paypal',
            payment_status='pending',
        )
        PayPalPayment.objects.create(
            order=order,
            amount=order.total_amount,
            currency='USD',
            status='created',
        )
        PayPalWebhookEvent.objects.create(
            event_id='EVENT-ADMIN-TEST',
            event_type='PAYMENT.CAPTURE.COMPLETED',
        )
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sandbox')
        self.assertContains(response, 'Transactions PayPal récentes')
        self.assertContains(response, 'PAYMENT.CAPTURE.COMPLETED')
        self.assertContains(response, '⭐ Gestion Carte Visa')
        self.assertNotContains(response, 'private-client-id-value')
        self.assertNotContains(response, 'private-client-secret-value')
        self.assertNotContains(response, 'private-webhook-id-value')

    @patch(
        'marketplace.paypal_admin.paypal_api_request',
        return_value={
            'webhooks': [{
                'id': 'private-webhook-id-value',
                'url': 'https://example.test/api/paypal/webhook/',
                'event_types': [
                    {'name': 'PAYMENT.CAPTURE.COMPLETED'},
                    {'name': 'PAYMENT.CAPTURE.DENIED'},
                ],
            }],
        },
    )
    def test_admin_can_test_connection_and_webhook_status(self, api_request):
        self.client.force_login(self.admin)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Connexion PayPal établie')
        self.assertContains(response, 'PAYMENT.CAPTURE.DENIED')
        self.assertNotContains(response, 'private-webhook-id-value')
        api_request.assert_called_once_with('GET', '/v1/notifications/webhooks')

    def test_connection_test_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)

        response = csrf_client.post(self.url)

        self.assertEqual(response.status_code, 403)
