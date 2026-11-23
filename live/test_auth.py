from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User


@override_settings(LIVE_SSO_ENABLED=True, ALLOWED_HOSTS=['postgis.ir', 'live.postgis.ir'])
class DirectLiveAuthTests(TestCase):
    def setUp(self):
        self.live = Client(HTTP_HOST='live.postgis.ir')

    def test_anonymous_page_stays_in_live(self):
        response = self.live.get('/live/', secure=True)
        self.assertIn('/live/auth/login/', response.url)

    def test_api_expiry_is_json(self):
        response = self.live.get('/live/1/table/', secure=True, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'auth_required')

    def test_password_login_reuses_account_and_stays_live(self):
        user = User.objects.create_user('09121234567', password='StrongPass123', email='live@example.com')
        response = self.live.post('/live/auth/password/', {'identifier': user.email, 'password': 'StrongPass123'}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/live/')
        self.assertEqual(self.live.get('/live/', secure=True).status_code, 200)

    def test_login_page_uses_live_template(self):
        response = self.live.get('/live/auth/password/', secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PostGIS Live')
        self.assertTemplateUsed(response, 'live/auth.html')

    def test_main_login_template_unchanged(self):
        response = Client(HTTP_HOST='postgis.ir').get(reverse('accounts:login_password'), secure=True)
        self.assertTemplateUsed(response, 'accounts/login_password.html')

    def test_external_next_cannot_redirect(self):
        user = User.objects.create_user('09121234568', password='StrongPass123', email='next@example.com')
        response = self.live.post('/live/auth/password/', {'identifier': user.email, 'password': 'StrongPass123', 'next': 'https://evil.example/'}, secure=True)
        self.assertEqual(response.url, '/live/')

    def test_staff_cannot_use_direct_live(self):
        user = User.objects.create_user('09121234569', password='StrongPass123', email='staff@example.com', is_staff=True)
        response = self.live.post('/live/auth/password/', {'identifier': user.email, 'password': 'StrongPass123'}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.live.session)

    def test_password_change_invalidates_direct_live(self):
        user = User.objects.create_user('09121234560', password='StrongPass123', email='change@example.com')
        self.live.post('/live/auth/password/', {'identifier': user.email, 'password': 'StrongPass123'}, secure=True)
        user.set_password('ChangedPass123')
        user.save()
        self.assertIn('/live/auth/login/', self.live.get('/live/', secure=True).url)

    def test_email_links_use_fixed_live_origin_only_when_requested(self):
        from unittest.mock import patch

        from accounts import emailverify
        user = User.objects.create_user('09121234561', password='StrongPass123', email='mail@example.com')
        with patch('accounts.emailverify.mail.send') as send:
            emailverify.send_verification(user, force=True, live=True)
            self.assertTrue(send.call_args.kwargs['context']['url'].startswith('https://live.postgis.ir/live/auth/email/confirm/'))
            emailverify.send_verification(user, force=True)
            self.assertTrue(send.call_args.kwargs['context']['url'].startswith('https://postgis.ir/accounts/email/confirm/'))
            emailverify.send_reset(user.email, live=True)
            self.assertTrue(send.call_args.kwargs['context']['url'].startswith('https://live.postgis.ir/live/auth/password/reset/'))

    def test_existing_sso_session_cannot_be_upgraded_to_direct_by_auth_page(self):
        user = User.objects.create_user('09121234562', password='StrongPass123')
        self.live.force_login(user)
        session = self.live.session
        session['live_parent_session'] = 'parent-placeholder'
        session.save()
        self.live.get('/live/auth/password/', secure=True)
        self.assertNotIn('live_direct_session', self.live.session)

    def test_password_post_requires_csrf(self):
        client = Client(HTTP_HOST='live.postgis.ir', enforce_csrf_checks=True)
        response = client.post('/live/auth/password/', {'identifier': 'nobody@example.com', 'password': 'invalid'}, secure=True)
        self.assertEqual(response.status_code, 403)

    def test_disabled_direct_account_is_rejected(self):
        user = User.objects.create_user('09121234563', password='StrongPass123', email='disabled@example.com')
        self.live.post('/live/auth/password/', {'identifier': user.email, 'password': 'StrongPass123'}, secure=True)
        user.is_active = False
        user.save(update_fields=['is_active'])
        self.assertIn('/live/auth/login/', self.live.get('/live/', secure=True).url)

    def test_switching_auth_method_preserves_safe_project_destination(self):
        response = self.live.get('/live/auth/login/?next=/live/12/34/', secure=True)
        self.assertContains(response, 'next=/live/12/34/')

    def test_signup_requires_terms_and_uses_existing_account_workflow(self):
        from unittest.mock import patch
        payload = {'email': 'signup@example.com', 'full_name': 'کاربر آزمایشی', 'password': 'UniqueSafePass123!'}
        with patch('accounts.emailverify.mail.send'):
            response = self.live.post('/live/auth/signup/', payload, secure=True)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(User.objects.filter(email=payload['email']).exists())
            response = self.live.post('/live/auth/signup/', {**payload, 'accept_terms': 'on'}, secure=True)
        self.assertEqual(response.url, '/live/')
        self.assertTrue(self.live.session.get('live_direct_session'))

    def test_mobile_new_user_verify_requires_terms(self):
        from unittest.mock import patch
        session = self.live.session
        session['otp_phone'] = '09121234564'
        session.save()
        with patch('accounts.views.otp.verify_code', return_value=(True, '')):
            response = self.live.post('/live/auth/verify/', {'code': '123456', 'full_name': 'کاربر'}, secure=True)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(User.objects.filter(phone='09121234564').exists())
            response = self.live.post('/live/auth/verify/', {'code': '123456', 'full_name': 'کاربر', 'accept_terms': 'on'}, secure=True)
        self.assertEqual(response.url, '/live/')

    def test_reset_token_is_single_use_and_expires(self):
        from datetime import timedelta
        from unittest.mock import patch

        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        user = User.objects.create_user('09121234565', password='StrongPass123', email='reset@example.com')
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        url = reverse('live:auth_password_reset', args=[uid, token])
        self.assertEqual(self.live.get(url, secure=True).status_code, 200)
        with patch('accounts.emailverify.mail.send'):
            response = self.live.post(url, {'new_password1': 'DifferentSafePass987!', 'new_password2': 'DifferentSafePass987!'}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.live.get(url, secure=True).status_code, 400)
        user.refresh_from_db()
        token = default_token_generator.make_token(user)
        with override_settings(PASSWORD_RESET_TIMEOUT=1), patch.object(default_token_generator, '_now', return_value=default_token_generator._now() + timedelta(seconds=5)):
            self.assertEqual(self.live.get(reverse('live:auth_password_reset', args=[uid, token]), secure=True).status_code, 400)
