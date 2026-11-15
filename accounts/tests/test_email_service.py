"""تأیید ایمیل، بازنشانی رمز با ایمیل و اعلان‌های امنیتی حساب."""
import re

from django.contrib.auth import get_user_model
from django.core import mail as djmail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts import emailverify
from kernel import mail

U = get_user_model()
SIGNUP = {"full_name": "علی رضایی", "email": "ali@example.com", "password": "Str0ng-pass-99", "accept_terms": "on"}


def link(message, name):
    return re.search(rf"https?://[^\s)]*{name}[^\s)]*", message.body).group(0)


class EmailVerifyTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_signup_sends_verification_and_confirm_welcomes(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse("accounts:signup_email"), SIGNUP)
        self.assertEqual(r.status_code, 302)
        user = U.objects.get(email="ali@example.com")
        self.assertIsNone(user.email_verified_at)
        self.assertEqual(len(djmail.outbox), 1)
        url = link(djmail.outbox[0], "email/confirm")
        self.client.get(url.replace("https://postgis.ir", "").replace("http://testserver", ""))
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)
        mail.tick()
        self.assertEqual(len(djmail.outbox), 2)  # خوش‌آمد بعد از تأیید

    def test_token_dies_when_email_changes_and_when_bad(self):
        user = U.objects.create_user(None, password="x", email="a@example.com")
        token = emailverify.make_token(user)
        user.email = "b@example.com"
        user.save()
        self.assertIsNone(emailverify.confirm(token))
        self.assertIsNone(emailverify.confirm("garbage"))

    def test_changing_profile_email_resets_verification_and_warns_old(self):
        user = U.objects.create_user(None, password="x", email="old@example.com", full_name="الف")
        user.email_verified_at = user.date_joined
        user.save()
        self.client.force_login(user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("accounts:profile"), {"action": "profile", "full_name": "الف", "email": "new@example.com", "organization": ""})
        user.refresh_from_db()
        self.assertEqual(user.email, "new@example.com")
        self.assertIsNone(user.email_verified_at)
        self.assertEqual(sorted(m.to[0] for m in djmail.outbox), ["new@example.com", "old@example.com"])

    def test_resend_is_rate_limited(self):
        user = U.objects.create_user(None, password="x", email="a@example.com")
        self.client.force_login(user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("accounts:email_resend"))
            self.client.post(reverse("accounts:email_resend"))
        self.assertEqual(len(djmail.outbox), 1)


class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = U.objects.create_user(None, password="Old-pass-123", email="ali@example.com")

    def ask(self, email):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("accounts:password_forgot"), {"email": email})

    def test_unknown_email_gets_same_answer_and_no_mail(self):
        a, b = self.ask("ali@example.com"), self.ask("nobody@example.com")
        self.assertEqual(a.status_code, b.status_code)
        self.assertContains(b, "اگر حسابی با این ایمیل باشد")
        self.assertEqual([m.to[0] for m in djmail.outbox], ["ali@example.com"])

    def test_full_flow_verifies_email_and_is_single_use(self):
        self.ask("ali@example.com")
        path = re.search(r"/accounts/password/reset/[^\s)]+", djmail.outbox[0].body).group(0)
        self.assertEqual(self.client.get(path).status_code, 200)
        r = self.client.post(path, {"new_password1": "Brand-new-pass-77", "new_password2": "Brand-new-pass-77"})
        self.assertEqual(r.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Brand-new-pass-77"))
        self.assertIsNotNone(self.user.email_verified_at)
        self.assertEqual(self.client.get(path).status_code, 400)  # یک‌بار مصرف

    def test_staff_cannot_reset_by_email(self):
        U.objects.create_user(username="boss", password="x", email="boss@example.com", is_staff=True)
        self.ask("boss@example.com")
        self.assertEqual(len(djmail.outbox), 0)

    def test_ip_rate_limit(self):
        for i in range(8):
            self.ask(f"u{i}@example.com")
        self.assertEqual(len(djmail.outbox), 0)  # کاربر وجود ندارد ولی سقف هم نشکسته؛ حالا کاربران واقعی:
        cache.clear()
        for i in range(8):
            U.objects.create_user(None, password="x", email=f"r{i}@example.com")
        for i in range(8):
            self.ask(f"r{i}@example.com")
        self.assertEqual(len(djmail.outbox), 5)
