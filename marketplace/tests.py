from decimal import Decimal

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from .admin import MarketplaceSettingsAdmin
from .context_processors import _build_banner_rotation_schedule, site_banner_context, system_settings_context
from .forms import normalize_phone_number
from .models import (
    User, Profile, Wallet, Agent, DepositCommissionConfig, Deposit, Transaction, CommissionRule,
    DepositReceipt, Shop, Product, ProductAccessRequest, ResellerProduct, MarketplaceSettings, Order, OrderItem,
    Transfer, SDISolSettings, SDISolMember, SDISolPayment, RealEstateMembershipRequest, SystemSettings, PriorityGroup, SiteBanner, SiteBannerAccess, SiteBannerPayment, SiteBannerEvent, SiteBannerPermission
)
from .business_logic import PaymentManager
from .views_commission import get_commission_eligible_users


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

    def test_agent_can_make_htg_deposit(self):
        url = reverse('agent_deposit')
        response = self.client.post(url, {
            'account_number': self.client_user.account_code,
            'amount': '2000',
            'currency': 'HTG',
            'agent_pin': '1234',
            'final_code': '0000',
        })
        self.assertEqual(response.status_code, 302)
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
        }, follow=True)
        self.assertContains(response, 'Solde insuffisant')
        self.assertEqual(Deposit.objects.count(), 0)

    def test_deposit_fails_when_client_phone_invalid(self):
        url = reverse('agent_deposit')
        response = self.client.post(url, {
            'account_number': 'ACC000000',
            'amount': '2000',
            'currency': 'HTG',
            'agent_pin': '1234',
            'final_code': '0000',
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
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        receipt = DepositReceipt.objects.latest('created_at')
        self.assertIsNotNone(receipt)
        self.assertIn('MicroSDICash - Reçu Bancaire Sécurisé', receipt.content)

        history_url = reverse('agent_deposit_history')
        response = self.client.get(history_url)
        self.assertEqual(response.status_code, 200)
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
        response = self.client.post(url, {
            'recipient_account_code': self.receiver.account_code,
            'source_account': 'principal',
            'currency': 'USD',
            'amount': '10.00',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('success'), True)
        self.sender_wallet.refresh_from_db()
        self.receiver_wallet.refresh_from_db()
        self.assertEqual(self.sender_wallet.balance, Decimal('90.00'))
        self.assertEqual(self.receiver_wallet.balance, Decimal('10.00'))
        self.assertTrue(Transfer.objects.filter(sender=self.sender, receiver=self.receiver, amount=Decimal('10.00'), currency='USD').exists())
        self.assertTrue(Transaction.objects.filter(sender=self.sender, receiver=self.receiver, amount=Decimal('10.00'), currency='USD', type='transfer').exists())

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
        response = self.client.post(url, {'user_id': self.target_user.id}, follow=True)
        self.assertEqual(response.status_code, 200)

        self.target_user.refresh_from_db()
        agent_obj = Agent.objects.filter(user=self.target_user).first()

        self.assertTrue(self.target_user.is_agent)
        self.assertIsNotNone(agent_obj)
        self.assertTrue(agent_obj.is_active)
        self.assertContains(response, 'a été activé comme agent', msg_prefix='Le message de succès doit apparaître')


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

    def test_join_and_payment_flow(self):
        logged_in = self.client.login(username='testuser', password='testpass')
        self.assertTrue(logged_in)

        resp = self.client.get(reverse('sdi_sol'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('can_join', resp.context)

        resp = self.client.post(reverse('sdi_sol_join'), follow=True)
        self.assertEqual(resp.status_code, 200)
        member = SDISolMember.objects.filter(user=self.user, active=True).first()
        self.assertIsNotNone(member)
        self.assertFalse(member.admin_approved)

        pay_url = reverse('sdi_sol_make_payment')
        amount = str(self.settings.contribution_amount_usd)
        resp = self.client.post(pay_url, {'amount': amount, 'currency': 'USD'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)
        data = resp.json()
        self.assertEqual(data.get('error'), 'Votre adhésion doit être approuvée par un admin avant de payer.')

        admin_user = User.objects.create_user(username='admin', email='admin@example.com', password='adminpass', is_staff=True)
        self.client.logout()
        self.client.login(username='admin', password='adminpass')
        approve_url = reverse('sdi_sol_admin_approve_member', args=[member.id])
        resp = self.client.post(approve_url, follow=True)
        self.assertEqual(resp.status_code, 200)
        member.refresh_from_db()
        self.assertTrue(member.admin_approved)
        self.client.logout()
        self.client.login(username='testuser', password='testpass')

        resp = self.client.post(pay_url, {'amount': amount, 'currency': 'USD'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('success'))
        receipt = data.get('receipt_number')
        self.assertIsNotNone(receipt)

        payment = SDISolPayment.objects.filter(receipt_number=receipt).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, 'completed')

        receipt_url = reverse('sdi_sol_payment_receipt', args=[receipt])
        resp = self.client.get(receipt_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(receipt, resp.content.decode('utf-8'))
