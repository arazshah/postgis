from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from core.models import SiteSettings


class EmailAccountTests(TestCase):
    def setUp(self):
        SiteSettings.get()
        cache.clear()

    def signup(self, **over):
        data = {"full_name": "احمد", "email": "Ahmad@Example.com", "password": "Zx9-secure-pass",
                "accept_terms": "on", **over}
        return self.client.post(reverse("accounts:signup_email"), data)

    def test_signup_logs_in_without_verification(self):
        r = self.signup()
        self.assertRedirects(r, reverse("databases:create"), fetch_redirect_response=False)
        u = User.objects.get(email="ahmad@example.com")
        self.assertIsNone(u.phone)
        self.assertTrue(u.check_password("Zx9-secure-pass"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), u.pk)

    def test_duplicate_weak_and_terms(self):
        self.signup()
        self.client.logout()
        self.assertEqual(self.signup().status_code, 200)  # ایمیل تکراری
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(self.signup(email="b@example.com", password="12345678").status_code, 200)
        self.assertEqual(self.signup(email="c@example.com", accept_terms="").status_code, 200)
        self.assertEqual(self.signup(email="bad").status_code, 200)
        self.assertEqual(User.objects.count(), 1)

    def test_signup_closed(self):
        SiteSettings.objects.update(signup_open=False)
        cache.clear()
        self.assertEqual(self.signup().status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_password_login(self):
        self.signup()
        self.client.logout()
        url = reverse("accounts:login_password")
        r = self.client.post(url, {"identifier": "AHMAD@example.com", "password": "bad"})
        self.assertContains(r, "اشتباه است")
        r = self.client.post(url, {"identifier": "ahmad@example.com", "password": "Zx9-secure-pass"})
        self.assertRedirects(r, reverse("databases:dashboard"), fetch_redirect_response=False)

    def test_lockout(self):
        self.signup()
        self.client.logout()
        url = reverse("accounts:login_password")
        for _ in range(8):
            self.client.post(url, {"identifier": "ahmad@example.com", "password": "bad"})
        r = self.client.post(url, {"identifier": "ahmad@example.com", "password": "Zx9-secure-pass"})
        self.assertContains(r, "قفل")

    def test_staff_and_otp_only_users_cannot_password_login(self):
        User.objects.create_admin("boss", "Zx9-secure-pass")
        User.objects.create_user("09121234567")
        url = reverse("accounts:login_password")
        for ident in ("boss", "09121234567"):
            r = self.client.post(url, {"identifier": ident, "password": "Zx9-secure-pass"})
            self.assertContains(r, "اشتباه است")

    def test_mobile_user_can_set_password_and_login_with_phone(self):
        u = User.objects.create_user("09121234567", full_name="x")
        self.client.force_login(u)
        r = self.client.post(reverse("accounts:profile"), {
            "action": "password", "new_password1": "Zx9-secure-pass", "new_password2": "Zx9-secure-pass"})
        self.assertEqual(r.status_code, 302)
        self.client.logout()
        r = self.client.post(reverse("accounts:login_password"),
                             {"identifier": "0912 123 4567", "password": "Zx9-secure-pass"})
        self.assertEqual(r.status_code, 302)

    def test_email_user_cannot_clear_email(self):
        self.signup()
        r = self.client.post(reverse("accounts:profile"), {"action": "profile", "full_name": "a", "email": ""})
        self.assertContains(r, "نمی‌تواند خالی باشد")
