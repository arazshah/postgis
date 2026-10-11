import os
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import AdminUser, SiteUser, User
from core.models import SiteSettings


class AdminSeparationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_admin("admin", "Str0ng-Admin-Pass")
        self.site_user = User.objects.create_user("09121234567", full_name="کاربر")

    def test_admin_login_with_username_password(self):
        r = self.client.post("/manage/login/?next=/manage/", {"username": "admin", "password": "Str0ng-Admin-Pass"})
        self.assertRedirects(r, "/manage/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/manage/").status_code, 200)

    def test_site_user_cannot_enter_admin(self):
        self.client.force_login(self.site_user)
        r = self.client.get("/manage/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/manage/login/", r["Location"])
        self.assertFalse(self.site_user.has_usable_password())

    def test_admin_kept_out_of_user_panel(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("databases:dashboard"))
        self.assertRedirects(r, reverse("admin:index"), fetch_redirect_response=False)

    def test_staff_phone_refused_in_otp(self):
        self.admin.phone = "09129999999"
        self.admin.save()
        with mock.patch("accounts.otp.send_otp") as send:
            r = self.client.post(reverse("accounts:login"), {"phone": "09129999999"})
        self.assertContains(r, "حساب مدیریتی")
        send.assert_not_called()

    def test_lockout_after_failures(self):
        for _ in range(8):
            self.client.post("/manage/login/", {"username": "admin", "password": "wrong"})
        r = self.client.post("/manage/login/", {"username": "admin", "password": "Str0ng-Admin-Pass"})
        self.assertContains(r, "قفل")

    def test_proxy_lists(self):
        self.assertEqual(list(SiteUser.objects.all()), [self.site_user])
        self.assertEqual(list(AdminUser.objects.all()), [self.admin])

    def test_ensure_superuser_does_not_reset_password(self):
        with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_USERNAME": "owner",
                                          "DJANGO_SUPERUSER_PASSWORD": "First-Pass-123"}):
            call_command("ensure_superuser")
            owner = User.objects.get(username="owner")
            self.assertTrue(owner.is_superuser and owner.is_staff)
            owner.set_password("Changed-Later-456")
            owner.save()
            call_command("ensure_superuser")
        owner.refresh_from_db()
        self.assertTrue(owner.check_password("Changed-Later-456"))


class AdminPagesTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_admin("admin", "Str0ng-Admin-Pass")
        self.client.force_login(self.admin)

    def test_all_admin_pages_load(self):
        urls = ["/manage/", "/manage/core/sitesettings/", "/manage/core/sitesettings/1/change/",
                "/manage/core/sitesettings/test-sms/", "/manage/accounts/siteuser/", "/manage/accounts/adminuser/",
                "/manage/accounts/adminuser/add/", "/manage/accounts/otpcode/", "/manage/databases/plan/",
                "/manage/databases/plan/add/", "/manage/databases/databaseserver/add/",
                "/manage/databases/userdatabase/", "/manage/databases/extension/", "/manage/password_change/"]
        for url in urls:
            r = self.client.get(url, follow=True)
            self.assertEqual(r.status_code, 200, url)

    def test_settings_save_encrypts_api_key_and_applies(self):
        url = "/manage/core/sitesettings/1/change/"
        from django.forms.models import model_to_dict

        data = {k: v for k, v in model_to_dict(SiteSettings.get()).items() if v is not None and v is not False}
        data.update({"site_name": "پستجیس", "sms_backend": "smsir", "smsir_api_key": "SECRET-KEY-1",
                     "smsir_template_id": "100200", "smsir_code_param": "CODE", "announcement_level": "info",
                     "max_databases_per_user": 2, "signup_open": "on", "allow_new_databases": "on"})
        r = self.client.post(url, data)
        self.assertEqual(r.status_code, 302, r.content[:2000])
        conf = SiteSettings.get()
        self.assertEqual(conf.get_smsir_api_key(), "SECRET-KEY-1")
        self.assertNotIn("SECRET-KEY-1", conf.smsir_api_key_encrypted)
        self.assertNotIn("SECRET-KEY-1", self.client.get(url).content.decode())
        self.assertContains(self.client.get("/"), "پستجیس")

    def test_dashboard_warns_about_missing_setup(self):
        r = self.client.get("/manage/")
        self.assertContains(r, "هنوز هیچ سرور دیتابیسی تعریف نشده")

    def test_admin_can_create_another_admin(self):
        r = self.client.post("/manage/accounts/adminuser/add/", {
            "username": "support", "full_name": "پشتیبان", "password1": "Support-Pass-99",
            "password2": "Support-Pass-99"})
        self.assertEqual(r.status_code, 302)
        u = User.objects.get(username="support")
        self.assertTrue(u.is_staff)
        self.assertFalse(u.is_superuser)
        self.assertTrue(u.check_password("Support-Pass-99"))
