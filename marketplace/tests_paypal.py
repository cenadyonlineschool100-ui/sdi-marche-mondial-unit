import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from .models import (
    Cart, CartItem, Order, OrderItem, PayPalPayment, PayPalStockEvent,
    PayPalStockReservation, PayPalWebhookEvent, Product, Shop, Transaction,
)
from .paypal_gateway import PayPalConfigurationError, paypal_api_request
from .forms import OrderForm
from .paypal_stock import (
    InsufficientStock,
    begin_paypal_capture,
    create_paypal_stock_reservation,
    decrement_available_stock,
)


@override_settings(
    PAYPAL_MODE='sandbox',
    PAYPAL_CLIENT_ID='sandbox-client',
    PAYPAL_CLIENT_SECRET='sandbox-secret',
    PAYPAL_WEBHOOK_ID='sandbox-webhook',
    PAYPAL_CHECKOUT_ENABLED=True,
)
class PayPalCheckoutTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.buyer = user_model.objects.create_user(
            username='paypal-buyer',
            email='paypal-buyer@example.test',
            password='test-password',
        )
        self.other_buyer = user_model.objects.create_user(
            username='other-buyer',
            email='other-buyer@example.test',
            password='test-password',
        )
        self.order = Order.objects.create(
            buyer=self.buyer,
            total_amount=Decimal('25.50'),
            delivery_address='1 Test Street',
            payment_method='int_paypal',
            payment_status='pending',
            status='pending',
        )
        self.seller = user_model.objects.create_user(
            username='paypal-stock-seller',
            email='paypal-stock-seller@example.test',
            password='test-password',
        )
        self.shop = Shop.objects.create(owner=self.seller, name='PayPal Stock Shop')
        self.product = Product.objects.create(
            shop=self.shop,
            name='Reserved product',
            price_ht=Decimal('25.50'),
            quantity=3,
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=1,
            price_ht=self.product.price_ht,
        )
        self.product.quantity -= 1
        self.product.save(update_fields=['quantity'])
        self.reservation = create_paypal_stock_reservation(
            self.order,
            [(self.product, 1)],
        )
        self.client.force_login(self.buyer)

    def test_create_order_uses_server_amount_and_owner_order(self):
        with patch(
            'marketplace.paypal_views.paypal_api_request',
            return_value={'id': 'PAYPAL-ORDER-1', 'status': 'CREATED'},
        ) as api_request:
            response = self.client.post(
                reverse('paypal_create_order', args=[self.order.pk]),
                data=json.dumps({'amount': '0.01'}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'id': 'PAYPAL-ORDER-1'})
        payload = api_request.call_args.kwargs['payload']
        self.assertEqual(
            payload['purchase_units'][0]['amount'],
            {'currency_code': 'USD', 'value': '25.50'},
        )
        payment = PayPalPayment.objects.get(order=self.order)
        self.assertEqual(payment.paypal_order_id, 'PAYPAL-ORDER-1')
        self.assertEqual(payment.amount, self.order.total_amount)

    def test_paypal_api_request_uses_the_bearer_token(self):
        token_response = Mock()
        token_response.json.return_value = {'access_token': 'sandbox-access-token'}
        api_response = Mock()
        api_response.content = b'{}'
        api_response.json.return_value = {'id': 'PAYPAL-ORDER-TOKEN'}
        with (
            patch('marketplace.paypal_gateway.requests.post', return_value=token_response),
            patch('marketplace.paypal_gateway.requests.request', return_value=api_response) as api_request,
        ):
            paypal_api_request('GET', '/v2/checkout/orders/ORDER')

        headers = api_request.call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], 'Bearer sandbox-access-token')

    def test_create_order_rejects_another_users_order(self):
        other_order = Order.objects.create(
            buyer=self.other_buyer,
            total_amount=Decimal('12.00'),
            delivery_address='2 Test Street',
            payment_method='int_paypal',
            payment_status='pending',
            status='pending',
        )
        with patch('marketplace.paypal_views.paypal_api_request') as api_request:
            response = self.client.post(
                reverse('paypal_create_order', args=[other_order.pk]),
                data='{}',
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 404)
        api_request.assert_not_called()

    def test_create_order_rejects_already_paid_order(self):
        payment = PayPalPayment.objects.create(
            order=self.order,
            paypal_order_id='PAYPAL-ORDER-PAID',
            amount=self.order.total_amount,
            currency='USD',
            status='completed',
        )
        self.order.payment_status = 'approved'
        self.order.save(update_fields=['payment_status'])

        with patch('marketplace.paypal_views.paypal_api_request') as api_request:
            response = self.client.post(
                reverse('paypal_create_order', args=[self.order.pk]),
                data='{}',
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 409)
        api_request.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'completed')

    @patch('marketplace.views.CommissionManager.calcul_commande_from_order', return_value={})
    def test_order_confirmation_renders_sandbox_checkout(self, _commission):
        response = self.client.get(reverse('order_confirm', args=[self.order.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'paypal-button-container')
        self.assertContains(response, 'currency=USD&intent=capture')
        self.assertContains(response, reverse('paypal_create_order', args=[self.order.pk]))

    @override_settings(PAYPAL_CHECKOUT_ENABLED=False)
    def test_direct_order_form_hides_paypal_when_not_configured(self):
        payment_methods = dict(OrderForm().fields['payment_method'].choices)

        self.assertNotIn('eur_paypal', payment_methods)
        self.assertNotIn('int_paypal', payment_methods)

    @patch('marketplace.views.notify_order_sellers')
    @patch('marketplace.views.create_persistent_notification')
    @patch('marketplace.views.DeliveryAssignmentManager.assign_delivery_agent_to_order', return_value=None)
    @patch(
        'marketplace.views.CommissionManager.calcul_commande',
        return_value={'total_commande': Decimal('30.00')},
    )
    def test_cart_checkout_creates_pending_paypal_order_without_wallet_debit(
        self, _commission, _assignment, _notification, _seller_notification
    ):
        seller = get_user_model().objects.create_user(
            username='paypal-seller',
            email='paypal-seller@example.test',
            password='test-password',
        )
        shop = Shop.objects.create(owner=seller, name='PayPal Test Shop')
        product = Product.objects.create(
            shop=shop,
            name='Test item',
            price_ht=Decimal('25.50'),
            quantity=3,
        )
        cart = Cart.objects.create(user=self.buyer)
        CartItem.objects.create(cart=cart, product=product, quantity=1)

        response = self.client.post(
            reverse('checkout'),
            {'delivery_address': '1 Test Street', 'payment_method': 'int_paypal'},
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(
            buyer=self.buyer,
            payment_method='int_paypal',
            product_name__startswith='Panier',
        )
        self.assertEqual(order.payment_status, 'pending')
        self.assertEqual(order.status, 'pending')
        self.assertEqual(order.total_amount, Decimal('30.00'))
        self.assertEqual(Transaction.objects.get(
            sender=self.buyer,
            type='payment_int_paypal',
        ).status, 'pending')
        product.refresh_from_db()
        self.assertEqual(product.quantity, 2)
        self.assertFalse(CartItem.objects.filter(cart=cart).exists())
        self.assertFalse(PayPalPayment.objects.filter(order=order).exists())
        reservation = PayPalStockReservation.objects.get(order=order)
        self.assertEqual(reservation.status, 'reserved')
        self.assertEqual(reservation.items.get().quantity, 1)

    @patch('marketplace.views.notify_order_sellers')
    @patch('marketplace.views.create_persistent_notification')
    @patch('marketplace.business_logic.DeliveryAssignmentManager.assign_delivery_roundrobin')
    @patch('marketplace.views.CommissionManager.get_config', return_value=Decimal('0'))
    def test_direct_paypal_order_creates_stock_reservation(
        self, _commission, _assignment, _notification, _seller_notification
    ):
        response = self.client.post(
            reverse('order_product', args=[self.product.pk]),
            {
                'quantity': '1',
                'delivery_address': '2 Test Street',
                'buyer_address_details': '',
                'buyer_lat': '',
                'buyer_lng': '',
                'map_failed': 'true',
                'payment_method': 'int_paypal',
            },
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(
            buyer=self.buyer,
            product_name=self.product.name,
            pk__gt=self.order.pk,
        )
        self.assertEqual(order.payment_status, 'pending')
        reservation = PayPalStockReservation.objects.get(order=order)
        self.assertEqual(reservation.status, 'reserved')
        self.assertEqual(reservation.items.get().quantity, 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 1)

    def test_capture_marks_order_paid_only_after_completed_matching_capture(self):
        payment_transaction = Transaction.objects.create(
            sender=self.buyer,
            amount=self.order.total_amount,
            type='payment_int_paypal',
            status='pending',
        )
        payment = PayPalPayment.objects.create(
            order=self.order,
            transaction=payment_transaction,
            paypal_order_id='PAYPAL-ORDER-2',
            amount=self.order.total_amount,
            currency='USD',
        )
        capture = {
            'id': 'CAPTURE-1',
            'status': 'COMPLETED',
            'amount': {'currency_code': 'USD', 'value': '25.50'},
        }
        paypal_response = {
            'id': payment.paypal_order_id,
            'status': 'COMPLETED',
            'purchase_units': [{
                'reference_id': f'SDI-ORDER-{self.order.pk}',
                'payments': {'captures': [capture]},
            }],
        }

        with patch(
            'marketplace.paypal_views.paypal_api_request',
            return_value=paypal_response,
        ) as api_request:
            response = self.client.post(
                reverse('paypal_capture_order', args=[self.order.pk]),
                data=json.dumps({'paypal_order_id': payment.paypal_order_id}),
                content_type='application/json',
            )
            retry_response = self.client.post(
                reverse('paypal_capture_order', args=[self.order.pk]),
                data=json.dumps({'paypal_order_id': payment.paypal_order_id}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(api_request.call_count, 1)
        self.order.refresh_from_db()
        payment.refresh_from_db()
        payment_transaction.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'approved')
        self.assertEqual(self.order.status, 'awaiting_delivery')
        self.assertEqual(payment.status, 'completed')
        self.assertEqual(payment.capture_id, 'CAPTURE-1')
        self.assertEqual(payment_transaction.status, 'approved')
        self.assertTrue(Transaction.objects.filter(
            sender=self.buyer,
            type='escrow_hold',
            status='pending',
            amount=self.order.total_amount,
        ).exists())
        self.product.refresh_from_db()
        self.reservation.refresh_from_db()
        self.assertEqual(self.product.quantity, 2)
        self.assertEqual(self.reservation.status, 'consumed')
        self.assertEqual(
            PayPalStockEvent.objects.filter(order=self.order, event_type='consumed').count(),
            1,
        )

    def test_mismatched_capture_does_not_mark_order_paid(self):
        payment = PayPalPayment.objects.create(
            order=self.order,
            paypal_order_id='PAYPAL-ORDER-3',
            amount=self.order.total_amount,
            currency='USD',
        )
        paypal_response = {
            'id': payment.paypal_order_id,
            'purchase_units': [{
                'reference_id': f'SDI-ORDER-{self.order.pk}',
                'payments': {'captures': [{
                    'id': 'CAPTURE-WRONG-AMOUNT',
                    'status': 'COMPLETED',
                    'amount': {'currency_code': 'USD', 'value': '1.00'},
                }]},
            }],
        }
        with patch(
            'marketplace.paypal_views.paypal_api_request',
            return_value=paypal_response,
        ):
            response = self.client.post(
                reverse('paypal_capture_order', args=[self.order.pk]),
                data=json.dumps({'paypal_order_id': payment.paypal_order_id}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 502)
        self.order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'pending')
        self.assertEqual(self.order.status, 'pending')
        self.assertEqual(payment.status, 'created')
        self.assertIsNone(payment.capture_id)
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'capturing')

    def test_verified_webhook_is_idempotent(self):
        payment = PayPalPayment.objects.create(
            order=self.order,
            paypal_order_id='PAYPAL-ORDER-4',
            amount=self.order.total_amount,
            currency='USD',
        )
        event = {
            'id': 'WH-EVENT-1',
            'event_type': 'PAYMENT.CAPTURE.COMPLETED',
            'resource': {
                'id': 'CAPTURE-2',
                'supplementary_data': {
                    'related_ids': {'order_id': payment.paypal_order_id},
                },
            },
        }
        capture = {
            'id': 'CAPTURE-2',
            'status': 'COMPLETED',
            'amount': {'currency_code': 'USD', 'value': '25.50'},
            'supplementary_data': {
                'related_ids': {'order_id': payment.paypal_order_id},
            },
        }
        with (
            patch('marketplace.paypal_views.verify_webhook_signature', return_value=True),
            patch('marketplace.paypal_views.paypal_api_request', return_value=capture) as api_request,
        ):
            first_response = self.client.post(
                reverse('paypal_webhook'),
                data=json.dumps(event),
                content_type='application/json',
                HTTP_PAYPAL_TRANSMISSION_ID='transmission-id',
            )
            duplicate_response = self.client.post(
                reverse('paypal_webhook'),
                data=json.dumps(event),
                content_type='application/json',
                HTTP_PAYPAL_TRANSMISSION_ID='transmission-id',
            )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(api_request.call_count, 1)
        self.assertEqual(PayPalWebhookEvent.objects.count(), 1)
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.reservation.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'approved')
        self.assertEqual(self.product.quantity, 2)
        self.assertEqual(self.reservation.status, 'consumed')
        self.assertEqual(
            PayPalStockEvent.objects.filter(order=self.order, event_type='consumed').count(),
            1,
        )

    def test_invalid_webhook_signature_is_rejected_without_recording_event(self):
        event = {
            'id': 'WH-EVENT-INVALID',
            'event_type': 'PAYMENT.CAPTURE.COMPLETED',
            'resource': {},
        }
        with patch(
            'marketplace.paypal_views.verify_webhook_signature',
            return_value=False,
        ):
            response = self.client.post(
                reverse('paypal_webhook'),
                data=json.dumps(event),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(PayPalWebhookEvent.objects.filter(
            event_id=event['id'],
        ).exists())
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'pending')

    def test_denied_webhook_marks_payment_failed_and_allows_retry(self):
        payment_transaction = Transaction.objects.create(
            sender=self.buyer,
            amount=self.order.total_amount,
            type='payment_int_paypal',
            status='pending',
        )
        payment = PayPalPayment.objects.create(
            order=self.order,
            transaction=payment_transaction,
            paypal_order_id='PAYPAL-ORDER-DENIED',
            amount=self.order.total_amount,
            currency='USD',
        )
        event = {
            'id': 'WH-EVENT-DENIED',
            'event_type': 'PAYMENT.CAPTURE.DENIED',
            'resource': {
                'id': 'CAPTURE-DENIED',
                'supplementary_data': {
                    'related_ids': {'order_id': payment.paypal_order_id},
                },
            },
        }
        with patch(
            'marketplace.paypal_views.verify_webhook_signature',
            return_value=True,
        ):
            response = self.client.post(
                reverse('paypal_webhook'),
                data=json.dumps(event),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        payment_transaction.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(payment_transaction.status, 'rejected')
        self.assertEqual(self.order.payment_status, 'failed')
        self.product.refresh_from_db()
        self.reservation.refresh_from_db()
        self.assertEqual(self.product.quantity, 3)
        self.assertEqual(self.reservation.status, 'released')
        previous_request_id = payment.request_id

        confirmation = self.client.get(reverse('order_confirm', args=[self.order.pk]))
        self.assertContains(confirmation, 'Vous pouvez réessayer')
        self.assertContains(confirmation, reverse('paypal_cancel_order', args=[self.order.pk]))

        with patch(
            'marketplace.paypal_views.paypal_api_request',
            return_value={'id': 'PAYPAL-ORDER-RETRY', 'status': 'CREATED'},
        ) as api_request:
            retry_response = self.client.post(
                reverse('paypal_create_order', args=[self.order.pk]),
                data='{}',
                content_type='application/json',
            )

        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(retry_response.json(), {'id': 'PAYPAL-ORDER-RETRY'})
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(payment.status, 'created')
        self.assertEqual(payment.paypal_order_id, 'PAYPAL-ORDER-RETRY')
        self.assertNotEqual(payment.request_id, previous_request_id)
        self.assertEqual(payment.transaction.status, 'pending')
        self.assertEqual(self.order.payment_status, 'pending')
        self.product.refresh_from_db()
        self.reservation.refresh_from_db()
        self.assertEqual(self.product.quantity, 2)
        self.assertEqual(self.reservation.status, 'reserved')
        self.assertEqual(
            PayPalStockEvent.objects.filter(order=self.order, event_type='re_reserved').count(),
            1,
        )
        self.assertEqual(
            api_request.call_args.kwargs['payload']['purchase_units'][0]['amount']['value'],
            '25.50',
        )
        self.assertEqual(
            api_request.call_args.kwargs['payload']['purchase_units'][0]['invoice_id'],
            f'SDI-{self.order.pk}-{payment.request_id.hex}',
        )

    def test_cancelled_order_is_checked_and_can_be_retried(self):
        payment_transaction = Transaction.objects.create(
            sender=self.buyer,
            amount=self.order.total_amount,
            type='payment_int_paypal',
            status='pending',
        )
        payment = PayPalPayment.objects.create(
            order=self.order,
            transaction=payment_transaction,
            paypal_order_id='PAYPAL-ORDER-CANCEL',
            amount=self.order.total_amount,
            currency='USD',
        )
        with patch(
            'marketplace.paypal_views.paypal_api_request',
            return_value={
                'id': payment.paypal_order_id,
                'status': 'CREATED',
            },
        ) as api_request:
            response = self.client.post(
                reverse('paypal_cancel_order', args=[self.order.pk]),
                data=json.dumps({'paypal_order_id': payment.paypal_order_id}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'CANCELLED'})
        self.assertEqual(api_request.call_args.args, (
            'GET', f'/v2/checkout/orders/{payment.paypal_order_id}',
        ))
        payment.refresh_from_db()
        payment_transaction.refresh_from_db()
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.reservation.refresh_from_db()
        self.assertEqual(payment.status, 'cancelled')
        self.assertEqual(payment_transaction.status, 'cancelled')
        self.assertEqual(self.order.payment_status, 'pending')
        self.assertEqual(self.product.quantity, 3)
        self.assertEqual(self.reservation.status, 'released')

        duplicate_response = self.client.post(
            reverse('paypal_cancel_order', args=[self.order.pk]),
            data=json.dumps({'paypal_order_id': payment.paypal_order_id}),
            content_type='application/json',
        )
        self.assertEqual(duplicate_response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 3)
        self.assertEqual(
            PayPalStockEvent.objects.filter(order=self.order, event_type='released').count(),
            1,
        )

        with patch('marketplace.paypal_views.paypal_api_request') as api_request:
            capture_response = self.client.post(
                reverse('paypal_capture_order', args=[self.order.pk]),
                data=json.dumps({'paypal_order_id': payment.paypal_order_id}),
                content_type='application/json',
            )

        self.assertEqual(capture_response.status_code, 409)
        api_request.assert_not_called()

        with patch(
            'marketplace.paypal_views.paypal_api_request',
            return_value={'id': 'PAYPAL-ORDER-AFTER-CANCEL', 'status': 'CREATED'},
        ):
            retry_response = self.client.post(
                reverse('paypal_create_order', args=[self.order.pk]),
                data='{}',
                content_type='application/json',
            )

        self.assertEqual(retry_response.status_code, 200)
        payment.refresh_from_db()
        payment_transaction.refresh_from_db()
        self.assertEqual(payment.status, 'created')
        self.assertEqual(payment.paypal_order_id, 'PAYPAL-ORDER-AFTER-CANCEL')
        self.assertEqual(payment_transaction.status, 'cancelled')
        self.assertEqual(payment.transaction.status, 'pending')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 2)

    def test_completed_paypal_order_cannot_be_cancelled(self):
        payment = PayPalPayment.objects.create(
            order=self.order,
            paypal_order_id='PAYPAL-ORDER-COMPLETED',
            amount=self.order.total_amount,
            currency='USD',
        )
        with patch(
            'marketplace.paypal_views.paypal_api_request',
            return_value={
                'id': payment.paypal_order_id,
                'status': 'COMPLETED',
            },
        ):
            response = self.client.post(
                reverse('paypal_cancel_order', args=[self.order.pk]),
                data=json.dumps({'paypal_order_id': payment.paypal_order_id}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 409)
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(payment.status, 'created')
        self.assertEqual(self.order.payment_status, 'pending')

    def test_paid_order_stock_cannot_be_released(self):
        payment = PayPalPayment.objects.create(
            order=self.order,
            paypal_order_id='PAYPAL-ORDER-ALREADY-PAID',
            amount=self.order.total_amount,
            currency='USD',
            status='completed',
        )
        self.order.payment_status = 'approved'
        self.order.status = 'awaiting_delivery'
        self.order.save(update_fields=['payment_status', 'status'])
        self.reservation.status = 'consumed'
        self.reservation.save(update_fields=['status'])

        with patch('marketplace.paypal_views.paypal_api_request') as api_request:
            response = self.client.post(
                reverse('paypal_cancel_order', args=[self.order.pk]),
                data=json.dumps({'paypal_order_id': payment.paypal_order_id}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 409)
        api_request.assert_not_called()
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 2)
        self.assertEqual(
            PayPalStockEvent.objects.filter(order=self.order, event_type='released').count(),
            0,
        )

    def test_preparing_order_stock_cannot_be_released(self):
        payment = PayPalPayment.objects.create(
            order=self.order,
            paypal_order_id='PAYPAL-ORDER-PREPARING',
            amount=self.order.total_amount,
            currency='USD',
        )
        self.order.status = 'awaiting_delivery'
        self.order.save(update_fields=['status'])
        with patch(
            'marketplace.paypal_views.paypal_api_request',
            return_value={'id': payment.paypal_order_id, 'status': 'CREATED'},
        ):
            response = self.client.post(
                reverse('paypal_cancel_order', args=[self.order.pk]),
                data=json.dumps({'paypal_order_id': payment.paypal_order_id}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 409)
        self.product.refresh_from_db()
        self.reservation.refresh_from_db()
        self.assertEqual(self.product.quantity, 2)
        self.assertEqual(self.reservation.status, 'reserved')

    def test_expired_reservation_is_released_once_and_marked_failed(self):
        payment_transaction = Transaction.objects.create(
            sender=self.buyer,
            amount=self.order.total_amount,
            type='payment_int_paypal',
            status='pending',
        )
        payment = PayPalPayment.objects.create(
            order=self.order,
            transaction=payment_transaction,
            paypal_order_id='PAYPAL-ORDER-EXPIRED',
            amount=self.order.total_amount,
            currency='USD',
        )
        self.reservation.expires_at = timezone.now() - timedelta(seconds=1)
        self.reservation.save(update_fields=['expires_at'])

        call_command('expire_paypal_stock_reservations', stdout=Mock())
        call_command('expire_paypal_stock_reservations', stdout=Mock())

        payment.refresh_from_db()
        payment_transaction.refresh_from_db()
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.reservation.refresh_from_db()
        self.assertEqual(payment.status, 'expired')
        self.assertEqual(payment_transaction.status, 'cancelled')
        self.assertEqual(self.order.payment_status, 'failed')
        self.assertEqual(self.product.quantity, 3)
        self.assertEqual(self.reservation.status, 'released')
        self.assertEqual(
            PayPalStockEvent.objects.filter(order=self.order, event_type='expired').count(),
            1,
        )
        with patch(
            'marketplace.views.CommissionManager.calcul_commande_from_order',
            return_value={},
        ):
            confirmation = self.client.get(
                reverse('order_confirm', args=[self.order.pk]),
            )
        self.assertContains(confirmation, 'La réservation de stock a expiré')

    def test_expired_order_cannot_be_captured_late(self):
        payment = PayPalPayment.objects.create(
            order=self.order,
            paypal_order_id='PAYPAL-ORDER-TOO-LATE',
            amount=self.order.total_amount,
            currency='USD',
        )
        self.reservation.expires_at = timezone.now() - timedelta(seconds=1)
        self.reservation.save(update_fields=['expires_at'])
        call_command('expire_paypal_stock_reservations', stdout=Mock())

        with patch('marketplace.paypal_views.paypal_api_request') as api_request:
            response = self.client.post(
                reverse('paypal_capture_order', args=[self.order.pk]),
                data=json.dumps({'paypal_order_id': payment.paypal_order_id}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 409)
        api_request.assert_not_called()
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'failed')
        self.assertEqual(self.product.quantity, 3)

    def test_expiration_does_not_release_stock_while_capture_is_in_flight(self):
        payment = PayPalPayment.objects.create(
            order=self.order,
            paypal_order_id='PAYPAL-ORDER-CAPTURING',
            amount=self.order.total_amount,
            currency='USD',
        )
        self.reservation.expires_at = timezone.now() - timedelta(seconds=1)
        self.reservation.save(update_fields=['expires_at'])
        self.assertFalse(begin_paypal_capture(payment.pk))

        self.reservation.expires_at = timezone.now() + timedelta(minutes=5)
        self.reservation.save(update_fields=['expires_at'])
        self.assertTrue(begin_paypal_capture(payment.pk))
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'capturing')
        self.reservation.expires_at = timezone.now() - timedelta(seconds=1)
        self.reservation.save(update_fields=['expires_at'])

        call_command('expire_paypal_stock_reservations', stdout=Mock())

        self.product.refresh_from_db()
        self.reservation.refresh_from_db()
        self.assertEqual(self.product.quantity, 2)
        self.assertEqual(self.reservation.status, 'capturing')
        self.assertEqual(
            PayPalStockEvent.objects.filter(order=self.order, event_type='expired').count(),
            0,
        )

    def test_retry_is_rejected_if_released_stock_is_no_longer_available(self):
        payment = PayPalPayment.objects.create(
            order=self.order,
            paypal_order_id='PAYPAL-ORDER-NO-STOCK',
            amount=self.order.total_amount,
            currency='USD',
            status='cancelled',
        )
        self.reservation.status = 'released'
        self.reservation.released_at = timezone.now()
        self.reservation.save(update_fields=['status', 'released_at'])
        self.product.quantity = 0
        self.product.save(update_fields=['quantity'])

        with patch('marketplace.paypal_views.paypal_api_request') as api_request:
            response = self.client.post(
                reverse('paypal_create_order', args=[self.order.pk]),
                data='{}',
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 409)
        api_request.assert_not_called()
        payment.refresh_from_db()
        self.reservation.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(payment.status, 'cancelled')
        self.assertEqual(self.reservation.status, 'released')
        self.assertEqual(self.product.quantity, 0)

    def test_legacy_pay_api_cannot_mark_an_order_paid_without_paypal(self):
        response = self.client.post(f'/api/orders/{self.order.pk}/pay/')

        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'pending')
        self.assertEqual(self.order.status, 'pending')

    def test_order_api_does_not_expose_another_buyer_order(self):
        other_order = Order.objects.create(
            buyer=self.other_buyer,
            total_amount=Decimal('12.00'),
            delivery_address='2 Test Street',
            payment_method='int_paypal',
            payment_status='pending',
            status='pending',
        )
        response = self.client.get(f'/api/orders/{other_order.pk}/')

        self.assertEqual(response.status_code, 404)

    @override_settings(
        PAYPAL_MODE='live',
        PAYPAL_LIVE_ENABLED=False,
        PAYPAL_CHECKOUT_ENABLED=False,
    )
    def test_live_api_is_blocked_without_explicit_enablement(self):
        with patch('marketplace.paypal_gateway.requests.post') as token_request:
            with self.assertRaises(PayPalConfigurationError):
                paypal_api_request('POST', '/v2/checkout/orders', payload={})

        token_request.assert_not_called()


class PayPalStockConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        user_model = get_user_model()
        self.buyers = [
            user_model.objects.create_user(
                username=f'concurrent-buyer-{index}',
                password='test-password',
            )
            for index in range(2)
        ]
        seller = user_model.objects.create_user(
            username='concurrent-seller',
            password='test-password',
        )
        shop = Shop.objects.create(owner=seller, name='Concurrent Stock Shop')
        self.product = Product.objects.create(
            shop=shop,
            name='Last item',
            price_ht=Decimal('5.00'),
            quantity=1,
        )

    def test_two_simultaneous_paypal_orders_cannot_reserve_the_last_unit_twice(self):
        barrier = Barrier(2)

        def place_order(buyer_id):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    decrement_available_stock(self.product.pk, 1)
                    order = Order.objects.create(
                        buyer_id=buyer_id,
                        total_amount=Decimal('5.00'),
                        delivery_address='Concurrent test address',
                        payment_method='int_paypal',
                        payment_status='pending',
                        status='pending',
                        product_name='Last item',
                    )
                    product = Product.objects.get(pk=self.product.pk)
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=1,
                        price_ht=product.price_ht,
                    )
                    create_paypal_stock_reservation(order, [(product, 1)])
                return 'reserved'
            except InsufficientStock:
                return 'unavailable'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(place_order, [buyer.pk for buyer in self.buyers]))

        self.product.refresh_from_db()
        self.assertCountEqual(results, ['reserved', 'unavailable'])
        self.assertEqual(self.product.quantity, 0)
        self.assertEqual(Order.objects.filter(payment_method='int_paypal').count(), 1)
        self.assertEqual(PayPalStockReservation.objects.count(), 1)
