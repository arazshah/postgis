import time
from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings

from accounts import admin_2fa, totp
from accounts.models import AdminTOTP, User
from kernel import stepup

PASS = "Str0ng-Admin-Pass"


class TotpTests(TestCase):
    # بردارهای RFC 6238 (SHA1، کلید ASCII «12345678901234567890»)
    SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

    def test_rfc_vectors(self):
        for t, code in [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"), (2000000000, "279037")]:
            self.assertEqual(totp.code_at(self.SECRET, t), code)

    def test_window_and_replay(self):
        now = 1111111109
        code = totp.code_at(self.SECRET, now)
        step = totp.verify(self.SECRET, code, 0, now + 30)  # یک گام دیرتر هنوز می‌خورد
        self.assertIsNotNone(step)
        self.assertIsNone(totp.verify(self.SECRET, code, step, now))  # بازپخش رد می‌شود
        self.assertIsNone(totp.verify(self.SECRET, code, 0, now + 300))  # بیرون پنجره
        self.assertIsNone(totp.verify(self.SECRET, "abc123", 0, now))


@override_settings(ADMIN_2FA_REQUIRED=True)
class Admin2FATests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_admin("root", PASS)
        self.client.force_login(self.admin)

    def _enroll(self):
        self.client.get("/manage/2fa/")
        rec = AdminTOTP.objects.get(user=self.admin)
        r = self.client.post("/manage/2fa/", {"code": totp.code_at(rec.secret)})
        return rec, r

    def test_redirects_until_verified(self):
        r = self.client.get("/manage/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/manage/2fa/"))

    def test_login_and_logout_exempt(self):
        self.client.logout()
        self.assertEqual(self.client.get("/manage/login/").status_code, 200)

    def test_enroll_flow(self):
        r = self.client.get("/manage/2fa/")
        self.assertContains(r, "otpauth://")
        rec, r = self._enroll()
        self.assertContains(r, "-")  # کدهای بازیابی یک‌بار نشان داده می‌شوند
        rec.refresh_from_db()
        self.assertIsNotNone(rec.confirmed_at)
        self.assertEqual(len(rec.recovery_hashes), 8)
        self.assertEqual(self.client.get("/manage/").status_code, 200)

    def test_wrong_code_does_not_enroll(self):
        self.client.get("/manage/2fa/")
        self.client.post("/manage/2fa/", {"code": "000000"})
        self.assertIsNone(AdminTOTP.objects.get(user=self.admin).confirmed_at)
        self.assertEqual(self.client.get("/manage/").status_code, 302)

    def _enrolled_new_session(self):
        rec, _ = self._enroll()
        self.client.logout()
        self.client.force_login(self.admin)
        return rec

    def test_verify_with_totp_replay_rejected(self):
        rec = self._enrolled_new_session()
        self.assertEqual(self.client.get("/manage/").status_code, 302)
        # رمز همان گام ثبت‌نام بازپخش‌شده رد می‌شود
        self.client.post("/manage/2fa/", {"code": totp.code_at(rec.secret)})
        self.assertEqual(self.client.get("/manage/").status_code, 302)
        rec.refresh_from_db()
        rec.last_step -= 5  # شبیه گام بعدی
        rec.save()
        r = self.client.post("/manage/2fa/", {"code": totp.code_at(rec.secret), "next": "/manage/"})
        self.assertRedirects(r, "/manage/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/manage/").status_code, 200)

    def test_recovery_code_single_use(self):
        rec, r = self._enroll()
        # کدها را مستقیم می‌سازیم تا نیازی به خواندن HTML نباشد
        codes = totp.new_recovery_codes()
        rec.refresh_from_db()
        rec.recovery_hashes = [totp.recovery_hash(c) for c in codes]
        rec.save()
        self.client.logout()
        self.client.force_login(self.admin)
        r = self.client.post("/manage/2fa/", {"code": codes[0], "next": "/manage/"})
        self.assertRedirects(r, "/manage/", fetch_redirect_response=False)
        rec.refresh_from_db()
        self.assertEqual(len(rec.recovery_hashes), 7)
        self.client.logout()
        self.client.force_login(self.admin)
        self.client.post("/manage/2fa/", {"code": codes[0]})
        self.assertEqual(self.client.get("/manage/").status_code, 302)

    def test_lockout_after_five_failures(self):
        rec = self._enrolled_new_session()
        for _ in range(5):
            self.client.post("/manage/2fa/", {"code": "111111"})
        rec.refresh_from_db()
        rec.last_step = 0
        rec.save()
        self.client.post("/manage/2fa/", {"code": totp.code_at(rec.secret)})  # درست ولی قفل
        self.assertEqual(self.client.get("/manage/").status_code, 302)

    def test_next_is_restricted_to_manage(self):
        rec = self._enrolled_new_session()
        rec.refresh_from_db()
        rec.last_step = 0
        rec.save()
        r = self.client.post("/manage/2fa/", {"code": totp.code_at(rec.secret), "next": "https://evil.example/x"})
        self.assertRedirects(r, "/manage/", fetch_redirect_response=False)
        AdminTOTP.objects.filter(pk=rec.pk).update(last_step=0)
        self.client.logout()
        self.client.force_login(self.admin)
        r = self.client.post("/manage/2fa/", {"code": totp.code_at(rec.secret), "next": "/dashboard/"})
        self.assertRedirects(r, "/manage/", fetch_redirect_response=False)

    def test_session_expires_after_max_age(self):
        self._enroll()
        self.assertEqual(self.client.get("/manage/").status_code, 200)
        s = self.client.session
        s["admin_2fa"] = {"uid": self.admin.pk, "at": time.time() - 13 * 3600}
        s.save()
        self.assertEqual(self.client.get("/manage/").status_code, 302)

    def test_other_users_verification_not_reused(self):
        self._enroll()
        other = User.objects.create_admin("other", PASS)
        s = self.client.session
        s["admin_2fa"] = {"uid": other.pk, "at": time.time()}
        s.save()
        self.assertEqual(self.client.get("/manage/").status_code, 302)

    def test_stepup_provider_needs_fresh(self):
        self._enroll()
        req = self.client.get("/manage/").wsgi_request
        self.assertTrue(stepup.ok(req))
        s = self.client.session
        s["admin_2fa"] = {"uid": self.admin.pk, "at": time.time() - 3600}
        s.save()
        self.assertEqual(self.client.get("/manage/").status_code, 200)  # هنوز در سقف ۱۲ ساعت
        req = self.client.get("/manage/").wsgi_request
        self.assertFalse(stepup.ok(req))
        self.assertIn("/manage/2fa/", stepup.url(req))

    def test_site_user_unaffected(self):
        u = User.objects.create_user("09121234567", full_name="کاربر")
        self.client.force_login(u)
        self.assertNotIn("/manage/2fa/", self.client.get("/dashboard/")["Location"] if self.client.get("/dashboard/").status_code == 302 else "")

    def test_reset_command_and_action(self):
        self._enroll()
        out = StringIO()
        call_command("admin_2fa_reset", "root", stdout=out)
        self.assertFalse(AdminTOTP.objects.filter(user=self.admin).exists())


class Admin2FAOffTests(TestCase):
    @override_settings(ADMIN_2FA_REQUIRED=False)
    def test_off_means_no_redirect(self):
        admin = User.objects.create_admin("root", PASS)
        self.client.force_login(admin)
        self.assertEqual(self.client.get("/manage/").status_code, 200)
        self.assertTrue(admin_2fa.verified(self.client.get("/manage/").wsgi_request))
