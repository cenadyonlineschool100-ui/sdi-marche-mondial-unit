import base64
import importlib
import json
import tempfile
from io import BytesIO
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import call, patch

from PIL import Image

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.db.models import Sum
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError

from .admin import MarketplaceSettingsAdmin
from .context_processors import _build_banner_rotation_schedule, site_banner_context, system_settings_context
from .forms import TiKaneAccessRequestForm, normalize_phone_number
from .models import (
    User, Profile, Wallet, Agent, DepositCommissionConfig, Deposit, DepositLimit, ExchangeRate, Receipt,
    AgentCommission, Transaction, TransactionLog, CommissionRule, FinancialOperation,
    DepositReceipt, Shop, Product, ProductAccessRequest, ResellerProduct, MarketplaceSettings, Order, OrderItem,
    Transfer, SDISolSettings, SDISolPlan, SDISolGroup, SDISolMember, SDISolPayment, RealEstateMembershipRequest, SystemSettings, PriorityGroup, SiteBanner, SiteBannerAccess, SiteBannerPayment, SiteBannerEvent, SiteBannerPermission,
    PersistentNotification, PushSubscription, ReturnRequest, WithdrawalRequest, WithdrawalTransaction,
    WithdrawalCommissionTier, TiKaneAccount, TiKaneAccessRequest, TiKanePlan,
)
from .business_logic import PaymentManager, create_persistent_notification, get_usd_display_conversion
from .views_commission import get_commission_eligible_users


class MonCashReceiptWorkflowTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='receipt-user', password='testpass123')
        self.wallet, _ = Wallet.objects.get_or_create(user=self.user)
        self.wallet.balance_htg = Decimal('125.00')
        self.wallet.save(update_fields=['balance_htg'])

    def make_image_upload(self, name='receipt.png', image_format='PNG', content_type='image/png'):
        image_bytes = BytesIO()
        Image.new('RGB', (2, 2), color='white').save(image_bytes, format=image_format)
        return SimpleUploadedFile(name, image_bytes.getvalue(), content_type=content_type)

    def test_upload_rejects_mislabelled_and_unsupported_files(self):
        self.client.force_login(self.user)

        for upload in (
            SimpleUploadedFile('fake.png', b'not an image', content_type='image/png'),
            self.make_image_upload('receipt.svg', content_type='image/svg+xml'),
        ):
            response = self.client.post(
                reverse('upload_receipt'),
                {'receipt_proof': upload},
            )
            self.assertEqual(response.status_code, 302)

        self.assertFalse(Receipt.objects.exists())

    def test_upload_rejects_files_over_five_megabytes(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            'large.png',
            b'x' * (5 * 1024 * 1024 + 1),
            content_type='image/png',
        )

        response = self.client.post(
            reverse('upload_receipt'),
            {'receipt_proof': upload},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Receipt.objects.exists())

    def test_receipt_upload_and_admin_decision_never_credit_wallet(self):
        admin = User.objects.create_user(
            username='receipt-admin',
            password='testpass123',
            role='super_admin',
        )
        self.client.force_login(self.user)

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            uploaded_receipts = []
            for _ in range(2):
                response = self.client.post(
                    reverse('upload_receipt'),
                    {'receipt_proof': self.make_image_upload()},
                )
                self.assertEqual(response.status_code, 302)
                receipt = Receipt.objects.latest('pk')
                self.assertEqual(receipt.status, 'pending')
                uploaded_receipts.append(receipt)

            self.wallet.refresh_from_db()
            self.assertEqual(self.wallet.balance_htg, Decimal('125.00'))

            self.client.force_login(admin)
            for receipt, action, expected_status in (
                (uploaded_receipts[0], 'approve', 'approved'),
                (uploaded_receipts[1], 'reject', 'rejected'),
            ):
                response = self.client.post(
                    reverse('process_receipt', args=[receipt.pk]),
                    {'action': action},
                )
                self.assertEqual(response.status_code, 302)
                receipt.refresh_from_db()
                self.assertEqual(receipt.status, expected_status)

            self.wallet.refresh_from_db()
            self.assertEqual(self.wallet.balance_htg, Decimal('125.00'))

    def test_non_admin_cannot_approve_a_receipt(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            receipt = Receipt.objects.create(
                user=self.user,
                receipt_image=self.make_image_upload(),
            )
            self.client.force_login(self.user)

            response = self.client.post(
                reverse('process_receipt', args=[receipt.pk]),
                {'action': 'approve'},
            )

        self.assertEqual(response.status_code, 302)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, 'pending')


class PersistentNotificationsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='notify-user', password='testpass123')
        self.other_user = User.objects.create_user(username='other-user', password='testpass123')
        self.client.force_login(self.user)

    def create_notification(self, recipient, key, notification_type='important'):
        return create_persistent_notification(
            recipient=recipient,
            title='Notification test',
            message='Persisted event',
            notification_type=notification_type,
            deduplication_key=key,
        )

    def test_event_key_prevents_duplicate_persistent_notifications(self):
        first = self.create_notification(self.user, 'test:event:1')
        second = self.create_notification(self.user, 'test:event:1')

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(PersistentNotification.objects.filter(recipient=self.user).count(), 1)

    def test_notifications_api_and_read_endpoint_are_recipient_scoped(self):
        own_notification = self.create_notification(self.user, 'test:own:1')
        other_notification = self.create_notification(self.other_user, 'test:other:1')

        response = self.client.get(reverse('get_persistent_notifications_api'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item['id'] for item in response.json()['notifications']],
            [own_notification.pk],
        )

        response = self.client.post(
            reverse('mark_persistent_notification_read_api', args=[other_notification.pk])
        )
        self.assertEqual(response.status_code, 404)
        other_notification.refresh_from_db()
        self.assertFalse(other_notification.is_read)

    def test_opening_notifications_page_does_not_mark_them_read(self):
        notification = self.create_notification(self.user, 'test:page:1')

        response = self.client.get(reverse('persistent_notifications_page'))

        self.assertEqual(response.status_code, 200)
        notification.refresh_from_db()
        self.assertFalse(notification.is_read)

    def test_admin_credit_sound_repeats_after_interval_until_read(self):
        notification = self.create_notification(
            self.user,
            'test:sound:1',
            notification_type='admin_money_received',
        )

        first_response = self.client.get(reverse('check_notifications_sound_api'))
        second_response = self.client.get(reverse('check_notifications_sound_api'))

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(
            [item['id'] for item in first_response.json()['notifications_to_sound']],
            [notification.pk],
        )
        self.assertEqual(second_response.json()['notifications_to_sound'], [])
        notification.refresh_from_db()
        self.assertIsNotNone(notification.last_sound_at)
        self.assertFalse(notification.is_read)

        notification.last_sound_at = timezone.now() - timedelta(minutes=2)
        notification.save(update_fields=['last_sound_at'])
        repeated_response = self.client.get(reverse('check_notifications_sound_api'))
        self.assertEqual(
            [item['id'] for item in repeated_response.json()['notifications_to_sound']],
            [notification.pk],
        )
        notification.refresh_from_db()
        self.assertFalse(notification.is_read)

    def test_other_notification_sound_remains_one_time(self):
        notification = self.create_notification(
            self.user,
            'test:sound:ordinary:1',
            notification_type='private_message',
        )
        self.client.get(reverse('check_notifications_sound_api'))
        notification.refresh_from_db()
        notification.last_sound_at = timezone.now() - timedelta(minutes=2)
        notification.save(update_fields=['last_sound_at'])

        response = self.client.get(reverse('check_notifications_sound_api'))

        self.assertEqual(response.json()['notifications_to_sound'], [])

    def test_admin_credit_count_is_returned_without_marking_notifications_read(self):
        credit = self.create_notification(
            self.user,
            'test:admin-credit:1',
            notification_type='admin_money_received',
        )
        self.create_notification(self.user, 'test:other:1')

        response = self.client.get(reverse('get_persistent_notifications_api'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 2)
        self.assertEqual(response.json()['admin_money_received_count'], 1)
        credit.refresh_from_db()
        self.assertFalse(credit.is_read)

        page_response = self.client.get(reverse('persistent_notifications_page'))
        self.assertRegex(
            page_response.content.decode(),
            r'id="notification-toggle" class="[^"]*has-admin-credit-alert',
        )

        self.client.post(
            reverse('mark_persistent_notification_read_api', args=[credit.pk])
        )
        page_after_read = self.client.get(reverse('persistent_notifications_page'))
        self.assertNotRegex(
            page_after_read.content.decode(),
            r'id="notification-toggle" class="[^"]*has-admin-credit-alert',
        )

    def test_admin_credit_sounds_again_until_the_specific_notification_is_read(self):
        credit = self.create_notification(
            self.user,
            'test:admin-credit-sound:1',
            notification_type='admin_money_received',
        )

        first_response = self.client.get(reverse('check_notifications_sound_api'))
        self.assertEqual(
            [item['id'] for item in first_response.json()['notifications_to_sound']],
            [credit.pk],
        )

        credit.refresh_from_db()
        credit.last_sound_at = timezone.now() - timedelta(minutes=2)
        credit.save(update_fields=['last_sound_at'])
        repeated_response = self.client.get(reverse('check_notifications_sound_api'))
        self.assertEqual(
            [item['id'] for item in repeated_response.json()['notifications_to_sound']],
            [credit.pk],
        )

        read_response = self.client.post(
            reverse('mark_persistent_notification_read_api', args=[credit.pk])
        )
        self.assertEqual(read_response.status_code, 200)
        stopped_response = self.client.get(reverse('check_notifications_sound_api'))
        self.assertEqual(stopped_response.json()['notifications_to_sound'], [])
        self.assertEqual(stopped_response.json()['count'], 0)

    def test_read_endpoint_schedules_browser_notification_dismissal(self):
        notification = self.create_notification(self.user, 'test:dismiss:1')
        with patch('marketplace.web_push.send_notification_dismissal') as send_dismissal:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    reverse('mark_persistent_notification_read_api', args=[notification.pk])
                )

        self.assertEqual(response.status_code, 200)
        send_dismissal.assert_called_once_with(self.user.pk, notification.pk)

    def test_persistent_notification_creation_dispatches_push_once_after_commit(self):
        with patch('marketplace.web_push.send_notification_push') as send_push:
            with self.captureOnCommitCallbacks(execute=True):
                notification = self.create_notification(self.user, 'test:push:1')
                self.create_notification(self.user, 'test:push:1')

        send_push.assert_called_once_with(notification.pk)


class WebPushSubscriptionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='push-user', password='testpass123')
        self.client.force_login(self.user)
        self.subscription_url = reverse('web_push_subscriptions')
        self.valid_keys = {
            'p256dh': base64.urlsafe_b64encode(b'P' * 65).decode().rstrip('='),
            'auth': base64.urlsafe_b64encode(b'A' * 16).decode().rstrip('='),
        }

    def post_subscription(self, endpoint):
        return self.client.post(
            self.subscription_url,
            data=json.dumps({'endpoint': endpoint, 'keys': self.valid_keys}),
            content_type='application/json',
        )

    def test_user_can_register_multiple_devices_and_remove_one(self):
        first_endpoint = 'https://fcm.googleapis.com/fcm/send/device-one'
        second_endpoint = 'https://updates.push.services.mozilla.com/wpush/v2/device-two'

        self.assertEqual(self.post_subscription(first_endpoint).status_code, 201)
        self.assertEqual(self.post_subscription(second_endpoint).status_code, 201)
        self.assertEqual(PushSubscription.objects.filter(user=self.user, is_active=True).count(), 2)

        repeated_response = self.post_subscription(first_endpoint)
        self.assertEqual(repeated_response.status_code, 200)
        self.assertEqual(PushSubscription.objects.filter(user=self.user).count(), 2)

        delete_response = self.client.delete(
            self.subscription_url,
            data=json.dumps({'endpoint': first_endpoint}),
            content_type='application/json',
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(PushSubscription.objects.filter(user=self.user, endpoint=first_endpoint).exists())

    def test_subscription_requires_login_and_rejects_untrusted_endpoints(self):
        self.client.logout()
        response = self.post_subscription('https://fcm.googleapis.com/fcm/send/device')
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.user)
        response = self.post_subscription('https://127.0.0.1/private')
        self.assertEqual(response.status_code, 400)

    def test_subscription_rejects_invalid_browser_keys(self):
        response = self.client.post(
            self.subscription_url,
            data=json.dumps({
                'endpoint': 'https://fcm.googleapis.com/fcm/send/device',
                'keys': {'p256dh': 'invalid', 'auth': 'invalid'},
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_subscription_cannot_be_reassigned_from_another_user(self):
        endpoint = 'https://fcm.googleapis.com/fcm/send/shared-device'
        self.assertEqual(self.post_subscription(endpoint).status_code, 201)
        other_user = User.objects.create_user(username='other-push-user', password='testpass123')
        self.client.force_login(other_user)

        response = self.post_subscription(endpoint)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(PushSubscription.objects.get(endpoint=endpoint).user_id, self.user.pk)

    @override_settings(
        WEB_PUSH_VAPID_PUBLIC_KEY='public-test-key',
        WEB_PUSH_VAPID_PRIVATE_KEY='private-test-key',
        WEB_PUSH_VAPID_CLAIMS_EMAIL='mailto:test@example.com',
    )
    def test_expired_push_subscription_is_deactivated_without_raising(self):
        from pywebpush import WebPushException
        from .web_push import send_notification_push

        notification = PersistentNotification.objects.create(
            recipient=self.user,
            title='Notification test',
            message='Persisted event',
            notification_type='important',
            deduplication_key='test:expired-push:1',
        )
        subscriptions = [
            PushSubscription.objects.create(
                user=self.user,
                endpoint=f'https://fcm.googleapis.com/fcm/send/expired-{status_code}',
                p256dh=self.valid_keys['p256dh'],
                auth=self.valid_keys['auth'],
            )
            for status_code in (404, 410)
        ]

        with patch(
            'pywebpush.webpush',
            side_effect=[
                WebPushException('expired', response=SimpleNamespace(status_code=status_code))
                for status_code in (404, 410)
            ],
        ) as mock_webpush:
            send_notification_push(notification.pk)

        for subscription in subscriptions:
            subscription.refresh_from_db()
            self.assertFalse(subscription.is_active)
        self.assertEqual(mock_webpush.call_count, 2)


class ContextProcessorRegressionTest(TestCase):
    def test_system_settings_context_exists_and_returns_safe_defaults(self):
        context = system_settings_context(None)
        self.assertIn('system_settings', context)
        self.assertIsNone(context['system_settings'])

    def test_normalize_phone_number_standardizes_phone_values(self):
        self.assertEqual(normalize_phone_number('509 1234 5678'), '+50912345678')
        self.assertEqual(normalize_phone_number('(509) 1234-5678'), '+50912345678')
        self.assertEqual(normalize_phone_number('12345678'), '+50912345678')


class MicrosDiCashAgentDepositTest(TestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(username='client1', password='testpass123', email='client1@example.com')
        self.client_profile, _ = Profile.objects.get_or_create(user=self.client_user)
        self.client_profile.phone = '50911111111'
        self.client_profile.save()
        self.client_wallet, _ = Wallet.objects.get_or_create(user=self.client_user)
        self.client_wallet.balance_htg = Decimal('500.00')
        self.client_wallet.save()

        self.agent_user = User.objects.create_user(username='agent1', password='agentpass123', email='agent1@example.com')
        self.agent_user.is_agent = True
        self.agent_user.save()
        self.agent_profile, _ = Profile.objects.get_or_create(user=self.agent_user)
        self.agent_profile.phone = '50922222222'
        self.agent_profile.save()
        self.agent, _ = Agent.objects.get_or_create(user=self.agent_user)
        self.agent.is_active = True
        self.agent.save()
        self.agent_wallet, _ = Wallet.objects.get_or_create(user=self.agent_user)
        self.agent_wallet.balance_htg = Decimal('50000.00')
        self.agent_wallet.save()

        self.agent_user.set_security_pin('1234')
        self.agent_user.set_otp_code('0000')

        self.admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='admin123')
        self.admin_wallet, _ = Wallet.objects.get_or_create(user=self.admin_user)
        self.admin_wallet.balance_htg = Decimal('100.00')
        self.admin_wallet.save()

        self.deposit_config = DepositCommissionConfig.objects.create(
            currency='HTG',
            commission_type='pourcentage',
            commission_value=Decimal('0.5'),
            min_deposit=Decimal('1.00'),
            max_deposit=Decimal('999999.00'),
            is_active=True
        )

        CommissionRule.objects.create(agent=None, min_amount=Decimal('100.00'), max_amount=Decimal('500.00'), commission_amount=Decimal('2.00'))
        CommissionRule.objects.create(agent=None, min_amount=Decimal('501.00'), max_amount=Decimal('2000.00'), commission_amount=Decimal('5.00'))
        CommissionRule.objects.create(agent=None, min_amount=Decimal('2001.00'), max_amount=Decimal('5000.00'), commission_amount=Decimal('10.00'))

        self.client = Client()
        self.client.login(username='agent1', password='agentpass123')

    def test_deposit_form_shows_only_active_currencies_and_effective_amount_limits(self):
        DepositCommissionConfig.objects.create(
            currency='USD',
            commission_type='fixe',
            commission_value=Decimal('1.00'),
            min_deposit=Decimal('5.00'),
            max_deposit=Decimal('500.00'),
            is_active=False,
        )
        DepositLimit.objects.create(
            min_amount=Decimal('10.00'),
            max_amount=Decimal('300.00'),
        )

        response = self.client.get(reverse('agent_deposit'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['currencies'],
            [{
                'code': 'HTG',
                'label': 'HTG',
                'min_amount': Decimal('10.00'),
                'max_amount': Decimal('300.00'),
            }],
        )
        self.assertContains(response, '<select id="currency"')
        self.assertContains(response, 'data-min-amount="10.00"')
        self.assertContains(response, 'data-max-amount="300.00"')
        currency_selector = response.content.decode('utf-8').split(
            '<select id="currency"',
            1,
        )[1].split('</select>', 1)[0]
        self.assertNotIn('<option value="USD"', currency_selector)
        self.assertNotContains(response, 'Aucune devise de dépôt')

    def test_agent_deposit_wizard_bypasses_native_validation_for_hidden_steps(self):
        response = self.client.get(reverse('agent_deposit'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="agent-deposit-form" novalidate')
        self.assertContains(
            response,
            'id="agent_pin" name="agent_pin" form="agent-deposit-form"',
        )

    def test_agent_deposit_rejects_invalid_amount_formats_and_limits(self):
        DepositLimit.objects.create(
            min_amount=Decimal('1.00'),
            max_amount=Decimal('1000.00'),
        )
        payload = {
            'account_number': self.client_user.account_code,
            'currency': 'HTG',
            'agent_pin': '1234',
            'final_code': '0000',
        }

        for amount in ('0', '-1', '1000.01', '1,25'):
            with self.subTest(amount=amount):
                response = self.client.post(
                    reverse('agent_deposit'),
                    {**payload, 'amount': amount, 'idempotency_key': f'invalid-amount-{amount}'},
                    follow=True,
                )
                self.assertEqual(response.status_code, 200)
                self.assertFalse(Deposit.objects.exists())

        self.agent_wallet.refresh_from_db()
        self.client_wallet.refresh_from_db()
        self.assertEqual(self.agent_wallet.balance_htg, Decimal('50000.00'))
        self.assertEqual(self.client_wallet.balance_htg, Decimal('500.00'))

    def test_agent_deposit_rejects_incomplete_and_non_agent_submissions(self):
        incomplete_response = self.client.post(
            reverse('agent_deposit'),
            {'amount': '100', 'currency': 'HTG'},
            follow=True,
        )
        self.assertContains(incomplete_response, 'Numéro de compte client requis')

        self.client.force_login(self.client_user)
        unauthorized_response = self.client.post(
            reverse('agent_deposit'),
            {
                'account_number': self.client_user.account_code,
                'amount': '100',
                'currency': 'HTG',
                'agent_pin': '1234',
                'final_code': '0000',
                'idempotency_key': 'non-agent-deposit-001',
            },
        )
        self.assertEqual(unauthorized_response.status_code, 302)
        self.assertEqual(unauthorized_response.url, reverse('dashboard'))
        self.assertFalse(Deposit.objects.exists())

    def test_deposit_form_explains_when_no_currency_is_active(self):
        self.deposit_config.is_active = False
        self.deposit_config.save(update_fields=['is_active'])

        response = self.client.get(reverse('agent_deposit'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['currencies'], [])
        self.assertContains(response, "Aucune devise de dépôt n&#x27;est activée.")
        self.assertContains(response, 'Aucune devise disponible')
        self.assertContains(response, 'data-deposit-submit disabled')

    def test_usd_deposit_receipt_uses_the_balance_usd_wallet_field(self):
        self.client_wallet.balance = Decimal('40.00')
        self.client_wallet.balance_usd = Decimal('60.00')
        self.client_wallet.save(update_fields=['balance', 'balance_usd'])
        deposit = Deposit.objects.create(
            agent=self.agent_user,
            client=self.client_user,
            amount=Decimal('10.00'),
            currency='USD',
            status='confirmed',
        )
        receipt = DepositReceipt.objects.create(
            receipt_number='DP-USD-RECEIPT-TEST',
            client=self.client_user,
            agent=self.agent_user,
            deposit=deposit,
        )

        receipt.generate_content()

        self.assertIn('Ancien Solde : 50.00 USD', receipt.content)
        self.assertIn('Nouveau Solde : 60.00 USD', receipt.content)

    def test_dop_deposit_receipt_uses_the_balance_peso_wallet_field(self):
        self.client_wallet.balance_peso = Decimal('60.00')
        self.client_wallet.save(update_fields=['balance_peso'])
        deposit = Deposit.objects.create(
            agent=self.agent_user,
            client=self.client_user,
            amount=Decimal('10.00'),
            currency='DOP',
            status='confirmed',
        )
        receipt = DepositReceipt.objects.create(
            receipt_number='DP-DOP-RECEIPT-TEST',
            client=self.client_user,
            agent=self.agent_user,
            deposit=deposit,
        )

        receipt.generate_content()

        self.assertIn('Ancien Solde : 50.00 DOP', receipt.content)
        self.assertIn('Nouveau Solde : 60.00 DOP', receipt.content)

    def test_deposit_receipt_uses_fresh_wallet_balance_not_cached_pre_deposit_balance(self):
        self.client_wallet.balance_htg = Decimal('10.00')
        self.client_wallet.save(update_fields=['balance_htg'])
        self.client_user._state.fields_cache['wallet'] = Wallet(
            user=self.client_user,
            balance_htg=Decimal('0.00'),
        )
        deposit = Deposit.objects.create(
            agent=self.agent_user,
            client=self.client_user,
            amount=Decimal('10.00'),
            currency='HTG',
            status='confirmed',
        )
        receipt = DepositReceipt.objects.create(
            receipt_number='DP-HTG-RECEIPT-STALE-WALLET-TEST',
            client=self.client_user,
            agent=self.agent_user,
            deposit=deposit,
        )

        receipt.generate_content()

        self.assertIn('Ancien Solde : 0.00 HTG', receipt.content)
        self.assertIn('Nouveau Solde : 10.00 HTG', receipt.content)

    def test_agent_can_make_htg_deposit(self):
        url = reverse('agent_deposit')
        with patch('marketplace.web_push.send_notification_push') as send_push:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(url, {
                    'account_number': self.client_user.account_code,
                    'amount': '2000',
                    'currency': 'HTG',
                    'agent_pin': '1234',
                    'final_code': '0000',
                    'idempotency_key': 'deposit-basic-001',
                }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(
            message.tags == 'success' and 'Dépôt de 2000 HTG confirmé' in str(message)
            for message in response.context['messages']
        ))
        deposit = Deposit.objects.latest('created_at')
        self.assertEqual(deposit.agent, self.agent_user)
        self.assertEqual(deposit.client, self.client_user)
        self.assertEqual(deposit.amount, Decimal('2000'))
        self.assertEqual(deposit.currency, 'HTG')
        self.assertEqual(deposit.status, 'confirmed')
        self.assertEqual(deposit.commission, Decimal('5.00'))

        self.client_wallet.refresh_from_db()
        self.agent_wallet.refresh_from_db()
        self.admin_wallet.refresh_from_db()
        self.assertEqual(self.client_wallet.balance_htg, Decimal('2500.00'))
        self.assertEqual(self.agent_wallet.balance_htg, Decimal('48000.00'))
        self.assertEqual(self.agent_wallet.commission_balance_htg, Decimal('5.00'))
        self.assertEqual(self.admin_wallet.balance_htg, Decimal('95.00'))
        self.assertEqual(self.admin_wallet.commission_balance_htg, Decimal('0.00'))

        self.assertTrue(Transaction.objects.filter(type='deposit', receiver=self.client_user, amount=Decimal('2000.00'), currency='HTG').exists())
        self.assertTrue(Transaction.objects.filter(type='commission', sender=self.admin_user, receiver=self.agent_user, amount=Decimal('5.00'), currency='HTG').exists())
        commission_notification = PersistentNotification.objects.get(
            recipient=self.agent_user,
            notification_type='commission_received',
        )
        client_notification = PersistentNotification.objects.get(
            recipient=self.client_user,
            notification_type='money_received',
        )
        self.assertEqual(
            commission_notification.deduplication_key,
            f'deposit-commission:{AgentCommission.objects.get(deposit=deposit).pk}:user:{self.agent_user.pk}',
        )
        self.assertEqual(commission_notification.target_url, '/profile/')
        self.assertEqual(client_notification.target_url, '/profile/')
        self.assertCountEqual(
            send_push.call_args_list,
            [call(client_notification.pk), call(commission_notification.pk)],
        )

    def test_agent_deposit_rejects_missing_or_invalid_pin_without_moving_balances(self):
        payload = {
            'account_number': self.client_user.account_code,
            'amount': '2000',
            'currency': 'HTG',
            'final_code': '0000',
        }

        cases = (
            ({}, 'PIN agent requis'),
            ({'agent_pin': '9999'}, 'PIN incorrect.'),
        )
        for index, (pin_values, expected_error) in enumerate(cases):
            with self.subTest(expected_error=expected_error):
                response = self.client.post(
                    reverse('agent_deposit'),
                    {
                        **payload,
                        **pin_values,
                        'idempotency_key': f'deposit-pin-rejected-{index}',
                    },
                    follow=True,
                )
                self.assertTrue(any(
                    message.tags == 'error' and expected_error in str(message)
                    for message in response.context['messages']
                ))
                self.assertFalse(any(
                    message.tags == 'success' and 'Dépôt de ' in str(message)
                    for message in response.context['messages']
                ))

        self.assertFalse(Deposit.objects.exists())
        self.assertFalse(Transaction.objects.filter(type='deposit').exists())
        self.agent_wallet.refresh_from_db()
        self.client_wallet.refresh_from_db()
        self.assertEqual(self.agent_wallet.balance_htg, Decimal('50000.00'))
        self.assertEqual(self.client_wallet.balance_htg, Decimal('500.00'))

    def test_invalid_final_confirmation_code_does_not_create_or_credit_a_deposit(self):
        response = self.client.post(
            reverse('agent_deposit'),
            {
                'account_number': self.client_user.account_code,
                'amount': '2000',
                'currency': 'HTG',
                'agent_pin': '1234',
                'final_code': '0001',
                'idempotency_key': 'deposit-invalid-final-code-001',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(
            message.tags == 'error' and 'Code final de confirmation invalide.' in str(message)
            for message in response.context['messages']
        ))
        self.assertFalse(any(
            message.tags == 'success' and 'Dépôt de ' in str(message)
            for message in response.context['messages']
        ))
        self.assertFalse(Deposit.objects.exists())
        self.assertFalse(Transaction.objects.filter(type='deposit').exists())

        self.agent_wallet.refresh_from_db()
        self.client_wallet.refresh_from_db()
        self.assertEqual(self.agent_wallet.balance_htg, Decimal('50000.00'))
        self.assertEqual(self.client_wallet.balance_htg, Decimal('500.00'))

    def test_repeated_deposit_post_creates_only_one_deposit(self):
        payload = {
            'account_number': self.client_user.account_code,
            'amount': '2000',
            'currency': 'HTG',
            'agent_pin': '1234',
            'final_code': '0000',
            'idempotency_key': 'deposit-retry-001',
        }

        first = self.client.post(reverse('agent_deposit'), payload)
        repeated = self.client.post(reverse('agent_deposit'), payload)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(repeated.status_code, 302)
        self.assertEqual(Deposit.objects.filter(agent=self.agent_user, client=self.client_user).count(), 1)
        deposit = Deposit.objects.get(agent=self.agent_user, client=self.client_user)
        self.assertEqual(
            Transaction.objects.filter(
                type='deposit',
                sender=self.agent_user,
                receiver=self.client_user,
                amount=Decimal('2000.00'),
                currency='HTG',
            ).count(),
            1,
        )
        self.assertEqual(
            Transaction.objects.filter(
                type='commission',
                sender=self.admin_user,
                receiver=self.agent_user,
                amount=Decimal('5.00'),
                currency='HTG',
            ).count(),
            1,
        )
        self.assertEqual(DepositReceipt.objects.filter(deposit=deposit).count(), 1)
        self.assertEqual(
            TransactionLog.objects.filter(
                transaction_type='deposit',
                transaction_ref=deposit.reference,
            ).count(),
            1,
        )
        self.assertEqual(
            FinancialOperation.objects.filter(
                actor=self.agent_user,
                operation='agent_deposit',
                idempotency_key='deposit-retry-001',
            ).count(),
            1,
        )
        self.agent_wallet.refresh_from_db()
        self.client_wallet.refresh_from_db()
        self.assertEqual(self.agent_wallet.balance_htg, Decimal('48000.00'))
        self.assertEqual(self.client_wallet.balance_htg, Decimal('2500.00'))

    def test_deposit_repay_real_estate_loan_before_credit(self):
        self.client_wallet.balance_htg = Decimal('0.00')
        self.client_wallet.real_estate_loan_balance_htg = Decimal('100.00')
        self.client_wallet.save()

        url = reverse('agent_deposit')
        response = self.client.post(url, {
            'account_number': self.client_user.account_code,
            'amount': '80',
            'currency': 'HTG',
            'agent_pin': '1234',
            'final_code': '0000',
            'idempotency_key': 'deposit-loan-001',
        })
        self.assertEqual(response.status_code, 302)

        self.client_wallet.refresh_from_db()
        self.assertEqual(self.client_wallet.real_estate_loan_balance_htg, Decimal('20.00'))
        self.assertEqual(self.client_wallet.balance_htg, Decimal('0.00'))

    def test_deposit_fails_when_agent_balance_insufficient(self):
        self.agent_wallet.balance_htg = Decimal('1000.00')
        self.agent_wallet.save()
        url = reverse('agent_deposit')
        response = self.client.post(url, {
            'account_number': self.client_user.account_code,
            'amount': '2000',
            'currency': 'HTG',
            'agent_pin': '1234',
            'final_code': '0000',
            'idempotency_key': 'deposit-low-balance-001',
        }, follow=True)
        self.assertContains(response, 'Solde insuffisant')
        self.assertEqual(Deposit.objects.count(), 0)

    def test_deposit_is_rejected_when_currency_has_no_active_configuration(self):
        self.deposit_config.is_active = False
        self.deposit_config.save(update_fields=['is_active'])

        response = self.client.post(
            reverse('agent_deposit'),
            {
                'account_number': self.client_user.account_code,
                'amount': '100.00',
                'currency': 'HTG',
                'agent_pin': '1234',
                'final_code': '0000',
                'idempotency_key': 'deposit-disabled-currency-001',
            },
            follow=True,
        )

        self.assertContains(response, 'Dépôts non disponibles pour HTG')
        self.assertFalse(Deposit.objects.exists())
        self.assertFalse(Transaction.objects.filter(type='deposit').exists())
        self.agent_wallet.refresh_from_db()
        self.client_wallet.refresh_from_db()
        self.assertEqual(self.agent_wallet.balance_htg, Decimal('50000.00'))
        self.assertEqual(self.client_wallet.balance_htg, Decimal('500.00'))

    def test_deposit_failure_rolls_back_wallet_and_records(self):
        with patch(
            'marketplace.views_deposit.create_persistent_notification',
            side_effect=RuntimeError('simulated notification failure'),
        ), self.assertLogs('marketplace.views_deposit', level='ERROR') as deposit_logs:
            response = self.client.post(reverse('agent_deposit'), {
                'account_number': self.client_user.account_code,
                'amount': '2000',
                'currency': 'HTG',
                'agent_pin': '1234',
                'final_code': '0000',
                'idempotency_key': 'deposit-rollback-001',
            }, follow=True)

        self.assertContains(
            response,
            "Le dépôt n&#x27;a pas pu être effectué. Aucun solde n&#x27;a été modifié.",
        )
        self.assertIn('simulated notification failure', '\n'.join(deposit_logs.output))
        self.assertEqual(Deposit.objects.count(), 0)
        self.assertFalse(Transaction.objects.filter(type='deposit').exists())
        self.agent_wallet.refresh_from_db()
        self.client_wallet.refresh_from_db()
        self.assertEqual(self.agent_wallet.balance_htg, Decimal('50000.00'))
        self.assertEqual(self.client_wallet.balance_htg, Decimal('500.00'))

    def test_deposit_fails_when_client_phone_invalid(self):
        url = reverse('agent_deposit')
        response = self.client.post(url, {
            'account_number': 'ACC000000',
            'amount': '2000',
            'currency': 'HTG',
            'agent_pin': '1234',
            'final_code': '0000',
            'idempotency_key': 'deposit-invalid-client-001',
        }, follow=True)
        self.assertContains(response, 'Aucun client trouvé')
        self.assertEqual(Deposit.objects.count(), 0)

    def test_agent_deposit_history_shows_receipt_and_download(self):
        # Create a deposit so a receipt is generated
        deposit_url = reverse('agent_deposit')
        response = self.client.post(deposit_url, {
            'account_number': self.client_user.account_code,
            'amount': '2000',
            'currency': 'HTG',
            'agent_pin': '1234',
            'final_code': '0000',
            'idempotency_key': 'deposit-history-001',
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        receipt = DepositReceipt.objects.latest('created_at')
        self.assertIsNotNone(receipt)
        self.assertIn('MicroSDICash - Reçu Bancaire Sécurisé', receipt.content)

        history_url = reverse('agent_deposit_history')
        response = self.client.get(history_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['stats']['HTG'],
            {'total_amount': Decimal('2000.00'), 'total_commission': Decimal('5.00')},
        )
        self.assertContains(response, 'Télécharger reçu')
        download_url = reverse('download_deposit_receipt', args=[receipt.id])
        self.assertContains(response, download_url)
        response = self.client.get(download_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain; charset=utf-8')
        self.assertIn(f'Numéro de Reçu : {receipt.receipt_number}', response.content.decode('utf-8'))

    def test_client_can_view_deposit_receipts_list(self):
        deposit_url = reverse('agent_deposit')
        response = self.client.post(deposit_url, {
            'account_number': self.client_user.account_code,
            'amount': '2000',
            'currency': 'HTG',
            'agent_pin': '1234',
            'final_code': '0000',
            'idempotency_key': 'deposit-receipts-001',
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        receipt = DepositReceipt.objects.latest('created_at')
        self.assertIsNotNone(receipt)

        self.client.logout()
        self.client.login(username='client1', password='testpass123')

        receipts_url = reverse('client_deposit_receipts')
        response = self.client.get(receipts_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mes reçus de dépôt')
        self.assertContains(response, receipt.receipt_number)
        self.assertContains(response, reverse('view_deposit_receipt', args=[receipt.id]))
        self.assertContains(response, reverse('download_deposit_receipt', args=[receipt.id]))

        view_url = reverse('view_deposit_receipt', args=[receipt.id])
        response = self.client.get(view_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reçu de dépôt')


class AgentWithdrawalNotificationTest(TestCase):
    def setUp(self):
        self.agent = User.objects.create_user(
            username='withdrawal-agent',
            password='agentpass123',
            is_agent=True,
        )
        Agent.objects.filter(user=self.agent).update(is_active=True)
        self.customer = User.objects.create_user(
            username='withdrawal-customer',
            password='customerpass123',
        )
        self.customer_profile, _ = Profile.objects.get_or_create(user=self.customer)
        self.customer_profile.withdrawal_pin = '12345678'
        self.customer_profile.withdrawal_code = '1234'
        self.customer_profile.save(update_fields=['withdrawal_pin', 'withdrawal_code'])
        self.wallet = Wallet.objects.get(user=self.customer)
        self.wallet.balance = Decimal('100.00')
        self.wallet.save(update_fields=['balance'])
        self.client = Client()
        self.client.login(username='withdrawal-agent', password='agentpass123')
        self.customer_client = Client()
        self.customer_client.login(username='withdrawal-customer', password='customerpass123')

    def test_agent_completes_pending_request_without_second_debit_and_notifies_once(self):
        no_fee = {
            'total_fee': Decimal('0.00'),
            'system_fee': Decimal('0.00'),
            'agent_fee': Decimal('0.00'),
        }

        with patch('marketplace.views.CommissionManager.get_withdrawal_commission_breakdown', return_value=no_fee):
            request_response = self.customer_client.post(
                reverse('withdraw_funds'),
                {
                    'account': 'principal',
                    'amount': '10.00',
                    'currency': 'USD',
                    'pin': self.customer_profile.withdrawal_pin,
                    'secure_code': self.customer_profile.withdrawal_code,
                    'idempotency_key': 'customer-withdrawal-request-001',
                },
            )

        self.assertEqual(request_response.status_code, 200)
        self.assertTrue(request_response.json()['success'])
        withdrawal = WithdrawalRequest.objects.get(pk=request_response.json()['withdrawal_id'])
        self.assertEqual(withdrawal.status, 'pending')
        self.assertTrue(withdrawal.amount_debited)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('90.00'))

        page = self.client.get(reverse('agent_process_withdrawal'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, self.customer.username)

        with patch('marketplace.web_push.send_notification_push') as send_push:
            with self.captureOnCommitCallbacks(execute=True):
                first = self.client.post(
                    reverse('agent_process_withdrawal'),
                    {'withdrawal_id': withdrawal.pk},
                )
                repeated = self.client.post(
                    reverse('agent_process_withdrawal'),
                    {'withdrawal_id': withdrawal.pk},
                )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(repeated.status_code, 302)
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, 'completed')
        self.assertEqual(withdrawal.processed_by, self.agent)
        self.assertEqual(WithdrawalRequest.objects.filter(user=self.customer).count(), 1)
        self.assertEqual(
            WithdrawalTransaction.objects.filter(
                withdrawal_request=withdrawal,
                agent=self.agent,
                status='completed',
            ).count(),
            1,
        )
        self.assertEqual(
            Transaction.objects.filter(
                sender=self.customer,
                receiver=self.agent,
                type='withdrawal_agent',
                amount=Decimal('10.00'),
                currency='USD',
                status='completed',
            ).count(),
            1,
        )
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('90.00'))

        notification = PersistentNotification.objects.get(
            recipient=self.customer,
            notification_type='withdrawal_completed',
        )
        self.assertEqual(
            notification.deduplication_key,
            f'agent-withdrawal-completed:{withdrawal.pk}:user:{self.customer.pk}',
        )
        self.assertEqual(notification.target_url, '/profile/')
        self.assertEqual(
            PersistentNotification.objects.filter(recipient=self.customer).count(),
            1,
        )
        send_push.assert_called_once_with(notification.pk)

    def test_inactive_agent_cannot_process_withdrawal(self):
        Agent.objects.filter(user=self.agent).update(is_active=False)

        response = self.client.post(
            reverse('agent_process_withdrawal'),
            {},
        )

        self.assertEqual(response.status_code, 403)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('100.00'))
        self.assertFalse(WithdrawalRequest.objects.filter(user=self.customer).exists())
        self.assertFalse(PersistentNotification.objects.filter(recipient=self.customer).exists())


class PersonalWithdrawalControlTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='personal-withdrawal-admin',
            email='personal-withdrawal-admin@example.com',
            password='adminpass123',
        )
        self.customer = User.objects.create_user(
            username='personal-withdrawal-customer',
            password='customerpass123',
        )
        self.profile = Profile.objects.get(user=self.customer)
        self.profile.withdrawal_pin = '12345678'
        self.profile.withdrawal_code = '1234'
        self.profile.save(update_fields=['withdrawal_pin', 'withdrawal_code'])
        self.wallet = Wallet.objects.get(user=self.customer)
        self.wallet.balance = Decimal('100.00')
        self.wallet.save(update_fields=['balance'])
        self.admin_client = Client()
        self.admin_client.force_login(self.admin)
        self.customer_client = Client()
        self.customer_client.force_login(self.customer)

    def submit_personal_withdrawal(self, amount='10.00'):
        return self.customer_client.post(reverse('withdraw_funds'), {
            'account': 'principal',
            'amount': amount,
            'currency': 'USD',
            'pin': self.profile.withdrawal_pin,
            'secure_code': self.profile.withdrawal_code,
            'idempotency_key': 'personal-withdrawal-request-001',
        })

    def test_admin_can_disable_personal_withdrawals_and_block_new_requests(self):
        settings = SystemSettings.objects.create(pk=1)
        self.assertTrue(settings.personal_withdrawals_enabled)

        admin_page = self.admin_client.get(reverse('manage_withdrawal_commissions'))
        self.assertEqual(admin_page.status_code, 200)
        self.assertContains(admin_page, 'Contrôle des retraits personnels')
        self.assertContains(admin_page, 'Devise')

        response = self.admin_client.post(reverse('manage_withdrawal_commissions'), {
            'action': 'set_personal_withdrawals',
            'enabled': 'off',
        })
        self.assertEqual(response.status_code, 302)
        settings.refresh_from_db()
        self.assertFalse(settings.personal_withdrawals_enabled)

        profile_response = self.customer_client.get(reverse('profile'))
        self.assertNotContains(profile_response, '💸 Retrait personnel</button>')
        withdrawal_response = self.submit_personal_withdrawal()
        self.assertEqual(withdrawal_response.status_code, 403)
        self.assertFalse(withdrawal_response.json()['success'])
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('100.00'))
        self.assertFalse(WithdrawalRequest.objects.filter(user=self.customer).exists())

    def test_personal_withdrawal_applies_admin_configured_currency_fee(self):
        profile_response = self.customer_client.get(reverse('profile'))
        self.assertContains(profile_response, '💸 Retrait personnel</button>')
        default_tiers = json.loads(profile_response.context['withdrawal_commission_tiers_json'])
        self.assertEqual(
            {tier['currency'] for tier in default_tiers},
            {'USD', 'HTG', 'DOP', 'EUR'},
        )
        self.assertContains(profile_response, 'Frais configurés')
        configured_tier = WithdrawalCommissionTier.objects.get(
            currency='USD',
            min_amount__lte=Decimal('10.00'),
            max_amount__gte=Decimal('10.00'),
        )
        self.assertTrue(
            WithdrawalCommissionTier.objects.filter(
                currency='USD',
                min_amount__lte=Decimal('10.00'),
                max_amount__gte=Decimal('10.00'),
                active=True,
            ).exists()
        )

        admin_response = self.admin_client.post(reverse('manage_withdrawal_commissions'), {
            'action': 'update',
            'tier_id': configured_tier.pk,
            'currency': 'USD',
            'min_amount': configured_tier.min_amount,
            'max_amount': configured_tier.max_amount,
            'total_fee': '2.00',
            'system_fee': '1.50',
            'agent_fee': '0.50',
            'description': 'Retrait personnel USD',
            'active': 'on',
        })
        self.assertEqual(admin_response.status_code, 302)
        self.assertTrue(WithdrawalCommissionTier.objects.filter(currency='USD').exists())

        response = self.submit_personal_withdrawal()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        withdrawal = WithdrawalRequest.objects.get(pk=response.json()['withdrawal_id'])
        self.assertEqual(withdrawal.fee_total, Decimal('2.00'))
        self.assertEqual(withdrawal.fee_system, Decimal('1.50'))
        self.assertEqual(withdrawal.fee_agent, Decimal('0.50'))
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('88.00'))

    def test_principal_withdrawal_is_rejected_without_a_matching_fee_tier(self):
        response = self.submit_personal_withdrawal(amount='1000.00')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIn('Aucun barème de frais', response.json()['message'])
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('100.00'))
        self.assertFalse(WithdrawalRequest.objects.filter(user=self.customer).exists())


class TiKaneCurrencyWithdrawalTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='tikane-system-admin',
            email='tikane-admin@example.com',
            password='testpass123',
        )
        self.customer = User.objects.create_user(
            username='tikane-customer',
            password='customerpass123',
        )
        self.profile = Profile.objects.get(user=self.customer)
        self.profile.withdrawal_pin = '12345678'
        self.profile.withdrawal_code = '1234'
        self.profile.save(update_fields=['withdrawal_pin', 'withdrawal_code'])
        self.plan = TiKanePlan.objects.create(
            name='Test withdrawal plan',
            duration_days=30,
            commission_fixed=Decimal('2.50'),
            commission_variable=Decimal('0.00'),
        )
        self.account = TiKaneAccount.objects.create(
            user=self.customer,
            account_number='TK-TEST-HTG',
            unique_identifier='TKID-TEST-HTG',
            plan=self.plan,
            currency='HTG',
            status='active',
            maturity_date=timezone.now() - timedelta(days=1),
            balance=Decimal('100.00'),
        )
        self.wallet = Wallet.objects.get(user=self.customer)
        self.wallet.balance = Decimal('80.00')
        self.wallet.balance_htg = Decimal('10.00')
        self.wallet.balance_peso = Decimal('20.00')
        self.wallet.balance_eur = Decimal('30.00')
        self.wallet.save(update_fields=['balance', 'balance_htg', 'balance_peso', 'balance_eur'])
        self.customer_client = Client()
        self.customer_client.force_login(self.customer)

    def test_tikane_balance_displays_the_account_currency(self):
        dashboard_response = self.customer_client.get(reverse('dashboard'))
        tikane_response = self.customer_client.get(reverse('tikane_access'))

        self.assertRegex(dashboard_response.content.decode(), r'100[,.]00 HTG')
        self.assertRegex(tikane_response.content.decode(), r'Solde actuel : 100[,.]00 HTG')

    def test_principal_usd_countervalues_use_configured_rates_without_creating_balances(self):
        ExchangeRate.objects.create(
            usd_to_htg=Decimal('132'),
            usd_to_peso=Decimal('58'),
            eur_to_usd=Decimal('1.086957'),
            is_active=True,
        )
        self.wallet.balance = Decimal('300.00')
        self.wallet.save(update_fields=['balance'])

        conversion = get_usd_display_conversion(Decimal('300.00'))
        dashboard_response = self.customer_client.get(reverse('dashboard'))
        profile_response = self.customer_client.get(reverse('profile'))

        self.assertEqual(conversion['amounts'], {
            'USD': Decimal('300.00'),
            'HTG': Decimal('39600.00'),
            'DOP': Decimal('17400.00'),
            'EUR': Decimal('276.00'),
        })
        self.assertRegex(dashboard_response.content.decode(), r'39600[,.]00')
        self.assertRegex(profile_response.content.decode(), r'39600[,.]00')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('300.00'))
        self.assertEqual(self.wallet.balance_usd, Decimal('0.00'))
        self.assertEqual(self.wallet.balance_htg, Decimal('10.00'))
        self.assertEqual(self.wallet.balance_peso, Decimal('20.00'))
        self.assertEqual(self.wallet.balance_eur, Decimal('30.00'))

    def test_principal_countervalues_are_unavailable_without_valid_configured_rates(self):
        ExchangeRate.objects.create(
            usd_to_htg=0,
            usd_to_peso=Decimal('58'),
            eur_to_usd=0,
            is_active=True,
        )

        conversion = get_usd_display_conversion(Decimal('300.00'))

        self.assertEqual(conversion['amounts']['USD'], Decimal('300.00'))
        self.assertIsNone(conversion['amounts']['HTG'])
        self.assertEqual(conversion['amounts']['DOP'], Decimal('17400.00'))
        self.assertIsNone(conversion['amounts']['EUR'])

    def test_tikane_withdrawal_api_rejects_new_requests_when_control_is_off(self):
        SystemSettings.objects.create(pk=1, tikane_withdrawals_enabled=False)

        response = self.submit_tikane_withdrawal(key='tikane-disabled')

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['success'])
        self.account.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('100.00'))
        self.assertEqual(self.wallet.balance_htg, Decimal('10.00'))
        self.assertFalse(WithdrawalRequest.objects.filter(user=self.customer).exists())

    def test_agent_withdrawal_api_stays_off_after_new_credits(self):
        self.customer.is_agent = True
        self.customer.save(update_fields=['is_agent'])
        self.wallet.commission_balance_htg = Decimal('70.00')
        self.wallet.save(update_fields=['commission_balance_htg'])
        SystemSettings.objects.create(pk=1, agent_wallet_withdrawals_enabled=False)
        Wallet.objects.filter(pk=self.wallet.pk).update(
            commission_balance_htg=Decimal('90.00'),
        )

        response = self.customer_client.post(reverse('withdraw_funds'), {
            'account': 'multidevice',
            'amount': '20.00',
            'currency': 'HTG',
            'pin': self.profile.withdrawal_pin,
            'secure_code': self.profile.withdrawal_code,
            'idempotency_key': 'agent-disabled-withdrawal',
        })

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['success'])
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.commission_balance_htg, Decimal('90.00'))
        self.assertFalse(WithdrawalRequest.objects.filter(user=self.customer).exists())

    def test_agent_wallet_withdrawal_remains_available_when_control_is_on(self):
        self.customer.is_agent = True
        self.customer.save(update_fields=['is_agent'])
        self.wallet.commission_balance_htg = Decimal('100.00')
        self.wallet.save(update_fields=['commission_balance_htg'])
        SystemSettings.objects.create(pk=1, agent_wallet_withdrawals_enabled=True)

        response = self.customer_client.post(reverse('withdraw_funds'), {
            'account': 'multidevice',
            'amount': '20.00',
            'currency': 'HTG',
            'pin': self.profile.withdrawal_pin,
            'secure_code': self.profile.withdrawal_code,
            'idempotency_key': 'agent-enabled-withdrawal',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertTrue(
            WithdrawalRequest.objects.filter(
                user=self.customer,
                account_type='multidevice',
                status='pending',
            ).exists()
        )

    def test_financial_admin_can_toggle_tikane_and_agent_withdrawals(self):
        admin_client = Client()
        admin_client.force_login(self.admin)
        SystemSettings.objects.create(pk=1)

        agent_off = admin_client.post(reverse('manage_agent_commissions'), {
            'action': 'set_agent_wallet_withdrawals',
            'enabled': 'off',
        })
        tikane_off = admin_client.post(reverse('manage_withdrawal_commissions'), {
            'action': 'set_tikane_withdrawals',
            'enabled': 'off',
        })

        self.assertEqual(agent_off.status_code, 302)
        self.assertEqual(tikane_off.status_code, 302)
        settings = SystemSettings.objects.get(pk=1)
        self.assertFalse(settings.agent_wallet_withdrawals_enabled)
        self.assertFalse(settings.tikane_withdrawals_enabled)

        agent_on = admin_client.post(reverse('manage_agent_commissions'), {
            'action': 'set_agent_wallet_withdrawals',
            'enabled': 'on',
        })
        tikane_on = admin_client.post(reverse('manage_withdrawal_commissions'), {
            'action': 'set_tikane_withdrawals',
            'enabled': 'on',
        })

        self.assertEqual(agent_on.status_code, 302)
        self.assertEqual(tikane_on.status_code, 302)
        settings.refresh_from_db()
        self.assertTrue(settings.agent_wallet_withdrawals_enabled)
        self.assertTrue(settings.tikane_withdrawals_enabled)

    def test_admin_cannot_approve_tikane_or_agent_withdrawal_when_control_is_off(self):
        admin_client = Client()
        admin_client.force_login(self.admin)
        self.admin.role = 'super_admin'
        self.admin.save(update_fields=['role'])
        self.customer.is_agent = True
        self.customer.save(update_fields=['is_agent'])

        cases = (
            ('tikane', 'HTG', 'tikane_withdrawals_enabled'),
            ('multidevice', 'USD', 'agent_wallet_withdrawals_enabled'),
        )
        for account_type, currency, setting_field in cases:
            with self.subTest(account_type=account_type):
                SystemSettings.objects.update_or_create(
                    pk=1,
                    defaults={setting_field: False},
                )
                withdrawal = WithdrawalRequest.objects.create(
                    user=self.customer,
                    amount=Decimal('20.00'),
                    currency=currency,
                    account_type=account_type,
                    status='pending',
                    amount_debited=True,
                )

                response = admin_client.post(reverse('profile'), {
                    'withdrawal_decision': '1',
                    'withdrawal_id': withdrawal.pk,
                    'action': 'approve',
                })

                self.assertEqual(response.status_code, 302)
                withdrawal.refresh_from_db()
                self.assertEqual(withdrawal.status, 'pending')
                self.assertIsNone(withdrawal.confirmed_at)
                self.assertIsNone(withdrawal.confirmed_by)
                self.assertFalse(withdrawal.receipt_generated)

    def submit_tikane_withdrawal(self, currency='HTG', amount='20.00', key='tikane-withdrawal-1'):
        return self.customer_client.post(reverse('withdraw_funds'), {
            'account': 'tikane',
            'amount': amount,
            'currency': currency,
            'pin': self.profile.withdrawal_pin,
            'secure_code': self.profile.withdrawal_code,
            'idempotency_key': key,
        })

    def test_tikane_withdrawal_debits_principal_once_and_fee_from_matching_wallet_currency(self):
        response = self.submit_tikane_withdrawal()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.account.refresh_from_db()
        self.wallet.refresh_from_db()
        withdrawal = WithdrawalRequest.objects.get(pk=response.json()['withdrawal_id'])
        self.assertEqual(self.account.balance, Decimal('80.00'))
        self.assertEqual(self.account.total_withdrawals, Decimal('20.00'))
        self.assertEqual(self.wallet.balance, Decimal('80.00'))
        self.assertEqual(self.wallet.balance_htg, Decimal('7.50'))
        self.assertEqual(self.wallet.balance_peso, Decimal('20.00'))
        self.assertEqual(self.wallet.balance_eur, Decimal('30.00'))
        self.assertEqual(withdrawal.status, 'pending')
        self.assertEqual(withdrawal.fee_total, Decimal('2.50'))
        self.assertEqual(withdrawal.fee_system, Decimal('2.50'))
        self.assertTrue(withdrawal.amount_debited)
        self.assertEqual(response.json()['amount'], '20.00')
        self.assertEqual(response.json()['fee_total'], '2.50')
        self.assertEqual(response.json()['net_received'], '20.00')
        self.assertIn('frais prélevés séparément', response.json()['message'])
        self.assertEqual(
            Transaction.objects.filter(
                sender=self.customer,
                receiver=self.admin,
                type='withdrawal_system_commission',
                amount=Decimal('2.50'),
                currency='HTG',
            ).count(),
            1,
        )

        repeated = self.submit_tikane_withdrawal()
        self.assertTrue(repeated.json()['duplicate'])
        self.account.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('80.00'))
        self.assertEqual(self.wallet.balance_htg, Decimal('7.50'))
        self.assertEqual(WithdrawalRequest.objects.filter(user=self.customer).count(), 1)

    def test_tikane_withdrawal_rejects_currency_mismatch_without_financial_movement(self):
        response = self.submit_tikane_withdrawal(currency='USD', key='tikane-currency-mismatch')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.account.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('100.00'))
        self.assertEqual(self.wallet.balance, Decimal('80.00'))
        self.assertEqual(self.wallet.balance_htg, Decimal('10.00'))
        self.assertFalse(WithdrawalRequest.objects.filter(user=self.customer).exists())
        self.assertFalse(Transaction.objects.filter(type='withdrawal_system_commission').exists())

    def test_insufficient_tikane_principal_does_not_debit_wallet_fee(self):
        self.account.balance = Decimal('10.00')
        self.account.save(update_fields=['balance'])

        response = self.submit_tikane_withdrawal(key='tikane-insufficient-principal')

        self.assertFalse(response.json()['success'])
        self.account.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('10.00'))
        self.assertEqual(self.wallet.balance_htg, Decimal('10.00'))
        self.assertFalse(WithdrawalRequest.objects.filter(user=self.customer).exists())

    def test_insufficient_wallet_fee_does_not_debit_tikane_principal(self):
        self.wallet.balance_htg = Decimal('1.00')
        self.wallet.save(update_fields=['balance_htg'])

        response = self.submit_tikane_withdrawal(key='tikane-insufficient-fee')

        self.assertFalse(response.json()['success'])
        self.account.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('100.00'))
        self.assertEqual(self.wallet.balance_htg, Decimal('1.00'))
        self.assertFalse(WithdrawalRequest.objects.filter(user=self.customer).exists())

    def test_tikane_withdrawal_debits_fees_only_from_the_matching_wallet_currency_field(self):
        wallet_fields = {
            'USD': 'balance',
            'HTG': 'balance_htg',
            'DOP': 'balance_peso',
            'EUR': 'balance_eur',
        }

        for currency, wallet_field in wallet_fields.items():
            with self.subTest(currency=currency):
                TiKaneAccount.objects.filter(pk=self.account.pk).update(
                    currency=currency,
                    balance=Decimal('100.00'),
                    total_withdrawals=Decimal('0.00'),
                )
                self.wallet.refresh_from_db()
                for field in wallet_fields.values():
                    setattr(self.wallet, field, Decimal('100.00'))
                self.wallet.save(update_fields=list(wallet_fields.values()))

                response = self.submit_tikane_withdrawal(
                    currency=currency,
                    key=f'tikane-currency-fee-{currency.lower()}',
                )

                self.assertTrue(response.json()['success'])
                self.account.refresh_from_db()
                self.wallet.refresh_from_db()
                self.assertEqual(self.account.balance, Decimal('80.00'))
                for field in wallet_fields.values():
                    expected = Decimal('97.50') if field == wallet_field else Decimal('100.00')
                    self.assertEqual(getattr(self.wallet, field), expected)

    def test_legacy_account_without_currency_cannot_withdraw(self):
        self.account.delete()
        legacy_account = TiKaneAccount(
            user=self.customer,
            account_number='TK-LEGACY-UNKNOWN',
            unique_identifier='TKID-LEGACY-UNKNOWN',
            plan=self.plan,
            currency=None,
            status='active',
            maturity_date=timezone.now() - timedelta(days=1),
            balance=Decimal('100.00'),
        )
        TiKaneAccount.objects.bulk_create([legacy_account])

        response = self.submit_tikane_withdrawal(key='tikane-legacy-unknown')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertEqual(TiKaneAccount.objects.get(user=self.customer).balance, Decimal('100.00'))
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_htg, Decimal('10.00'))
        self.assertFalse(WithdrawalRequest.objects.filter(user=self.customer).exists())

    def test_agent_processing_same_pending_tikane_withdrawal_does_not_debit_again(self):
        request_response = self.submit_tikane_withdrawal(key='tikane-agent-process-once')
        withdrawal_id = request_response.json()['withdrawal_id']
        agent = User.objects.create_user(
            username='tikane-withdrawal-agent',
            password='agentpass123',
            is_agent=True,
        )
        Agent.objects.filter(user=agent).update(is_active=True)
        agent_client = Client()
        agent_client.force_login(agent)

        with patch('marketplace.web_push.send_notification_push'):
            with self.captureOnCommitCallbacks(execute=True):
                first = agent_client.post(reverse('agent_process_withdrawal'), {'withdrawal_id': withdrawal_id})
                repeated = agent_client.post(reverse('agent_process_withdrawal'), {'withdrawal_id': withdrawal_id})

        self.assertEqual(first.status_code, 302)
        self.assertEqual(repeated.status_code, 302)
        self.account.refresh_from_db()
        self.wallet.refresh_from_db()
        withdrawal = WithdrawalRequest.objects.get(pk=withdrawal_id)
        self.assertEqual(withdrawal.status, 'completed')
        self.assertEqual(self.account.balance, Decimal('80.00'))
        self.assertEqual(self.account.total_withdrawals, Decimal('20.00'))
        self.assertEqual(self.wallet.balance_htg, Decimal('7.50'))
        self.assertEqual(
            Transaction.objects.filter(
                sender=self.customer,
                receiver=agent,
                type='withdrawal_agent',
                amount=Decimal('20.00'),
                currency='HTG',
            ).count(),
            1,
        )

    def test_agent_cannot_complete_already_debited_tikane_withdrawal_while_off(self):
        request_response = self.submit_tikane_withdrawal(key='tikane-agent-off-pending')
        withdrawal_id = request_response.json()['withdrawal_id']
        SystemSettings.objects.create(pk=1, tikane_withdrawals_enabled=False)
        agent = User.objects.create_user(
            username='tikane-disabled-agent',
            password='agentpass123',
            is_agent=True,
        )
        Agent.objects.filter(user=agent).update(is_active=True)
        agent_client = Client()
        agent_client.force_login(agent)

        response = agent_client.post(
            reverse('agent_process_withdrawal'),
            {'withdrawal_id': withdrawal_id},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            WithdrawalRequest.objects.get(pk=withdrawal_id).status,
            'pending',
        )
        self.assertFalse(
            WithdrawalTransaction.objects.filter(
                withdrawal_request_id=withdrawal_id,
                status='completed',
            ).exists()
        )

    def test_agent_cannot_complete_already_debited_agent_wallet_withdrawal_while_off(self):
        self.customer.is_agent = True
        self.customer.save(update_fields=['is_agent'])
        self.wallet.commission_balance_htg = Decimal('100.00')
        self.wallet.save(update_fields=['commission_balance_htg'])
        agent_request_response = self.customer_client.post(reverse('withdraw_funds'), {
            'account': 'multidevice',
            'amount': '20.00',
            'currency': 'HTG',
            'pin': self.profile.withdrawal_pin,
            'secure_code': self.profile.withdrawal_code,
            'idempotency_key': 'agent-withdrawal-pending',
        })
        withdrawal_id = agent_request_response.json()['withdrawal_id']
        SystemSettings.objects.create(pk=1, agent_wallet_withdrawals_enabled=False)
        payout_agent = User.objects.create_user(
            username='agent-wallet-disabled-payout',
            password='agentpass123',
            is_agent=True,
        )
        Agent.objects.filter(user=payout_agent).update(is_active=True)
        agent_client = Client()
        agent_client.force_login(payout_agent)

        response = agent_client.post(
            reverse('agent_process_withdrawal'),
            {'withdrawal_id': withdrawal_id},
        )

        self.assertEqual(response.status_code, 302)
        withdrawal = WithdrawalRequest.objects.get(pk=withdrawal_id)
        self.assertEqual(withdrawal.status, 'pending')
        self.wallet.refresh_from_db()
        self.assertEqual(
            self.wallet.commission_balance_htg,
            Decimal('100.00') - withdrawal.amount - withdrawal.fee_total,
        )

    def test_tikane_access_form_requires_explicit_currency(self):
        self.assertTrue(TiKaneAccessRequestForm.base_fields['currency'].required)
        self.assertEqual(
            [value for value, _label in TiKaneAccessRequestForm.base_fields['currency'].choices],
            ['USD', 'HTG', 'DOP', 'EUR'],
        )
        with self.assertRaises(ValidationError):
            TiKaneAccount.objects.create(
                user=self.customer,
                account_number='TK-MISSING-CURRENCY',
                unique_identifier='TKID-MISSING-CURRENCY',
                currency=None,
            )
        with self.assertRaises(ValidationError):
            TiKaneAccessRequest.objects.create(
                user=self.customer,
                full_name='Test Customer',
                email='tikane-customer@example.com',
                phone='50900000000',
                currency=None,
            )

    def test_admin_creates_tikane_account_with_request_currency(self):
        self.account.delete()
        access_request = TiKaneAccessRequest.objects.create(
            user=self.customer,
            full_name='Test Customer',
            email='tikane-customer@example.com',
            phone='50900000000',
            currency='EUR',
            plan=self.plan,
            acceptance_clause=True,
        )
        admin_client = Client()
        admin_client.force_login(self.admin)

        response = admin_client.post(reverse('admin_tikane_requests'), {
            'action': 'approve_immediate',
            'request_id': access_request.pk,
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(TiKaneAccount.objects.get(user=self.customer).currency, 'EUR')

    def test_agent_tikane_deposit_rejects_currency_mismatch_without_movement(self):
        agent = User.objects.create_user(
            username='tikane-deposit-agent',
            password='agentpass123',
            is_agent=True,
        )
        Agent.objects.filter(user=agent).update(is_active=True)
        agent.set_security_pin('12345678')
        agent.set_otp_code('1234')
        agent_wallet = Wallet.objects.get(user=agent)
        agent_wallet.balance_htg = Decimal('500.00')
        agent_wallet.save(update_fields=['balance_htg'])
        agent_client = Client()
        agent_client.force_login(agent)

        response = agent_client.post(
            reverse('agent_deposit'),
            {
                'account_number': self.customer.account_code,
                'amount': '20.00',
                'currency': 'USD',
                'tikane_deposit': 'on',
                'agent_pin': '12345678',
                'final_code': '1234',
                'idempotency_key': 'tikane-deposit-mismatch',
            },
            follow=True,
        )

        self.assertContains(response, 'La devise du compte Ti Kanè est HTG')
        self.account.refresh_from_db()
        agent_wallet.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('100.00'))
        self.assertEqual(agent_wallet.balance_htg, Decimal('500.00'))
        self.assertFalse(Deposit.objects.filter(client=self.customer, tikane_deposit=True).exists())

    def test_tikane_daily_payment_rejects_deposit_in_other_currency(self):
        deposit = Deposit.objects.create(
            client=self.customer,
            amount=Decimal('10.00'),
            currency='USD',
            tikane_deposit=True,
            tikane_account=self.account,
            status='confirmed',
        )

        with self.assertRaises(ValueError):
            self.account.mark_next_unpaid_day_paid(deposit=deposit)

        self.assertFalse(self.account.daily_payments.filter(paid=True).exists())

    def test_tikane_currency_migration_keeps_existing_rows_unknown(self):
        migration = importlib.import_module('marketplace.migrations.0109_tikane_currency').Migration
        added_fields = {
            (operation.model_name, operation.name): operation.field
            for operation in migration.operations
            if operation.__class__.__name__ == 'AddField'
        }

        account_currency = added_fields[('tikaneaccount', 'currency')]
        request_currency = added_fields[('tikaneaccessrequest', 'currency')]
        self.assertTrue(account_currency.null)
        self.assertFalse(account_currency.blank)
        self.assertTrue(request_currency.null)
        self.assertFalse(request_currency.blank)
        self.assertFalse(any(operation.__class__.__name__ == 'RunPython' for operation in migration.operations))


class SiteBannerAdminAccessTest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(username='banneradmin', email='banneradmin@example.com', password='admin123')
        self.shop = Shop.objects.create(owner=self.admin_user, name='Boutique de test')
        self.product = Product.objects.create(
            shop=self.shop,
            category=None,
            name='Produit banner test',
            description='Desc',
            price_ht=Decimal('49.99'),
            quantity=10,
            image='https://example.com/banner.jpg',
        )
        self.client = Client()

    def test_banner_dashboard_requires_admin_login(self):
        response = self.client.get(reverse('site_banner_dashboard'))
        self.assertEqual(response.status_code, 302)

        self.client.login(username='banneradmin', password='admin123')
        response = self.client.get(reverse('site_banner_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Gestion de la bannière')

    def test_gp_dashboard_is_separate_route_and_title(self):
        response = self.client.get(reverse('site_gp_dashboard'))
        self.assertEqual(response.status_code, 302)

        self.client.login(username='banneradmin', password='admin123')
        response = self.client.get(reverse('site_gp_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '⭐ GP — Gestion des Priorités')
        self.assertContains(response, 'Groupes de Priorité')
        self.assertContains(response, 'Gestion des cartes')
        self.assertContains(response, 'Rotation intelligente')
        self.assertNotContains(response, '🎬 Bannière')
        self.assertNotContains(response, '📊 Stats')

        banner_response = self.client.get(reverse('site_banner_dashboard'))
        self.assertContains(banner_response, '🎯 Gestion de la bannière')
        self.assertNotContains(banner_response, '⭐ GP — Gestion des Priorités')
        self.assertNotContains(banner_response, 'Groupes de Priorité')

    def test_gp_entry_is_visible_only_to_authorized_admins(self):
        normal_user = User.objects.create_user(username='regularuser', email='regular@example.com', password='pass123')
        self.client.force_login(normal_user)
        response = self.client.get(reverse('home'))
        self.assertNotContains(response, '⭐ GP')
        self.assertNotContains(response, '🎯 Gestion de la bannière')

        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('home'))
        self.assertContains(response, '🎯 Gestion de la bannière')
        self.assertContains(response, '⭐ GP')

    def test_search_page_includes_mobile_responsive_rules(self):
        response = self.client.get(reverse('search'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('@media (max-width: 767px)', html)
        self.assertIn('grid-template-columns: 1fr;', html)


class HomePageRouteTest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(username='banneradmin', email='banneradmin@example.com', password='admin123')
        self.shop = Shop.objects.create(owner=self.admin_user, name='Boutique de test')
        self.product = Product.objects.create(
            shop=self.shop,
            category=None,
            name='Produit banner test',
            description='Desc',
            price_ht=Decimal('49.99'),
            quantity=10,
            image='https://example.com/banner.jpg',
        )
        self.banner = SiteBanner.objects.create(
            product=self.product,
            title='Offre du moment',
            subtitle='Produit phare',
            button_text='Voir le produit',
            is_active=True,
            display_mode='static',
            access_mode='free',
        )
        self.client = Client()

    def test_root_url_renders_home_page_with_banner(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Produits en vedette')
        self.assertContains(response, 'shop-carousel')

    def test_home_page_renders_compact_banner_product_carousel(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'site-top-banner-product-carousel')
        self.assertContains(response, 'Produit banner test')

    def test_banner_management_link_is_visible_only_to_principal_admin(self):
        self.client.login(username='banneradmin', password='admin123')
        response = self.client.get(reverse('home'))
        self.assertContains(response, '🎯 Gestion de la bannière')
        self.assertContains(response, '⭐ GP')
        self.assertContains(response, 'ACTIVATION BANNIÈRE')
        self.assertContains(response, reverse('site_banner_dashboard'))
        self.assertContains(response, reverse('site_banner_activation'))

        secondary = User.objects.create_user(
            username='banner_secondary',
            password='admin123',
            role='admin_secondary',
            is_staff=True,
        )
        self.client.force_login(secondary)
        response = self.client.get(reverse('home'))
        self.assertNotContains(response, '🎯 Gestion de la bannière')
        self.assertNotContains(response, '⭐ GP')
        self.assertNotContains(response, 'ACTIVATION BANNIÈRE')
        self.assertNotEqual(self.client.get(reverse('site_banner_dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('site_banner_activation')).status_code, 403)

        normal = User.objects.create_user(username='banner_normal', password='admin123')
        self.client.force_login(normal)
        response = self.client.get(reverse('home'))
        self.assertNotContains(response, '🎯 Gestion de la bannière')
        self.assertNotContains(response, '⭐ GP')
        self.assertNotContains(response, 'ACTIVATION BANNIÈRE')
        self.assertNotEqual(self.client.get(reverse('site_banner_dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('site_banner_activation')).status_code, 403)

    def test_principal_can_disable_banner_globally_without_reserved_space(self):
        self.client.login(username='banneradmin', password='admin123')
        response = self.client.post(reverse('site_banner_activation_toggle'))
        self.assertRedirects(response, reverse('site_banner_activation'))
        self.assertFalse(SystemSettings.objects.get(pk=1).banner_enabled)

        response = self.client.get(reverse('home'))
        self.assertNotContains(response, 'site-top-banner')
        self.assertNotContains(response, 'Produit banner test')

        self.client.post(reverse('site_banner_activation_toggle'))
        self.assertTrue(SystemSettings.objects.get(pk=1).banner_enabled)
        self.assertContains(self.client.get(reverse('home')), 'site-top-banner')

    def test_active_banner_is_exposed_in_template_context(self):
        SiteBanner.objects.create(
            product=self.product,
            title='Promo flash',
            subtitle='Grande réduction',
            button_text='Voir le produit',
            is_active=True,
            display_order=1,
        )
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Promo flash')


class SiteBannerPriorityTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='priority_admin', password='pass12345')
        self.shop = Shop.objects.create(owner=self.admin, name='Priority Shop')
        self.banner = SiteBanner.objects.create(product=self._product('Banner product'))

    def _product(self, name, group=None, weight=1):
        return Product.objects.create(
            shop=self.shop,
            name=name,
            description='test',
            price_ht=10,
            quantity=1,
            image=f'https://example.com/{name.replace(" ", "-")}.jpg',
            priority_group=group,
            banner_weight=weight,
        )

    def _request(self, user):
        request = RequestFactory().get('/')
        request.user = user
        request.resolver_match = None
        return request

    def test_active_group_and_product_order_has_no_duplicates(self):
        premium = PriorityGroup.objects.create(name='Premium', priority=1, weight=3)
        normal = PriorityGroup.objects.create(name='Normal', priority=2, weight=1)
        self._product('Premium A', premium, 10)
        self._product('Premium B', premium, 3)
        self._product('Normal A', normal, 1)
        context = site_banner_context(self._request(self.admin))
        products = context['banner_carousel_products']
        self.assertEqual(len(products), len({product.id for product in products}))
        self.assertNotEqual(products[0].priority_group_id, products[1].priority_group_id)

        normal.is_active = False
        normal.save(update_fields=['is_active'])
        products = site_banner_context(self._request(self.admin))['banner_carousel_products']
        self.assertNotIn(normal.id, [product.priority_group_id for product in products])

    def test_admin_visibility_setting_does_not_hide_normal_users(self):
        settings = SystemSettings.objects.create(pk=1, banner_visible_to_admins=False, principal_banner_visible=False)
        secondary = User.objects.create_user(username='priority_secondary', role='admin_secondary', is_staff=True)
        normal = User.objects.create_user(username='priority_user')
        self.assertIsNone(site_banner_context(self._request(secondary))['site_banner'])
        self.assertIsNotNone(site_banner_context(self._request(normal))['site_banner'])
        self.assertIsNone(site_banner_context(self._request(self.admin))['site_banner'])
        settings.banner_enabled = False
        settings.save(update_fields=['banner_enabled'])
        self.assertEqual(site_banner_context(self._request(normal))['banner_carousel_products'], [])

    def test_individual_weight_controls_long_run_frequency(self):
        products = [
            self._product('A', weight=1),
            self._product('B', weight=3),
            self._product('C', weight=6),
        ]
        schedule = _build_banner_rotation_schedule(products, length=100)
        counts = {product.name: schedule.count(index) for index, product in enumerate(products)}
        self.assertGreater(counts['C'], counts['B'])
        self.assertGreater(counts['B'], counts['A'])
        self.assertLessEqual(abs(counts['B'] / counts['A'] - 3), 1)
        self.assertLessEqual(abs(counts['C'] / counts['A'] - 6), 1)

    def test_group_schedule_excludes_expired_groups(self):
        from datetime import timedelta
        from django.utils import timezone

        expired = PriorityGroup.objects.create(
            name='Expired', end_date=timezone.now() - timedelta(minutes=1)
        )
        active = PriorityGroup.objects.create(name='Active', priority=1)
        expired_product = self._product('Expired card', expired)
        self._product('Active card', active)
        products = site_banner_context(self._request(self.admin))['banner_carousel_products']
        self.assertNotIn(expired_product, products)

    def test_priority_mutations_are_principal_only(self):
        secondary = User.objects.create_user(username='priority_delegate', role='admin_secondary', is_staff=True)
        SiteBannerPermission.objects.create(banner=self.banner, user=secondary, granted_by=self.admin)
        self.client.force_login(secondary)
        response = self.client.post(reverse('site_banner_dashboard'), {
            'group_action': '1', 'name': 'Forbidden', 'priority': 1, 'weight': 1,
        })
        self.assertEqual(response.status_code, 403)
        response = self.client.post(reverse('site_banner_dashboard'), {
            'product_priority_action': '1', 'product_id': self.banner.product_id,
            'banner_priority': 1, 'banner_weight': 10,
        })
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.admin)
        response = self.client.post(reverse('site_banner_dashboard'), {
            'group_action': '1', 'name': 'Allowed', 'priority': 1, 'weight': 2,
        })
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse('site_banner_dashboard'), {
            'product_priority_action': '1', 'product_id': self.banner.product_id,
            'banner_priority': 2, 'banner_weight': 10,
        })
        self.assertEqual(response.status_code, 302)
        self.banner.product.refresh_from_db()
        self.assertEqual(self.banner.product.banner_weight, 10)


class SiteBannerAccessModeTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='banner_access_admin', password='pass12345', email='banner-access-admin@example.com')
        self.user = User.objects.create_user(username='banner_access_user', password='pass12345', email='banner-access-user@example.com')
        self.shop = Shop.objects.create(owner=self.admin, name='Banner Access Shop')
        self.product = Product.objects.create(shop=self.shop, name='Banner Access Product', description='test', price_ht=10, quantity=1, image='https://example.com/banner.jpg')
        self.banner = SiteBanner.objects.create(product=self.product, title='Banner Access Test', access_mode='free')
        self.client.login(username='banner_access_user', password='pass12345')

    def test_free_banner_is_accessible(self):
        self.assertTrue(self.banner.can_access(self.user))
        self.assertEqual(self.client.get(reverse('site_banner_click', args=[self.banner.id])).status_code, 302)

    def test_selected_banner_requires_grant_and_revocation_is_immediate(self):
        self.banner.access_mode = 'selected'
        self.banner.save(update_fields=['access_mode'])
        self.assertFalse(self.banner.can_access(self.user))
        self.assertEqual(self.client.get(reverse('site_banner_click', args=[self.banner.id])).status_code, 403)
        self.client.logout()
        self.client.login(username='banner_access_admin', password='pass12345')
        self.client.post(reverse('site_banner_access', args=[self.banner.id]), {'user_id': self.user.id})
        self.banner.refresh_from_db()
        self.assertTrue(self.banner.can_access(self.user))
        self.client.post(reverse('site_banner_access', args=[self.banner.id]), {'user_id': self.user.id, 'action': 'remove'})
        self.assertFalse(self.banner.can_access(self.user))

    def test_access_mode_transitions_and_secondary_admin_protection(self):
        self.client.logout()
        secondary = User.objects.create_user(username='banner_access_secondary', password='pass12345', email='banner-access-secondary@example.com', role='admin_secondary')
        self.client.login(username='banner_access_secondary', password='pass12345')
        banner_data = {
            'banner_id': self.banner.id,
            'product': self.product.id,
            'title': self.banner.title,
            'subtitle': self.banner.subtitle,
            'button_text': self.banner.button_text,
            'is_active': 'on',
            'display_order': self.banner.display_order,
            'display_mode': self.banner.display_mode,
            'autoplay_seconds': self.banner.autoplay_seconds,
            'scope': self.banner.scope,
            'access_price': self.banner.access_price,
        }
        response = self.client.post(reverse('site_banner_dashboard'), {**banner_data, 'access_mode': 'selected'})
        self.assertNotEqual(response.status_code, 200)
        self.banner.refresh_from_db()
        self.assertEqual(self.banner.access_mode, 'free')
        self.client.logout()
        self.client.login(username='banner_access_admin', password='pass12345')
        self.client.post(reverse('site_banner_dashboard'), {**banner_data, 'access_mode': 'selected'})
        self.banner.refresh_from_db()
        self.assertEqual(self.banner.access_mode, 'selected')
        self.assertFalse(self.banner.can_access(self.user))
        self.client.post(reverse('site_banner_dashboard'), {**banner_data, 'access_mode': 'free'})
        self.banner.refresh_from_db()
        self.assertEqual(self.banner.access_mode, 'free')
        self.assertTrue(self.banner.can_access(self.user))

    def test_paid_banner_debits_microcash_once_and_rejects_insufficient_balance(self):
        self.banner.access_mode = 'paid'
        self.banner.access_price = Decimal('25.00')
        self.banner.save(update_fields=['access_mode', 'access_price'])
        wallet, _ = Wallet.objects.get_or_create(user=self.user)
        wallet.balance = Decimal('20.00')
        wallet.save(update_fields=['balance'])
        response = self.client.post(reverse('site_banner_purchase', args=[self.banner.id]))
        self.assertEqual(response.status_code, 400)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal('20.00'))
        wallet.balance = Decimal('30.00')
        wallet.save(update_fields=['balance'])
        response = self.client.post(reverse('site_banner_purchase', args=[self.banner.id]))
        self.assertEqual(response.status_code, 200)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal('5.00'))
        self.assertTrue(SiteBannerPayment.objects.get(banner=self.banner, user=self.user).status == 'confirmed')
        self.assertEqual(self.client.post(reverse('site_banner_purchase', args=[self.banner.id])).json()['already_paid'], True)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal('5.00'))


class RealEstateMembershipApprovalTest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='admin123')
        self.client = Client()
        self.client.login(username='admin', password='admin123')
        self.user = User.objects.create_user(username='member1', password='memberpass123', email='member1@example.com')
        self.profile, _ = Profile.objects.get_or_create(user=self.user)
        self.wallet, _ = Wallet.objects.get_or_create(user=self.user)
        self.wallet.balance_htg = Decimal('200.00')
        self.wallet.save()
        self.membership_request = RealEstateMembershipRequest.objects.create(
            user=self.user,
            full_name='Member One',
            phone='50933333333',
            sample_property_title='Maison Test',
            message='Demande d’adhésion'
        )

    def test_approve_membership_request_deducts_fee_when_balance_sufficient(self):
        url = reverse('real_estate:approve_membership_request', args=[self.membership_request.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        self.membership_request.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(self.membership_request.status, 'approved')
        self.assertTrue(self.user.profile.is_real_estate_member)
        self.assertEqual(self.wallet.balance_htg, Decimal('100.00'))
        self.assertEqual(self.wallet.real_estate_loan_balance_htg, Decimal('0.00'))

    def test_approve_membership_request_grants_auto_loan_when_balance_insufficient(self):
        settings = MarketplaceSettings.get_solo()
        settings.enable_real_estate_auto_loan = True
        settings.real_estate_membership_fee_htg = Decimal('100.00')
        settings.save()

        self.wallet.balance_htg = Decimal('0.00')
        self.wallet.save()

        self.membership_request.status = 'pending'
        self.membership_request.save(update_fields=['status'])

        url = reverse('real_estate:approve_membership_request', args=[self.membership_request.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        self.membership_request.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(self.membership_request.status, 'approved')
        self.assertTrue(self.user.profile.is_real_estate_member)
        self.assertEqual(self.wallet.balance_htg, Decimal('0.00'))
        self.assertEqual(self.wallet.real_estate_loan_balance_htg, Decimal('100.00'))

    def test_approve_membership_request_grants_partial_auto_loan_when_partial_balance_exists(self):
        settings = MarketplaceSettings.get_solo()
        settings.enable_real_estate_auto_loan = True
        settings.real_estate_membership_fee_htg = Decimal('100.00')
        settings.save()

        self.wallet.balance_htg = Decimal('50.00')
        self.wallet.real_estate_loan_balance_htg = Decimal('0.00')
        self.wallet.save()

        self.membership_request.status = 'pending'
        self.membership_request.save(update_fields=['status'])

        url = reverse('real_estate:approve_membership_request', args=[self.membership_request.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        self.membership_request.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(self.membership_request.status, 'approved')
        self.assertTrue(self.user.profile.is_real_estate_member)
        self.assertEqual(self.wallet.balance_htg, Decimal('0.00'))
        self.assertEqual(self.wallet.real_estate_loan_balance_htg, Decimal('50.00'))

    def test_approve_membership_request_fails_when_balance_insufficient_and_auto_loan_disabled(self):
        settings = MarketplaceSettings.get_solo()
        settings.enable_real_estate_auto_loan = False
        settings.real_estate_membership_fee_htg = Decimal('100.00')
        settings.save()

        self.wallet.balance_htg = Decimal('50.00')
        self.wallet.real_estate_loan_balance_htg = Decimal('0.00')
        self.wallet.save()

        self.membership_request.status = 'pending'
        self.membership_request.save(update_fields=['status'])

        url = reverse('real_estate:approve_membership_request', args=[self.membership_request.id])
        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'solde HTG est insuffisant')

        self.membership_request.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(self.membership_request.status, 'pending')
        self.assertEqual(self.wallet.real_estate_loan_balance_htg, Decimal('0.00'))
        self.assertEqual(self.wallet.balance_htg, Decimal('50.00'))


class MarketplaceSettingsAdminPermissionTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.normal_admin = User.objects.create_user(username='admin_normal', email='admin_normal@example.com', password='adminpass123', is_staff=True)
        self.principal_admin = User.objects.create_user(username='admin_principal', email='admin_principal@example.com', password='principalpass123', is_staff=True)
        from django.contrib.contenttypes.models import ContentType
        content_type = ContentType.objects.get_for_model(User)
        permission, _ = Permission.objects.get_or_create(
            codename='principal_admin_power',
            content_type=content_type,
            defaults={'name': 'Pouvoir admin principal'}
        )
        self.principal_admin.user_permissions.add(permission)
        self.settings_admin = MarketplaceSettingsAdmin(MarketplaceSettings, admin.site)

    def test_non_principal_admin_cannot_view_marketplace_settings(self):
        request = self.factory.get('/admin/marketplace/marketplacesettings/')
        request.user = self.normal_admin
        self.assertFalse(self.settings_admin.has_view_permission(request))
        self.assertFalse(self.settings_admin.has_change_permission(request))

    def test_principal_admin_can_view_and_change_marketplace_settings(self):
        request = self.factory.get('/admin/marketplace/marketplacesettings/')
        request.user = self.principal_admin
        self.assertTrue(self.settings_admin.has_view_permission(request))
        self.assertTrue(self.settings_admin.has_change_permission(request))


class TransferFundsTest(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(username='sender', password='senderpass123', email='sender@example.com')
        self.receiver = User.objects.create_user(username='receiver', password='receiverpass123', email='receiver@example.com')
        self.sender_wallet, _ = Wallet.objects.get_or_create(user=self.sender)
        self.sender_wallet.can_transfer = True
        self.receiver_wallet, _ = Wallet.objects.get_or_create(user=self.receiver)
        self.sender_wallet.balance = Decimal('100.00')
        self.sender_wallet.save()
        self.admin_user = User.objects.create_superuser(username='admin_transfer', email='admin_transfer@example.com', password='adminpass123')
        self.admin_wallet, _ = Wallet.objects.get_or_create(user=self.admin_user)
        self.admin_wallet.balance = Decimal('0.00')
        self.admin_wallet.save()

        self.client = Client()
        self.client.login(username='sender', password='senderpass123')

    def test_sender_can_transfer_usd_to_receiver(self):
        url = reverse('transfer_funds')
        with patch('marketplace.web_push.send_notification_push') as send_push:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(url, {
                    'recipient_account_code': self.receiver.account_code,
                    'source_account': 'principal',
                    'currency': 'USD',
                    'amount': '10.00',
                    'idempotency_key': 'transfer-usd-001',
                })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('success'), True)
        self.sender_wallet.refresh_from_db()
        self.receiver_wallet.refresh_from_db()
        self.assertEqual(self.sender_wallet.balance, Decimal('90.00'))
        self.assertEqual(self.receiver_wallet.balance, Decimal('10.00'))
        self.assertTrue(Transfer.objects.filter(sender=self.sender, receiver=self.receiver, amount=Decimal('10.00'), currency='USD').exists())
        self.assertTrue(Transaction.objects.filter(sender=self.sender, receiver=self.receiver, amount=Decimal('10.00'), currency='USD', type='transfer').exists())
        transfer = Transfer.objects.get(sender=self.sender, receiver=self.receiver)
        notification = PersistentNotification.objects.get(
            recipient=self.receiver,
            notification_type='money_received',
        )
        self.assertEqual(
            notification.deduplication_key,
            f'transfer-received:{transfer.pk}:user:{self.receiver.pk}',
        )
        self.assertEqual(notification.target_url, reverse('profile'))
        send_push.assert_called_once_with(notification.pk)

    def test_repeated_transfer_request_with_same_key_moves_money_once(self):
        payload = {
            'recipient_account_code': self.receiver.account_code,
            'source_account': 'principal',
            'currency': 'USD',
            'amount': '10.00',
            'idempotency_key': 'transfer-retry-001',
        }

        first = self.client.post(reverse('transfer_funds'), payload)
        repeated = self.client.post(reverse('transfer_funds'), payload)
        conflicting = self.client.post(
            reverse('transfer_funds'),
            {**payload, 'amount': '12.00'},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(repeated.status_code, 200)
        self.assertTrue(repeated.json()['duplicate'])
        self.assertEqual(conflicting.status_code, 409)
        self.sender_wallet.refresh_from_db()
        self.receiver_wallet.refresh_from_db()
        self.assertEqual(self.sender_wallet.balance, Decimal('90.00'))
        self.assertEqual(self.receiver_wallet.balance, Decimal('10.00'))
        self.assertEqual(Transfer.objects.filter(sender=self.sender, receiver=self.receiver).count(), 1)

    def test_transfer_rejects_invalid_amount_recipient_and_insufficient_balance(self):
        url = reverse('transfer_funds')
        invalid_amount = self.client.post(url, {
            'recipient_account_code': self.receiver.account_code,
            'source_account': 'principal',
            'currency': 'USD',
            'amount': '0',
            'idempotency_key': 'transfer-invalid-amount-001',
        })
        self_transfer = self.client.post(url, {
            'recipient_account_code': self.sender.account_code,
            'source_account': 'principal',
            'currency': 'USD',
            'amount': '10.00',
            'idempotency_key': 'transfer-self-001',
        })
        missing_recipient = self.client.post(url, {
            'recipient_account_code': 'NOT-A-REAL-ACCOUNT',
            'source_account': 'principal',
            'currency': 'USD',
            'amount': '10.00',
            'idempotency_key': 'transfer-missing-recipient-001',
        })
        insufficient_balance = self.client.post(url, {
            'recipient_account_code': self.receiver.account_code,
            'source_account': 'principal',
            'currency': 'USD',
            'amount': '200.00',
            'idempotency_key': 'transfer-insufficient-001',
        })

        self.assertEqual(invalid_amount.status_code, 400)
        self.assertEqual(self_transfer.status_code, 400)
        self.assertEqual(missing_recipient.status_code, 400)
        self.assertEqual(insufficient_balance.status_code, 400)
        self.sender_wallet.refresh_from_db()
        self.receiver_wallet.refresh_from_db()
        self.assertEqual(self.sender_wallet.balance, Decimal('100.00'))
        self.assertEqual(self.receiver_wallet.balance, Decimal('0.00'))
        self.assertFalse(Transfer.objects.exists())
        self.assertFalse(Transaction.objects.filter(type='transfer').exists())

    def test_transfer_failure_after_wallet_updates_rolls_back_operation(self):
        payload = {
            'recipient_account_code': self.receiver.account_code,
            'source_account': 'principal',
            'currency': 'USD',
            'amount': '10.00',
            'idempotency_key': 'transfer-rollback-001',
        }

        with patch(
            'marketplace.views.TransferReceipt.objects.create',
            side_effect=RuntimeError('simulated receipt creation failure'),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('transfer_funds'), payload)

        self.sender_wallet.refresh_from_db()
        self.receiver_wallet.refresh_from_db()
        self.assertEqual(self.sender_wallet.balance, Decimal('100.00'))
        self.assertEqual(self.receiver_wallet.balance, Decimal('0.00'))
        self.assertFalse(Transfer.objects.exists())
        self.assertFalse(Transaction.objects.filter(type='transfer').exists())
        self.assertFalse(PersistentNotification.objects.exists())

    def test_profile_transfer_creates_persistent_notification_for_receiver(self):
        response = self.client.post(reverse('profile'), {
            'transfer_submit': '1',
            'recipient_account_code': self.receiver.account_code,
            'source_account': 'principal',
            'currency': 'USD',
            'amount': '10.00',
            'idempotency_key': 'transfer-profile-001',
        })

        self.assertEqual(response.status_code, 302)
        transfer = Transfer.objects.get(sender=self.sender, receiver=self.receiver)
        notification = PersistentNotification.objects.get(
            recipient=self.receiver,
            notification_type='money_received',
        )
        self.assertEqual(
            notification.deduplication_key,
            f'transfer-received:{transfer.pk}:user:{self.receiver.pk}',
        )
        self.assertFalse(
            PersistentNotification.objects.filter(
                recipient=self.sender,
                deduplication_key=f'transfer-received:{transfer.pk}:user:{self.receiver.pk}',
            ).exists()
        )

    def test_sender_can_transfer_htg_from_micro_device_and_credit_system_commission(self):
        self.sender_wallet.commission_balance_htg = Decimal('100.00')
        self.sender_wallet.save(update_fields=['commission_balance_htg'])
        self.receiver_wallet.commission_balance_htg = Decimal('0.00')
        self.receiver_wallet.save(update_fields=['commission_balance_htg'])
        self.admin_wallet.commission_balance_htg = Decimal('0.00')
        self.admin_wallet.save(update_fields=['commission_balance_htg'])

        url = reverse('transfer_funds')
        response = self.client.post(url, {
            'recipient_account_code': self.receiver.account_code,
            'source_account': 'micro_device',
            'currency': 'HTG',
            'amount': '50.00',
            'idempotency_key': 'transfer-htg-001',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('success'), True)

        self.sender_wallet.refresh_from_db()
        self.receiver_wallet.refresh_from_db()
        self.admin_wallet.refresh_from_db()
        self.assertEqual(self.sender_wallet.commission_balance_htg, Decimal('44.00'))
        self.assertEqual(self.receiver_wallet.commission_balance_htg, Decimal('50.00'))
        self.assertEqual(self.admin_wallet.commission_balance_htg, Decimal('6.00'))
        self.assertTrue(Transfer.objects.filter(sender=self.sender, receiver=self.receiver, amount=Decimal('50.00'), currency='HTG').exists())
        self.assertTrue(Transaction.objects.filter(sender=self.sender, receiver=self.receiver, amount=Decimal('50.00'), currency='HTG', type='transfer').exists())

    def test_agent_sender_gets_agent_commission_for_htg_transfer(self):
        self.sender.is_agent = True
        self.sender.save(update_fields=['is_agent'])
        self.sender_wallet.commission_balance_htg = Decimal('100.00')
        self.sender_wallet.save(update_fields=['commission_balance_htg'])
        self.receiver_wallet.commission_balance_htg = Decimal('0.00')
        self.receiver_wallet.save(update_fields=['commission_balance_htg'])
        self.admin_wallet.commission_balance_htg = Decimal('0.00')
        self.admin_wallet.save(update_fields=['commission_balance_htg'])

        url = reverse('transfer_funds')
        response = self.client.post(url, {
            'recipient_account_code': self.receiver.account_code,
            'source_account': 'micro_device',
            'currency': 'HTG',
            'amount': '50.00',
            'idempotency_key': 'transfer-agent-htg-001',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('success'), True)

        self.sender_wallet.refresh_from_db()
        self.receiver_wallet.refresh_from_db()
        self.admin_wallet.refresh_from_db()
        self.assertEqual(self.sender_wallet.commission_balance_htg, Decimal('46.00'))
        self.assertEqual(self.receiver_wallet.commission_balance_htg, Decimal('50.00'))
        self.assertEqual(self.admin_wallet.commission_balance_htg, Decimal('4.00'))
        self.assertTrue(Transfer.objects.filter(sender=self.sender, receiver=self.receiver, amount=Decimal('50.00'), currency='HTG').exists())
        self.assertTrue(Transaction.objects.filter(sender=self.sender, receiver=self.receiver, amount=Decimal('50.00'), currency='HTG', type='transfer').exists())


class MicroSDICashCriticalProtectionTest(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(username='cash-user-a', password='testpass123')
        self.user_b = User.objects.create_user(username='cash-user-b', password='testpass123')
        self.wallet_a = Wallet.objects.get(user=self.user_a)
        self.wallet_b = Wallet.objects.get(user=self.user_b)
        self.client.force_login(self.user_a)

    def test_wallet_and_transaction_apis_are_scoped_to_authenticated_user(self):
        Transaction.objects.create(
            sender=self.user_b,
            receiver=self.user_b,
            amount=Decimal('8.00'),
            currency='USD',
            type='private-test',
            status='approved',
        )

        wallets_response = self.client.get(reverse('wallet-list'))
        transactions_response = self.client.get(reverse('transaction-list'))

        wallets_payload = wallets_response.json()
        wallets = wallets_payload.get('results', []) if isinstance(wallets_payload, dict) else wallets_payload
        transactions_payload = transactions_response.json()
        transactions = transactions_payload.get('results', []) if isinstance(transactions_payload, dict) else transactions_payload
        self.assertEqual([item['user'] for item in wallets], [self.user_a.pk])
        self.assertFalse(any(
            transaction['sender'] == self.user_b.pk or transaction['receiver'] == self.user_b.pk
            for transaction in transactions
        ))

    def test_agent_api_does_not_allow_normal_user_to_update_another_agent(self):
        self.user_b.is_agent = True
        self.user_b.role = 'agent'
        self.user_b.save(update_fields=['is_agent', 'role'])
        other_agent, _ = Agent.objects.get_or_create(user=self.user_b)
        other_agent.is_active = True
        other_agent.save(update_fields=['is_active'])

        response = self.client.patch(
            reverse('agent-detail', args=[other_agent.pk]),
            data=json.dumps({'is_active': False}),
            content_type='application/json',
        )

        self.assertIn(response.status_code, (403, 404))
        other_agent.refresh_from_db()
        self.assertTrue(other_agent.is_active)

    def test_agent_recharge_rejects_nonpositive_values_and_is_idempotent(self):
        self.user_a.is_agent = True
        self.user_a.role = 'agent'
        self.user_a.save(update_fields=['is_agent', 'role'])
        agent, _ = Agent.objects.get_or_create(user=self.user_a)
        agent.is_active = True
        agent.save(update_fields=['is_active'])
        self.wallet_a.balance = Decimal('10.00')
        self.wallet_a.save(update_fields=['balance'])

        url = reverse('agent-recharge')
        for value in ('0', '-1.00'):
            response = self.client.post(
                url,
                data=json.dumps({'user_id': self.user_b.pk, 'amount': value}),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 400)

        payload = {'user_id': self.user_b.pk, 'amount': '2.50'}
        first = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_IDEMPOTENCY_KEY='recharge-test-001',
        )
        repeated = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_IDEMPOTENCY_KEY='recharge-test-001',
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(repeated.status_code, 200)
        self.assertTrue(repeated.json()['duplicate'])
        self.wallet_a.refresh_from_db()
        self.wallet_b.refresh_from_db()
        self.assertEqual(self.wallet_a.balance, Decimal('7.50'))
        self.assertEqual(self.wallet_b.balance, Decimal('2.50'))
        self.assertEqual(Transaction.objects.filter(type='recharge').count(), 1)

    def test_new_profile_wallet_starts_at_zero(self):
        Wallet.objects.filter(user=self.user_a).delete()

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.wallet_a = Wallet.objects.get(user=self.user_a)
        self.assertEqual(self.wallet_a.balance, Decimal('0.00'))

    def test_profile_forms_share_pending_keys_across_tabs(self):
        first_page = self.client.get(reverse('profile'))
        first_key = first_page.context['transfer_idempotency_key']
        second_page = self.client.get(reverse('profile'))
        self.assertEqual(second_page.context['transfer_idempotency_key'], first_key)

    def test_withdrawal_request_failure_rolls_back_wallet_debit(self):
        profile, _ = Profile.objects.get_or_create(user=self.user_a)
        profile.withdrawal_pin = '12345678'
        profile.withdrawal_code = '1234'
        profile.save(update_fields=['withdrawal_pin', 'withdrawal_code'])
        self.wallet_a.balance = Decimal('100.00')
        self.wallet_a.save(update_fields=['balance'])
        payload = {
            'account': 'principal',
            'amount': '10.00',
            'currency': 'USD',
            'pin': profile.withdrawal_pin,
            'secure_code': profile.withdrawal_code,
            'idempotency_key': 'withdraw-rollback-001',
        }

        with patch(
            'marketplace.models.WithdrawalRequest.objects.create',
            side_effect=RuntimeError('simulated request creation failure'),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('withdraw_funds'), payload)

        self.wallet_a.refresh_from_db()
        self.assertEqual(self.wallet_a.balance, Decimal('100.00'))
        self.assertFalse(WithdrawalRequest.objects.filter(user=self.user_a).exists())

    def test_repeated_withdrawal_post_debits_wallet_once(self):
        profile, _ = Profile.objects.get_or_create(user=self.user_a)
        profile.withdrawal_pin = '12345678'
        profile.withdrawal_code = '1234'
        profile.save(update_fields=['withdrawal_pin', 'withdrawal_code'])
        self.wallet_a.balance = Decimal('100.00')
        self.wallet_a.save(update_fields=['balance'])
        payload = {
            'account': 'principal',
            'amount': '10.00',
            'currency': 'USD',
            'pin': profile.withdrawal_pin,
            'secure_code': profile.withdrawal_code,
            'idempotency_key': 'withdraw-repeat-001',
        }
        no_fee = {'total_fee': Decimal('0.00'), 'system_fee': Decimal('0.00'), 'agent_fee': Decimal('0.00')}

        with patch('marketplace.views.CommissionManager.get_withdrawal_commission_breakdown', return_value=no_fee):
            first = self.client.post(reverse('withdraw_funds'), payload)
            repeated = self.client.post(reverse('withdraw_funds'), payload)

        self.assertTrue(first.json()['success'])
        self.assertTrue(repeated.json()['duplicate'])
        self.wallet_a.refresh_from_db()
        self.assertEqual(self.wallet_a.balance, Decimal('90.00'))
        self.assertEqual(WithdrawalRequest.objects.filter(user=self.user_a).count(), 1)


class ConcurrentTransferProtectionTest(TransactionTestCase):
    reset_sequences = True

    def test_simultaneous_transfers_cannot_overdraw_one_wallet(self):
        sender = User.objects.create_user(username='concurrent-sender', password='testpass123')
        receiver = User.objects.create_user(username='concurrent-receiver', password='testpass123')
        User.objects.create_superuser(
            username='concurrent-admin',
            email='concurrent-admin@example.com',
            password='testpass123',
        )
        sender_wallet = Wallet.objects.get(user=sender)
        sender_wallet.balance = Decimal('10.00')
        sender_wallet.can_transfer = True
        sender_wallet.save(update_fields=['balance', 'can_transfer'])

        clients = [Client(), Client()]
        for client in clients:
            client.force_login(sender)

        barrier = Barrier(2)
        payloads = [
            {
                'recipient_account_code': receiver.account_code,
                'source_account': 'principal',
                'currency': 'USD',
                'amount': '7.00',
                'idempotency_key': f'concurrent-transfer-{index}',
            }
            for index in (1, 2)
        ]

        def submit(client, payload):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                response = client.post(reverse('transfer_funds'), payload)
                return response.status_code, response.json()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(submit, client, payload)
                for client, payload in zip(clients, payloads)
            ]
            outcomes = [future.result(timeout=30) for future in futures]

        sender_wallet.refresh_from_db()
        receiver_wallet = Wallet.objects.get(user=receiver)
        self.assertGreaterEqual(sender_wallet.balance, Decimal('0.00'))
        self.assertEqual(
            receiver_wallet.balance,
            Transfer.objects.filter(sender=sender, receiver=receiver).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0.00'),
        )
        self.assertTrue(any(status_code == 200 and body.get('success') for status_code, body in outcomes))


class ReturnRefundNotificationTest(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='refund-customer', password='testpass123')
        self.admin = User.objects.create_superuser(
            username='refund-admin',
            email='refund-admin@example.com',
            password='testpass123',
        )
        self.wallet = Wallet.objects.get(user=self.customer)
        self.order = Order.objects.create(
            buyer=self.customer,
            total_amount=Decimal('40.00'),
            delivery_address='Adresse test',
            status='delivered',
        )
        self.return_request = ReturnRequest.objects.create(
            order=self.order,
            customer=self.customer,
            reason='damaged',
            description='Produit endommagé',
        )
        self.client.force_login(self.admin)

    def test_order_refund_replay_credits_wallet_once(self):
        PaymentManager.refund_order(self.order)
        PaymentManager.refund_order(self.order)

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('40.00'))
        self.assertEqual(Transaction.objects.filter(receiver=self.customer, type='refund').count(), 1)

    def test_process_refund_notifies_without_changing_wallet_balance(self):
        with patch('marketplace.web_push.send_notification_push') as send_push:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    reverse('returnrequest-process-refund', args=[self.return_request.pk]),
                    data={'amount': '20.00'},
                )

        self.assertEqual(response.status_code, 200)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('0.00'))
        self.assertTrue(Transaction.objects.filter(
            receiver=self.customer,
            amount=Decimal('20.00'),
            currency='HTG',
            type='refund',
            status='approved',
        ).exists())
        notification = PersistentNotification.objects.get(
            recipient=self.customer,
            notification_type='refund',
        )
        self.assertEqual(
            notification.deduplication_key,
            f'return-refund-request:{self.return_request.pk}:customer:{self.customer.pk}',
        )
        self.assertIn('ne crédite pas le portefeuille', notification.message)
        send_push.assert_called_once_with(notification.pk)


class AdminAddAgentViewTest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username='admin_agent_test',
            email='admin_agent_test@example.com',
            password='adminpass123'
        )
        self.target_user = User.objects.create_user(
            username='target_agent_user',
            password='userpass123',
            email='target_agent_user@example.com'
        )
        self.client = Client()
        self.client.login(username='admin_agent_test', password='adminpass123')

    def test_admin_can_activate_user_as_agent(self):
        url = reverse('admin_add_agent')
        response = self.client.post(
            url,
            {'user_id': self.target_user.id, 'action': 'activate'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        self.target_user.refresh_from_db()
        agent_obj = Agent.objects.filter(user=self.target_user).first()

        self.assertTrue(self.target_user.is_agent)
        self.assertIsNotNone(agent_obj)
        self.assertTrue(agent_obj.is_active)
        self.assertContains(response, 'a été activé comme agent', msg_prefix='Le message de succès doit apparaître')

    def test_principal_admin_funds_active_agent_wallet_once(self):
        self.target_user.is_agent = True
        self.target_user.save(update_fields=['is_agent'])
        agent, _ = Agent.objects.get_or_create(user=self.target_user)
        agent.is_active = True
        agent.save(update_fields=['is_active'])
        wallet, _ = Wallet.objects.get_or_create(user=self.target_user)
        wallet.balance_htg = Decimal('15.00')
        wallet.commission_balance_htg = Decimal('3.00')
        wallet.save(update_fields=['balance_htg', 'commission_balance_htg'])
        payload = {
            'action': 'add',
            'target': 'single',
            'user_id': str(self.target_user.pk),
            'account_type': 'agent',
            'currency': 'HTG',
            'amount': '7.50',
            'idempotency_key': 'admin-agent-funding-001',
        }

        first = self.client.post(reverse('admin_add_money'), payload)
        repeated = self.client.post(reverse('admin_add_money'), payload)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(repeated.status_code, 302)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance_htg, Decimal('22.50'))
        self.assertEqual(wallet.commission_balance_htg, Decimal('3.00'))
        transaction_record = Transaction.objects.get(type='admin_add_agent')
        self.assertEqual(transaction_record.sender, self.admin_user)
        self.assertEqual(transaction_record.receiver, self.target_user)
        self.assertEqual(transaction_record.amount, Decimal('7.50'))
        self.assertEqual(transaction_record.currency, 'HTG')
        self.assertEqual(transaction_record.status, 'approved')
        self.assertEqual(Transaction.objects.filter(type='admin_add_agent').count(), 1)
        credit_notification = PersistentNotification.objects.get(
            recipient=self.target_user,
            notification_type='admin_money_received',
        )
        self.assertEqual(
            credit_notification.deduplication_key,
            f'admin-wallet-credit:{transaction_record.pk}:{self.target_user.pk}',
        )
        self.assertIn('7.50 HTG', credit_notification.message)

    def test_admin_funding_of_user_wallet_creates_credit_notification(self):
        user = User.objects.create_user(
            username='funded_wallet_user',
            password='userpass123',
        )
        wallet, _ = Wallet.objects.get_or_create(user=user)

        response = self.client.post(
            reverse('admin_add_money'),
            {
                'action': 'add',
                'target': 'single',
                'user_id': str(user.pk),
                'account_type': 'principal',
                'currency': 'USD',
                'amount': '12.34',
            },
        )

        self.assertEqual(response.status_code, 302)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal('12.34'))
        funding_transaction = Transaction.objects.get(
            type='admin_add',
            receiver=user,
        )
        notification = PersistentNotification.objects.get(
            recipient=user,
            notification_type='admin_money_received',
        )
        self.assertEqual(funding_transaction.status, 'approved')
        self.assertIn('12.34 USD', notification.message)
        self.assertEqual(
            notification.deduplication_key,
            f'admin-wallet-credit:{funding_transaction.pk}:{user.pk}',
        )

    def test_admin_credit_notification_failure_rolls_back_agent_credit(self):
        self.target_user.is_agent = True
        self.target_user.save(update_fields=['is_agent'])
        agent, _ = Agent.objects.get_or_create(user=self.target_user)
        agent.is_active = True
        agent.save(update_fields=['is_active'])
        wallet, _ = Wallet.objects.get_or_create(user=self.target_user)
        wallet.balance_htg = Decimal('10.00')
        wallet.save(update_fields=['balance_htg'])

        with patch(
            'marketplace.views.create_persistent_notification',
            side_effect=RuntimeError('simulated notification creation failure'),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse('admin_add_money'),
                    {
                        'action': 'add',
                        'target': 'single',
                        'user_id': str(self.target_user.pk),
                        'account_type': 'agent',
                        'currency': 'HTG',
                        'amount': '5.00',
                        'idempotency_key': 'admin-agent-funding-notification-rollback-001',
                    },
                )

        wallet.refresh_from_db()
        self.assertEqual(wallet.balance_htg, Decimal('10.00'))
        self.assertFalse(Transaction.objects.filter(type='admin_add_agent').exists())
        self.assertFalse(
            PersistentNotification.objects.filter(
                recipient=self.target_user,
                notification_type='admin_money_received',
            ).exists()
        )

    def test_principal_admin_can_fund_own_operational_wallet_once(self):
        wallet, _ = Wallet.objects.get_or_create(user=self.admin_user)
        wallet.balance_htg = Decimal('10.00')
        wallet.save(update_fields=['balance_htg'])
        payload = {
            'action': 'add',
            'target': 'single',
            'user_id': str(self.admin_user.pk),
            'account_type': 'agent',
            'currency': 'HTG',
            'amount': '7.50',
            'idempotency_key': 'admin-self-funding-001',
        }

        first = self.client.post(reverse('admin_add_money'), payload)
        repeated = self.client.post(reverse('admin_add_money'), payload)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(repeated.status_code, 302)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance_htg, Decimal('17.50'))
        transaction_record = Transaction.objects.get(type='admin_add_agent')
        self.assertEqual(transaction_record.sender, self.admin_user)
        self.assertEqual(transaction_record.receiver, self.admin_user)
        self.assertEqual(transaction_record.amount, Decimal('7.50'))
        self.assertEqual(transaction_record.currency, 'HTG')
        self.assertEqual(Transaction.objects.filter(type='admin_add_agent').count(), 1)

    def test_agent_funding_rejects_invalid_requests_without_credit(self):
        self.target_user.is_agent = True
        self.target_user.save(update_fields=['is_agent'])
        agent, _ = Agent.objects.get_or_create(user=self.target_user)
        agent.is_active = True
        agent.save(update_fields=['is_active'])
        ordinary_user = User.objects.create_user(
            username='ordinary_funding_target',
            password='userpass123',
        )
        wallet, _ = Wallet.objects.get_or_create(user=self.target_user)
        wallet.balance_htg = Decimal('10.00')
        wallet.save(update_fields=['balance_htg'])
        base_payload = {
            'action': 'add',
            'target': 'single',
            'user_id': str(self.target_user.pk),
            'account_type': 'agent',
            'currency': 'HTG',
            'idempotency_key': 'admin-agent-funding-invalid-001',
        }

        for invalid_amount in ('0', '-2', '1.001', 'NaN'):
            self.client.post(
                reverse('admin_add_money'),
                {**base_payload, 'amount': invalid_amount},
            )

        self.client.post(
            reverse('admin_add_money'),
            {**base_payload, 'user_id': str(ordinary_user.pk), 'amount': '5.00'},
        )
        self.client.post(
            reverse('admin_add_money'),
            {**base_payload, 'user_id': '99999999', 'amount': '5.00'},
        )

        wallet.refresh_from_db()
        self.assertEqual(wallet.balance_htg, Decimal('10.00'))
        self.assertFalse(Transaction.objects.filter(type='admin_add_agent').exists())
        self.assertFalse(
            PersistentNotification.objects.filter(
                recipient=self.target_user,
                notification_type='admin_money_received',
            ).exists()
        )

    def test_nonprincipal_staff_and_agent_cannot_fund_agent_wallet(self):
        self.target_user.is_agent = True
        self.target_user.save(update_fields=['is_agent'])
        agent, _ = Agent.objects.get_or_create(user=self.target_user)
        agent.is_active = True
        agent.save(update_fields=['is_active'])
        wallet, _ = Wallet.objects.get_or_create(user=self.target_user)
        wallet.balance_htg = Decimal('10.00')
        wallet.save(update_fields=['balance_htg'])

        staff_user = User.objects.create_user(
            username='nonprincipal_staff',
            password='staffpass123',
            is_staff=True,
        )
        self.client.force_login(staff_user)
        payload = {
            'action': 'add',
            'target': 'single',
            'user_id': str(self.target_user.pk),
            'account_type': 'agent',
            'currency': 'HTG',
            'amount': '5.00',
            'idempotency_key': 'staff-agent-funding-001',
        }
        self.client.post(reverse('admin_add_money'), payload)

        agent_user = User.objects.create_user(
            username='ordinary_funding_agent',
            password='agentpass123',
            is_agent=True,
        )
        agent, _ = Agent.objects.get_or_create(user=agent_user)
        agent.is_active = True
        agent.save(update_fields=['is_active'])
        self.client.force_login(agent_user)
        self.client.post(reverse('admin_add_money'), payload)

        wallet.refresh_from_db()
        self.assertEqual(wallet.balance_htg, Decimal('10.00'))
        self.assertFalse(Transaction.objects.filter(type='admin_add_agent').exists())

    def test_agent_funding_rolls_back_if_transaction_creation_fails(self):
        self.target_user.is_agent = True
        self.target_user.save(update_fields=['is_agent'])
        agent, _ = Agent.objects.get_or_create(user=self.target_user)
        agent.is_active = True
        agent.save(update_fields=['is_active'])
        wallet, _ = Wallet.objects.get_or_create(user=self.target_user)
        wallet.balance_htg = Decimal('10.00')
        wallet.save(update_fields=['balance_htg'])

        with patch(
            'marketplace.views.Transaction.objects.create',
            side_effect=RuntimeError('simulated transaction creation failure'),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse('admin_add_money'),
                    {
                        'action': 'add',
                        'target': 'single',
                        'user_id': str(self.target_user.pk),
                        'account_type': 'agent',
                        'currency': 'HTG',
                        'amount': '5.00',
                        'idempotency_key': 'admin-agent-funding-rollback-001',
                    },
                )

        wallet.refresh_from_db()
        self.assertEqual(wallet.balance_htg, Decimal('10.00'))
        self.assertFalse(Transaction.objects.filter(type='admin_add_agent').exists())


class MarketplaceResellerFlowTest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(username='admin_market', email='admin_market@example.com', password='adminpass123')
        self.seller_user = User.objects.create_user(username='seller1', email='seller1@example.com', password='sellerpass123')
        self.seller_user.is_seller = True
        self.seller_user.save()
        self.owner_user = User.objects.create_user(username='owner1', email='owner1@example.com', password='ownerpass123')
        self.owner_user.is_seller = True
        self.owner_user.save()

        self.owner_shop = Shop.objects.create(owner=self.owner_user, name='Boutique Origine')
        self.seller_shop = Shop.objects.create(owner=self.seller_user, name='Boutique Revendeur')
        self.product = Product.objects.create(
            shop=self.owner_shop,
            name='Produit Original',
            description='Produit de test',
            price_ht=Decimal('100.00'),
            price_input_currency='USD',
            quantity=20
        )
        self.settings = MarketplaceSettings.get_solo()
        self.settings.default_commission_type = 'percent'
        self.settings.default_commission_value = Decimal('20.00')
        self.settings.validation_required = True
        self.settings.allow_auto_copy = False
        self.settings.save()

        self.client = Client()

    def test_seller_can_request_product_access(self):
        self.client.login(username='seller1', password='sellerpass123')
        url = reverse('request_product_access', args=[self.product.id])
        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ProductAccessRequest.objects.filter(seller=self.seller_user, product=self.product, status='pending').exists())

    def test_duplicate_access_request_is_blocked(self):
        ProductAccessRequest.objects.create(
            seller=self.seller_user,
            product=self.product,
            owner_shop=self.owner_shop,
            status='pending'
        )
        self.client.login(username='seller1', password='sellerpass123')
        url = reverse('request_product_access', args=[self.product.id])
        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProductAccessRequest.objects.filter(seller=self.seller_user, product=self.product).count(), 1)
        self.assertContains(response, 'Vous avez déjà une demande en cours ou approuvée pour ce produit.')

    def test_auto_copy_without_validation_works(self):
        self.settings.allow_auto_copy = True
        self.settings.validation_required = False
        self.settings.save()

        self.client.login(username='seller1', password='sellerpass123')
        url = reverse('request_product_access', args=[self.product.id])
        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ProductAccessRequest.objects.filter(seller=self.seller_user, product=self.product, status='approved').exists())
        self.assertTrue(ResellerProduct.objects.filter(seller=self.seller_user, original_product=self.product, copied_product__isnull=False, status='active').exists())

    def test_admin_can_approve_request_and_create_copy(self):
        req = ProductAccessRequest.objects.create(
            seller=self.seller_user,
            product=self.product,
            owner_shop=self.owner_shop,
            status='pending'
        )
        self.client.login(username='admin_market', password='adminpass123')
        url = reverse('admin:marketplace_productaccessrequest_approve_form')
        response = self.client.post(url, {
            'ids': str(req.id),
            'commission_type': 'percent',
            'commission_value': '20'
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ResellerProduct.objects.filter(seller=self.seller_user, original_product=self.product, copied_product__isnull=False).exists())
        reseller = ResellerProduct.objects.get(seller=self.seller_user, original_product=self.product)
        self.assertEqual(reseller.commission_type, 'percent')
        self.assertEqual(reseller.commission_value, Decimal('20.00'))

    def test_admin_can_approve_product_access_request_from_profile(self):
        req = ProductAccessRequest.objects.create(
            seller=self.seller_user,
            product=self.product,
            owner_shop=self.owner_shop,
            status='pending'
        )
        self.client.login(username='admin_market', password='adminpass123')
        url = reverse('profile')
        response = self.client.post(url, {
            'access_request_decision': '1',
            'request_id': str(req.id),
            'action': 'approve',
            'commission_type': 'percent',
            'commission_value': '15'
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ResellerProduct.objects.filter(seller=self.seller_user, original_product=self.product, copied_product__isnull=False).exists())
        reseller = ResellerProduct.objects.get(seller=self.seller_user, original_product=self.product)
        self.assertEqual(reseller.commission_value, Decimal('15.00'))

    def test_admin_can_reject_product_access_request_from_profile(self):
        req = ProductAccessRequest.objects.create(
            seller=self.seller_user,
            product=self.product,
            owner_shop=self.owner_shop,
            status='pending'
        )
        self.client.login(username='admin_market', password='adminpass123')
        url = reverse('profile')
        response = self.client.post(url, {
            'access_request_decision': '1',
            'request_id': str(req.id),
            'action': 'reject'
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, 'rejected')

    def test_commission_distribution_for_reseller_copy(self):
        copied_product = Product.objects.create(
            shop=self.seller_shop,
            name='Produit Copie',
            description='Copie du produit',
            price_ht=Decimal('100.00'),
            price_input_currency='USD',
            quantity=10
        )
        reseller_entry = ResellerProduct.objects.create(
            seller=self.seller_user,
            original_product=self.product,
            copied_product=copied_product,
            commission_type='percent',
            commission_value=Decimal('20.00'),
            status='active'
        )
        buyer = User.objects.create_user(username='client1', email='client1@example.com', password='clientpass123')
        Wallet.objects.get_or_create(user=buyer, defaults={'balance': Decimal('500.00')})
        Wallet.objects.get_or_create(user=self.owner_user, defaults={'balance': Decimal('0.00')})
        Wallet.objects.get_or_create(user=self.seller_user, defaults={'balance': Decimal('0.00')})
        Wallet.objects.get_or_create(user=self.admin_user, defaults={'balance': Decimal('0.00')})
        order = Order.objects.create(
            buyer=buyer,
            total_amount=Decimal('100.00'),
            delivery_address='Adresse test',
            payment_method='htg_wallet',
            payment_status='approved',
            status='delivered'
        )
        OrderItem.objects.create(order=order, product=copied_product, quantity=1, price_ht=Decimal('100.00'))

        result = PaymentManager.confirm_delivery_payment(order)
        self.assertTrue(result)

        self.owner_user.wallet.refresh_from_db()
        self.seller_user.wallet.refresh_from_db()
        self.admin_user.wallet.refresh_from_db()

        self.assertEqual(self.seller_user.wallet.balance, Decimal('20.00'))
        self.assertEqual(self.owner_user.wallet.balance, Decimal('70.00'))
        self.assertEqual(self.admin_user.wallet.commission_balance_usd, Decimal('7.00'))
        self.assertEqual(self.admin_user.wallet.distribution_balance_usd, Decimal('3.00'))
        self.assertTrue(Transaction.objects.filter(type='reseller_commission', receiver=self.seller_user, amount=Decimal('20.00')).exists())
        self.assertTrue(Transaction.objects.filter(type='order_payment', receiver=self.owner_user, amount=Decimal('70.00')).exists())
        self.assertTrue(Transaction.objects.filter(type='commission_admin', receiver=self.admin_user, amount=Decimal('7.00')).exists())

    def test_commission_peuple_eligibility_requires_purchase_or_sale(self):
        buyer = User.objects.create_user(username='buyer1', email='buyer1@example.com', password='buyerpass123')
        seller = User.objects.create_user(username='seller2', email='seller2@example.com', password='sellerpass123')
        inactive_user = User.objects.create_user(username='idle', email='idle@example.com', password='idlepass123')

        seller_shop = Shop.objects.create(owner=seller, name='Boutique vendeur')
        order = Order.objects.create(
            buyer=buyer,
            total_amount=Decimal('50.00'),
            delivery_address='Adresse test',
            payment_method='htg_wallet',
            payment_status='approved',
            status='delivered'
        )
        product = Product.objects.create(
            shop=seller_shop,
            name='Produit vente',
            description='Produit pour test',
            price_ht=Decimal('50.00'),
            price_input_currency='USD',
            quantity=5
        )
        OrderItem.objects.create(order=order, product=product, quantity=1, price_ht=Decimal('50.00'))

        eligible_users = get_commission_eligible_users()
        self.assertIn(buyer, eligible_users)
        self.assertIn(seller, eligible_users)
        self.assertNotIn(inactive_user, eligible_users)


class TestSDISolFlow(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='testpass')
        self.settings = SDISolSettings.get_solo()
        self.plan = SDISolPlan.objects.create(
            name='Plan test 15 jours',
            duration_days=15,
            amount_usd=Decimal('100.00'),
            amount_htg=Decimal('2600.00'),
            is_active=True,
        )

    def create_approved_member_payment(self, user, receipt_number):
        member = SDISolMember.objects.create(
            user=user,
            plan=self.plan,
            plan_name=self.plan.name,
            active=True,
            admin_approved=True,
        )
        payment = SDISolPayment.objects.create(
            member=member,
            amount=Decimal('100.00'),
            currency='USD',
            receipt_number=receipt_number,
            due_date=timezone.now() + timedelta(days=1),
        )
        return member, payment

    def test_join_and_payment_flow(self):
        logged_in = self.client.login(username='testuser', password='testpass')
        self.assertTrue(logged_in)

        resp = self.client.get(reverse('sdi_sol'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('can_join', resp.context)

        resp = self.client.post(reverse('sdi_sol_join'), {'plan_id': self.plan.pk}, follow=True)
        self.assertEqual(resp.status_code, 200)
        member = SDISolMember.objects.filter(user=self.user, active=True).first()
        self.assertIsNotNone(member)
        self.assertFalse(member.admin_approved)
        self.assertEqual(member.plan, self.plan)
        self.assertEqual(member.plan_duration_days, 15)

        pay_url = reverse('sdi_sol_make_payment')
        amount = str(self.settings.contribution_amount_usd)
        resp = self.client.post(pay_url, {'amount': amount, 'currency': 'USD'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)
        data = resp.json()
        self.assertEqual(data.get('error'), 'Votre adhésion doit être approuvée par un admin avant de payer.')

        admin_user = User.objects.create_superuser(username='admin', email='admin@example.com', password='adminpass')
        self.client.logout()
        self.client.login(username='admin', password='adminpass')
        approve_url = reverse('sdi_sol_admin_approve_member', args=[member.id])
        group = SDISolGroup.objects.get(plan=self.plan)
        resp = self.client.post(approve_url, {'group_id': group.pk}, follow=True)
        self.assertEqual(resp.status_code, 200)
        member.refresh_from_db()
        self.assertTrue(member.admin_approved)
        self.client.logout()
        self.client.login(username='testuser', password='testpass')
        principal = User.objects.create_superuser(
            username='principal', email='principal@example.com', password='principalpass'
        )

        resp = self.client.post(pay_url, {'amount': amount, 'currency': 'USD'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('success'))
        receipt = data.get('receipt_number')
        self.assertIsNotNone(receipt)

        payment = SDISolPayment.objects.filter(receipt_number=receipt).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, 'pending')
        member.refresh_from_db()
        self.assertEqual(member.total_paid_usd, Decimal('0.00'))

        self.assertTrue(PersistentNotification.objects.filter(
            recipient=principal,
            notification_type='sdi_sol_payment_review',
        ).exists())
        self.client.logout()
        self.client.login(username='principal', password='principalpass')
        approve_payment_url = reverse('sdi_sol_admin_approve_payment', args=[payment.pk])
        resp = self.client.post(approve_payment_url, follow=True)
        self.assertEqual(resp.status_code, 200)
        payment.refresh_from_db()
        member.refresh_from_db()
        self.assertIn(payment.status, ('completed', 'late'))
        self.assertEqual(member.total_paid_usd, Decimal('100.00'))

        self.client.post(approve_payment_url, follow=True)
        member.refresh_from_db()
        self.assertEqual(member.total_paid_usd, Decimal('100.00'))

        self.client.logout()
        self.client.login(username='testuser', password='testpass')
        receipt_url = reverse('sdi_sol_payment_receipt', args=[receipt])
        resp = self.client.get(receipt_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(receipt, resp.content.decode('utf-8'))

    def test_principal_admin_cannot_approve_own_payment_or_change_financial_data(self):
        principal = User.objects.create_superuser(
            username='principal-member',
            email='principal-member@example.com',
            password='principalpass',
        )
        member, payment = self.create_approved_member_payment(principal, 'SDISOL-SELF-REVIEW')
        transactions_before = Transaction.objects.count()
        self.client.login(username='principal-member', password='principalpass')

        response = self.client.post(
            reverse('sdi_sol_admin_approve_payment', args=[payment.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        member.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertIsNone(payment.paid_at)
        self.assertEqual(member.total_paid_usd, Decimal('0.00'))
        self.assertEqual(member.total_paid_htg, Decimal('0.00'))
        self.assertEqual(Transaction.objects.count(), transactions_before)

    def test_principal_admin_can_approve_another_members_payment_only_once(self):
        member_user = User.objects.create_user(
            username='payment-owner',
            email='payment-owner@example.com',
            password='ownerpass',
        )
        member, payment = self.create_approved_member_payment(member_user, 'SDISOL-OTHER-REVIEW')
        principal = User.objects.create_superuser(
            username='principal-reviewer',
            email='principal-reviewer@example.com',
            password='principalpass',
        )
        self.client.login(username='principal-reviewer', password='principalpass')
        approve_url = reverse('sdi_sol_admin_approve_payment', args=[payment.pk])

        first_response = self.client.post(approve_url, follow=True)

        self.assertEqual(first_response.status_code, 200)
        payment.refresh_from_db()
        member.refresh_from_db()
        self.assertIn(payment.status, ('completed', 'late'))
        self.assertEqual(payment.reviewed_by, principal)
        self.assertEqual(member.total_paid_usd, Decimal('100.00'))
        first_paid_at = payment.paid_at

        second_response = self.client.post(approve_url, follow=True)

        self.assertEqual(second_response.status_code, 200)
        payment.refresh_from_db()
        member.refresh_from_db()
        self.assertEqual(payment.paid_at, first_paid_at)
        self.assertEqual(member.total_paid_usd, Decimal('100.00'))

    def test_non_principal_cannot_approve_payment_or_change_financial_data(self):
        member_user = User.objects.create_user(
            username='protected-payment-owner',
            email='protected-payment-owner@example.com',
            password='ownerpass',
        )
        member, payment = self.create_approved_member_payment(member_user, 'SDISOL-UNAUTHORIZED')
        staff = User.objects.create_user(
            username='unprivileged-staff',
            email='unprivileged-staff@example.com',
            password='staffpass',
            is_staff=True,
        )
        transactions_before = Transaction.objects.count()
        self.client.login(username='unprivileged-staff', password='staffpass')

        response = self.client.post(
            reverse('sdi_sol_admin_approve_payment', args=[payment.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        member.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertIsNone(payment.paid_at)
        self.assertIsNone(payment.reviewed_by)
        self.assertEqual(member.total_paid_usd, Decimal('0.00'))
        self.assertEqual(member.total_paid_htg, Decimal('0.00'))
        self.assertEqual(Transaction.objects.count(), transactions_before)

    def test_past_start_date_is_allowed_and_sets_plan_schedule(self):
        start_date = timezone.localdate() - timedelta(days=45)
        self.settings.start_date = start_date
        self.settings.save(update_fields=['start_date'])
        self.client.login(username='testuser', password='testpass')

        response = self.client.post(reverse('sdi_sol_join'), {'plan_id': self.plan.pk}, follow=True)

        self.assertEqual(response.status_code, 200)
        member = SDISolMember.objects.get(user=self.user)
        self.assertEqual(member.plan_start_date, start_date)
        self.assertEqual(member.next_due_date.date(), start_date + timedelta(days=15))

    def test_rejected_payment_does_not_change_member_totals(self):
        self.client.login(username='testuser', password='testpass')
        self.client.post(reverse('sdi_sol_join'), {'plan_id': self.plan.pk})
        member = SDISolMember.objects.get(user=self.user)
        staff = User.objects.create_superuser(
            username='staff',
            email='staff@example.com',
            password='staffpass',
        )
        self.client.logout()
        self.client.login(username='staff', password='staffpass')
        group = SDISolGroup.objects.get(plan=self.plan)
        self.client.post(
            reverse('sdi_sol_admin_approve_member', args=[member.pk]),
            {'group_id': group.pk},
        )
        self.client.logout()
        self.client.login(username='testuser', password='testpass')
        principal = User.objects.create_superuser(
            username='principal', email='principal@example.com', password='principalpass'
        )
        response = self.client.post(
            reverse('sdi_sol_make_payment'),
            {'amount': '100.00', 'currency': 'USD'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        payment = SDISolPayment.objects.get(receipt_number=response.json()['receipt_number'])
        self.client.logout()
        self.client.login(username='principal', password='principalpass')

        response = self.client.post(reverse('sdi_sol_admin_reject_payment', args=[payment.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        member.refresh_from_db()
        self.assertEqual(payment.status, 'rejected')
        self.assertIsNone(payment.paid_at)
        self.assertEqual(member.total_paid_usd, Decimal('0.00'))
        self.assertTrue(PersistentNotification.objects.filter(
            recipient=self.user,
            notification_type='sdi_sol_payment_result',
        ).exists())

    def test_principal_admin_can_add_a_plan(self):
        principal = User.objects.create_superuser(
            username='principal', email='principal@example.com', password='principalpass'
        )
        self.client.login(username='principal', password='principalpass')

        response = self.client.post(reverse('sdi_sol_admin_save_plan'), {
            'name': 'Plan spécial',
            'duration_days': '45',
            'amount_usd': '125.00',
            'amount_htg': '3250.00',
            'is_active': 'on',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        plan = SDISolPlan.objects.get(name='Plan spécial')
        self.assertEqual(plan.duration_days, 45)
        self.assertEqual(plan.amount_usd, Decimal('125.00'))
        self.assertTrue(plan.is_active)
        self.assertTrue(SDISolGroup.objects.filter(plan=plan).exists())

    def test_existing_member_can_request_a_second_plan_without_joining_it_early(self):
        second_plan = SDISolPlan.objects.create(
            name='Plan test 30 jours',
            duration_days=30,
            amount_usd=Decimal('150.00'),
            is_active=True,
        )
        first_group = SDISolGroup.objects.create(plan=self.plan)
        first_membership = SDISolMember.objects.create(
            user=self.user,
            plan=self.plan,
            group=first_group,
            plan_name=self.plan.name,
            position=1,
            group_position=1,
            active=True,
            admin_approved=True,
        )
        self.client.login(username='testuser', password='testpass')

        second_response = self.client.post(
            reverse('sdi_sol_join'),
            {'plan_id': second_plan.pk, 'group_id': 9999, 'position': 1},
        )

        self.assertEqual(second_response.status_code, 302)
        memberships = SDISolMember.objects.filter(user=self.user, active=True).order_by('plan_id')
        self.assertEqual(memberships.count(), 2)
        self.assertEqual(set(memberships.values_list('plan_id', flat=True)), {self.plan.pk, second_plan.pk})
        first_membership.refresh_from_db()
        second_membership = memberships.get(plan=second_plan)
        self.assertTrue(first_membership.admin_approved)
        self.assertEqual(first_membership.group, first_group)
        self.assertFalse(second_membership.admin_approved)
        self.assertIsNone(second_membership.group)
        self.assertEqual(second_membership.position, 0)
        self.assertEqual(second_membership.group_position, 0)

    def test_principal_admin_assigns_group_and_cannot_approve_own_request(self):
        self.client.login(username='testuser', password='testpass')
        self.client.post(reverse('sdi_sol_join'), {'plan_id': self.plan.pk})
        member = SDISolMember.objects.get(user=self.user, plan=self.plan)
        group = SDISolGroup.objects.get(plan=self.plan)
        principal = User.objects.create_superuser(
            username='principal',
            email='principal@example.com',
            password='principalpass',
        )
        self.client.logout()
        self.client.login(username='principal', password='principalpass')

        response = self.client.post(
            reverse('sdi_sol_admin_approve_member', args=[member.pk]),
            {'group_id': group.pk},
        )

        self.assertEqual(response.status_code, 302)
        member.refresh_from_db()
        self.assertTrue(member.admin_approved)
        self.assertEqual(member.group, group)
        self.assertEqual(member.position, 1)
        self.assertEqual(member.group_position, 1)

        self.client.post(reverse('sdi_sol_join'), {'plan_id': self.plan.pk})
        self_member = SDISolMember.objects.get(user=principal, plan=self.plan)
        response = self.client.post(
            reverse('sdi_sol_admin_approve_member', args=[self_member.pk]),
            {'group_id': group.pk},
        )
        self.assertEqual(response.status_code, 403)
        self_member.refresh_from_db()
        self.assertFalse(self_member.admin_approved)
        self.assertIsNone(self_member.group)

    def test_non_principal_staff_cannot_approve_or_reject_membership(self):
        self.client.login(username='testuser', password='testpass')
        self.client.post(reverse('sdi_sol_join'), {'plan_id': self.plan.pk})
        member = SDISolMember.objects.get(user=self.user, plan=self.plan)
        group = SDISolGroup.objects.get(plan=self.plan)
        staff = User.objects.create_user(username='staff', password='staffpass', is_staff=True)
        self.client.logout()
        self.client.login(username='staff', password='staffpass')

        approve_response = self.client.post(
            reverse('sdi_sol_admin_approve_member', args=[member.pk]),
            {'group_id': group.pk},
        )
        reject_response = self.client.post(reverse('sdi_sol_admin_reject_member', args=[member.pk]))
        legacy_remove_response = self.client.post(reverse('sdi_sol_admin_remove_member', args=[member.pk]))

        self.assertEqual(approve_response.status_code, 302)
        self.assertEqual(reject_response.status_code, 302)
        self.assertEqual(legacy_remove_response.status_code, 403)
        member.refresh_from_db()
        self.assertTrue(member.active)
        self.assertFalse(member.admin_approved)
        self.assertFalse(member.admin_rejected)

    def test_full_group_cannot_be_overfilled_and_rejection_preserves_request(self):
        self.settings.max_members = 1
        self.settings.save(update_fields=['max_members'])
        group = SDISolGroup.objects.create(plan=self.plan)
        other_user = User.objects.create_user(username='first-place', password='testpass')
        SDISolMember.objects.create(
            user=other_user,
            plan=self.plan,
            group=group,
            plan_name=self.plan.name,
            position=1,
            group_position=1,
            active=True,
            admin_approved=True,
        )
        self.client.login(username='testuser', password='testpass')
        full_join_response = self.client.post(
            reverse('sdi_sol_join'),
            {'plan_id': self.plan.pk},
        )
        self.assertEqual(full_join_response.status_code, 302)
        self.assertFalse(SDISolMember.objects.filter(user=self.user, plan=self.plan).exists())

    def test_pending_request_reserves_a_group_place(self):
        self.settings.max_members = 1
        self.settings.save(update_fields=['max_members'])
        self.client.login(username='testuser', password='testpass')

        response = self.client.post(
            reverse('sdi_sol_join'),
            {'plan_id': self.plan.pk},
        )

        self.assertEqual(response.status_code, 302)
        group = SDISolGroup.objects.get(plan=self.plan)
        self.assertEqual(group.available_places, 0)

        pending_user = User.objects.create_user(username='waiting-user', password='testpass')
        pending = SDISolMember.objects.create(
            user=pending_user,
            plan=self.plan,
            plan_name=self.plan.name,
            active=True,
            admin_approved=False,
        )
        principal = User.objects.create_superuser(
            username='principal',
            email='principal@example.com',
            password='principalpass',
        )
        self.client.login(username='principal', password='principalpass')

        response = self.client.post(
            reverse('sdi_sol_admin_approve_member', args=[pending.pk]),
            {'group_id': group.pk},
        )

        self.assertEqual(response.status_code, 302)
        pending.refresh_from_db()
        self.assertFalse(pending.admin_approved)
        self.assertIsNone(pending.group)
        self.assertEqual(self.plan.members.filter(active=True, admin_approved=True).count(), 0)
        self.assertEqual(self.plan.members.filter(active=True).count(), 2)

        self.client.post(reverse('sdi_sol_admin_reject_member', args=[pending.pk]))
        pending.refresh_from_db()
        self.assertFalse(pending.active)
        self.assertTrue(pending.admin_rejected)
        self.assertIsNone(pending.group)

    def test_members_only_see_real_names_inside_their_own_group(self):
        second_plan = SDISolPlan.objects.create(
            name='Plan privé 30 jours',
            duration_days=30,
            amount_usd=Decimal('150.00'),
            is_active=True,
        )
        first_group = SDISolGroup.objects.create(plan=self.plan)
        second_group = SDISolGroup.objects.create(plan=second_plan)
        SDISolMember.objects.create(
            user=self.user,
            plan=self.plan,
            group=first_group,
            plan_name=self.plan.name,
            position=1,
            group_position=1,
            active=True,
            admin_approved=True,
        )
        same_group_user = User.objects.create_user(
            username='same-group-user',
            first_name='PrénomGroupe',
            last_name='NomGroupe',
            password='testpass',
        )
        SDISolMember.objects.create(
            user=same_group_user,
            plan=self.plan,
            group=first_group,
            plan_name=self.plan.name,
            position=2,
            group_position=2,
            active=True,
            admin_approved=True,
        )
        for index in (1, 2):
            group_user = User.objects.create_user(
                username=f'other-group-user-{index}',
                password='testpass',
            )
            SDISolMember.objects.create(
                user=group_user,
                plan=second_plan,
                group=second_group,
                plan_name=second_plan.name,
                position=index + 2,
                group_position=index,
                active=True,
                admin_approved=True,
            )
        private_user = User.objects.create_user(
            username='private-outsider-secret',
            first_name='NomPriveSecret',
            last_name='FamillePrivee',
            password='testpass',
        )
        SDISolMember.objects.create(
            user=private_user,
            plan=second_plan,
            group=second_group,
            plan_name=second_plan.name,
            position=3,
            group_position=3,
            active=True,
            admin_approved=True,
        )
        self.client.login(username='testuser', password='testpass')

        response = self.client.get(reverse('sdi_sol'))
        page = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertIn('PrénomGroupe NomGroupe', page)
        self.assertNotIn('private-outsider-secret', page)
        self.assertNotIn('NomPriveSecret', page)
        self.assertNotIn('FamillePrivee', page)
        self.assertIn('Place 3', page)
        self.assertIn('Membre masqué 3', page)

        principal = User.objects.create_superuser(
            username='principal',
            email='principal@example.com',
            password='principalpass',
        )
        self.client.logout()
        self.client.login(username='principal', password='principalpass')
        admin_response = self.client.get(reverse('sdi_sol'))
        admin_page = admin_response.content.decode('utf-8')
        self.assertIn('NomPriveSecret FamillePrivee', admin_page)
        self.assertNotIn('Membre masqué 3', admin_page)

    def test_member_cannot_open_another_users_payment_record_or_assign_themselves(self):
        other_user = User.objects.create_user(username='other-member', password='testpass')
        other_group = SDISolGroup.objects.create(plan=self.plan)
        other_member = SDISolMember.objects.create(
            user=other_user,
            plan=self.plan,
            group=other_group,
            plan_name=self.plan.name,
            position=1,
            active=True,
            admin_approved=True,
        )
        self.client.login(username='testuser', password='testpass')

        self.client.post(
            reverse('sdi_sol_join'),
            {'plan_id': self.plan.pk, 'group_id': other_group.pk, 'position': 1},
        )
        response = self.client.get(
            reverse('sdi_sol_payments'),
            {'member_id': other_member.pk},
        )
        own_request = SDISolMember.objects.get(user=self.user, plan=self.plan)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(own_request.admin_approved)
        self.assertIsNone(own_request.group)
        self.assertEqual(own_request.position, 0)
        self.assertEqual(own_request.group_position, 0)

        payment_response = self.client.post(
            reverse('sdi_sol_make_payment'),
            {
                'member_id': other_member.pk,
                'amount': '100.00',
                'currency': 'USD',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(payment_response.status_code, 403)
        self.assertFalse(SDISolPayment.objects.filter(member=other_member).exists())
