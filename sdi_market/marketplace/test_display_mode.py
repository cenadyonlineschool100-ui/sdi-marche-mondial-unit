from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import DisplayModePermission, SystemSettings


User = get_user_model()


class GlobalDisplayModeTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username='SDI',
            password='safe-test-password',
            is_staff=True,
            is_superuser=True,
        )
        self.secondary = User.objects.create_user(
            username='display-secondary',
            password='safe-test-password',
            role='admin_secondary',
            is_staff=True,
        )
        self.other_superuser = User.objects.create_user(
            username='other-superuser',
            password='safe-test-password',
            is_staff=True,
            is_superuser=True,
        )
        self.regular_user = User.objects.create_user(
            username='display-customer',
            password='safe-test-password',
        )
        self.inactive_admin = User.objects.create_user(
            username='inactive-display-admin',
            password='safe-test-password',
            role='admin_secondary',
            is_staff=True,
            is_active=False,
        )
        self.control_url = reverse('display_mode_control')
        self.set_mode_url = reverse('set_display_mode')

    def login_as(self, user):
        self.client.force_login(user)

    def test_exact_active_superuser_sdi_uppercase_can_open_management_page(self):
        self.login_as(self.owner)

        response = self.client.get(self.control_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Administrateurs secondaires autorisés')

    def test_navigation_shows_display_mode_link_only_to_authorized_users(self):
        response = self.client.get(reverse('home'))
        self.assertNotContains(response, self.control_url)

        self.login_as(self.owner)
        response = self.client.get(reverse('home'))
        self.assertContains(response, self.control_url)

        DisplayModePermission.objects.create(user=self.secondary, granted_by=self.owner)
        self.login_as(self.secondary)
        response = self.client.get(reverse('home'))
        self.assertContains(response, self.control_url)

    def test_authorized_secondary_admin_can_only_change_display_mode(self):
        DisplayModePermission.objects.create(user=self.secondary, granted_by=self.owner)
        self.login_as(self.secondary)

        response = self.client.post(self.set_mode_url, {'mode': 'desktop'})

        self.assertRedirects(response, self.control_url)
        self.assertTrue(SystemSettings.objects.get(pk=1).desktop_display_mode_enabled)
        self.assertEqual(
            self.client.post(
                reverse('grant_display_mode_access', args=[self.regular_user.pk])
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse('revoke_display_mode_access', args=[self.secondary.pk])
            ).status_code,
            403,
        )

    def test_only_owner_can_grant_and_revoke_secondary_admin_access(self):
        self.login_as(self.owner)
        grant_url = reverse('grant_display_mode_access', args=[self.secondary.pk])

        response = self.client.post(grant_url)

        self.assertRedirects(response, self.control_url)
        self.assertTrue(DisplayModePermission.objects.filter(user=self.secondary).exists())
        response = self.client.post(
            reverse('revoke_display_mode_access', args=[self.secondary.pk])
        )
        self.assertRedirects(response, self.control_url)
        self.assertFalse(DisplayModePermission.objects.filter(user=self.secondary).exists())

    def test_unauthorized_superuser_and_regular_user_are_forbidden(self):
        for user in (self.other_superuser, self.regular_user):
            with self.subTest(username=user.username):
                self.login_as(user)
                self.assertEqual(self.client.get(self.control_url).status_code, 403)

    def test_inactive_account_cannot_use_the_feature(self):
        DisplayModePermission.objects.create(user=self.inactive_admin, granted_by=self.owner)
        self.login_as(self.inactive_admin)

        response = self.client.get(self.control_url)

        self.assertNotEqual(response.status_code, 200)

    def test_unauthenticated_user_cannot_open_management_page(self):
        response = self.client.get(self.control_url)

        self.assertEqual(response.status_code, 302)

    def test_mode_change_selects_desktop_viewport_without_extra_zoom(self):
        self.login_as(self.owner)
        response = self.client.post(self.set_mode_url, {'mode': 'desktop'})
        self.assertRedirects(response, self.control_url)

        for route_name in ('home', 'search', 'profile'):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'width=1280')
                self.assertNotContains(response, 'applyDesktopDisplayScale')
                self.assertContains(response, '<body class="desktop-display-mode">')
                self.assertContains(
                    response,
                    "if (window.screen.width <= 767 && window.matchMedia('(pointer: coarse)').matches)",
                )
                self.assertContains(response, "document.documentElement.classList.add('desktop-phone-display')")
                self.assertContains(response, 'zoom: 1.1')
                self.assertContains(
                    response,
                    'const isMobileDevice = !isDesktopDisplayMode && (isMobileUserAgent || isTouchSmallScreen || isSmallViewport);',
                )

        settings_obj = SystemSettings.objects.get(pk=1)
        settings_obj.refresh_from_db()
        self.assertTrue(settings_obj.desktop_display_mode_enabled)

        response = self.client.post(self.set_mode_url, {'mode': 'mobile'})
        self.assertRedirects(response, self.control_url)
        settings_obj.refresh_from_db()
        self.assertFalse(settings_obj.desktop_display_mode_enabled)

        response = self.client.get(reverse('home'))
        self.assertContains(response, 'width=device-width, initial-scale=1.0')
        self.assertContains(response, '<body>')
        self.assertNotContains(response, "desktop-phone-display")

    def test_django_admin_uses_global_viewport_in_both_modes(self):
        settings_obj = SystemSettings.objects.get_or_create(pk=1)[0]
        admin_routes = (
            reverse('admin:index'),
            reverse('admin:marketplace_user_changelist'),
        )

        for desktop_mode, expected_viewport, expected_phone_display in (
            (True, 'width=1280', True),
            (False, 'width=device-width, initial-scale=1.0', False),
        ):
            with self.subTest(desktop_mode=desktop_mode):
                settings_obj.desktop_display_mode_enabled = desktop_mode
                settings_obj.save(update_fields=['desktop_display_mode_enabled'])

                self.client.logout()
                login_response = self.client.get(reverse('admin:login'))
                self.assertEqual(login_response.status_code, 200)
                self.assertContains(login_response, expected_viewport)
                self.assertNotContains(login_response, 'applyDesktopDisplayScale')
                if expected_phone_display:
                    self.assertContains(login_response, "document.documentElement.classList.add('desktop-phone-display')")
                    self.assertContains(login_response, 'zoom: 1.1')
                else:
                    self.assertNotContains(login_response, "desktop-phone-display")

                self.login_as(self.owner)
                for route in admin_routes:
                    with self.subTest(route=route):
                        response = self.client.get(route)
                        self.assertEqual(response.status_code, 200)
                        self.assertContains(response, expected_viewport)
                        self.assertNotContains(response, 'applyDesktopDisplayScale')
                        if expected_phone_display:
                            self.assertContains(response, "document.documentElement.classList.add('desktop-phone-display')")
                            self.assertContains(response, 'zoom: 1.1')
                        else:
                            self.assertNotContains(response, "desktop-phone-display")

    def test_revoking_delegation_immediately_blocks_access(self):
        permission = DisplayModePermission.objects.create(
            user=self.secondary,
            granted_by=self.owner,
        )
        self.login_as(self.secondary)
        self.assertEqual(self.client.get(self.control_url).status_code, 200)

        permission.delete()

        self.assertEqual(self.client.get(self.control_url).status_code, 403)

    def test_setting_mode_requires_valid_post_and_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        page = client.get(self.control_url)
        csrf_token = page.cookies['csrftoken'].value

        self.assertEqual(client.post(self.set_mode_url, {'mode': 'desktop'}).status_code, 403)
        response = client.post(
            self.set_mode_url,
            {'mode': 'desktop'},
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SystemSettings.objects.get(pk=1).desktop_display_mode_enabled)

    def test_invalid_mode_is_not_saved(self):
        self.login_as(self.owner)

        response = self.client.post(self.set_mode_url, {'mode': 'unknown'})

        self.assertRedirects(response, self.control_url)
        self.assertFalse(SystemSettings.objects.filter(pk=1).exists())

    def test_non_secondary_account_cannot_be_granted_display_mode_access(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse('grant_display_mode_access', args=[self.regular_user.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(DisplayModePermission.objects.exists())
