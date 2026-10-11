import json
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import otp as otp_mod
from accounts import sms
from accounts.models import OTPCode, User, normalize_mobile
from core.models import SiteSettings


class CaptureCodes:
    """send_otp را جایگزین می‌کند تا کد ارسال‌شده را در تست ببینیم."""

    def __init__(self):
        self.codes = {}

    def __call__(self, phone, code):
        self.codes[phone] = code


class NormalizeTests(TestCase):
    def test_formats(self):
        for raw in ["09121234567", "۰۹۱۲۱۲۳۴۵۶۷", "+989121234567", "00989121234567", "989121234567",
                    "9121234567", "0912 123 4567", "٠٩١٢١٢٣٤٥٦٧"]:
            self.assertEqual(normalize_mobile(raw), "09121234567", raw)

    def test_invalid(self):
        for raw in ["", "0912", "08121234567", "abc", "091212345678"]:
            with self.assertRaises(ValidationError, msg=raw):
                normalize_mobile(raw)


class OTPFlowTests(TestCase):
    def setUp(self):
        SiteSettings.get()
        self.cap = CaptureCodes()
        p = mock.patch.object(otp_mod, "send_otp", self.cap)
        p.start()
        self.addCleanup(p.stop)

    def start(self, phone="09121234567"):
        return self.client.post(reverse("accounts:login"), {"phone": phone})

    def test_new_user_signup(self):
        r = self.start("+98 912 123 4567")
        self.assertRedirects(r, reverse("accounts:verify"))
        page = self.client.get(reverse("accounts:verify")).content.decode()
        self.assertIn("ساخت حساب", page)
        code = self.cap.codes["09121234567"]
        # بدون نام و پذیرش قوانین ساخته نمی‌شود
        r = self.client.post(reverse("accounts:verify"), {"code": code})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.exists())
        # کد مصرف نشده چون فرم نامعتبر بود؛ دوباره با اطلاعات کامل
        r = self.client.post(reverse("accounts:verify"), {"code": code, "full_name": "علی", "accept_terms": "on"})
        self.assertRedirects(r, reverse("databases:create"), fetch_redirect_response=False)
        user = User.objects.get()
        self.assertEqual(user.phone, "09121234567")
        self.assertFalse(user.has_usable_password())
        self.assertIsNotNone(user.phone_verified_at)

    def test_existing_user_login_and_next(self):
        User.objects.create_user("09121234567", full_name="علی")
        self.client.post(reverse("accounts:login"), {"phone": "09121234567", "next": "/docs/"})
        code = self.cap.codes["09121234567"]
        r = self.client.post(reverse("accounts:verify"), {"code": code})
        self.assertRedirects(r, "/docs/", fetch_redirect_response=False)

    def test_unsafe_next_ignored(self):
        User.objects.create_user("09121234567")
        self.client.post(reverse("accounts:login"), {"phone": "09121234567", "next": "https://evil.example/"})
        r = self.client.post(reverse("accounts:verify"), {"code": self.cap.codes["09121234567"]})
        self.assertRedirects(r, reverse("databases:dashboard"), fetch_redirect_response=False)

    def test_wrong_code_attempts_exhaust(self):
        User.objects.create_user("09121234567")
        self.start()
        good = self.cap.codes["09121234567"]
        bad = "00000" if good != "00000" else "11111"
        for _ in range(5):
            self.client.post(reverse("accounts:verify"), {"code": bad})
        r = self.client.post(reverse("accounts:verify"), {"code": good})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_code_single_use_and_expiry(self):
        User.objects.create_user("09121234567")
        self.start()
        code = self.cap.codes["09121234567"]
        OTPCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        r = self.client.post(reverse("accounts:verify"), {"code": code})
        self.assertContains(r, "منقضی")

    def test_resend_cooldown_and_hourly_limit(self):
        self.start()
        self.start()
        self.assertEqual(OTPCode.objects.count(), 1)  # در دوره انتظار کد جدید صادر نمی‌شود
        for _ in range(10):
            OTPCode.objects.update(created_at=timezone.now() - timedelta(minutes=2))
            self.start()
        self.assertEqual(OTPCode.objects.count(), 5)  # سقف ساعتی

    def test_ip_limit(self):
        SiteSettings.objects.filter(pk=1).update(otp_max_per_ip_hour=2, otp_resend_seconds=0)
        for i in range(4):
            self.client.post(reverse("accounts:login"), {"phone": f"0912000000{i}"}, REMOTE_ADDR="5.5.5.5")
        self.assertEqual(OTPCode.objects.count(), 2)

    def test_client_ip_behind_proxy(self):
        req = mock.Mock(META={"HTTP_X_FORWARDED_FOR": "1.1.1.1, 2.2.2.2", "REMOTE_ADDR": "10.0.0.1"})
        self.assertEqual(otp_mod.client_ip(req), "2.2.2.2")  # مقدار ساختگی کاربر (1.1.1.1) نادیده گرفته می‌شود

    def test_sms_failure_message(self):
        def boom(phone, code):
            raise sms.SMSError("down")
        with mock.patch.object(otp_mod, "send_otp", boom):
            r = self.start()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ارسال پیامک ممکن نشد")
        self.assertFalse(OTPCode.objects.get().sent_ok)

    def test_signup_closed(self):
        SiteSettings.objects.filter(pk=1).update(signup_open=False)
        r = self.start()
        self.assertContains(r, "ثبت‌نام کاربر جدید فعلاً بسته است")
        self.assertFalse(OTPCode.objects.exists())  # پیامک هدر نمی‌رود
        User.objects.create_user("09121234567")
        self.assertRedirects(self.start(), reverse("accounts:verify"))  # کاربر قبلی هنوز وارد می‌شود

    def test_code_not_stored_plain(self):
        self.start()
        code = self.cap.codes["09121234567"]
        self.assertNotIn(code, OTPCode.objects.get().code_hash)


class SmsIrTests(TestCase):
    def setUp(self):
        conf = SiteSettings.get()
        conf.sms_backend = "smsir"
        conf.smsir_template_id = "456789"
        conf.smsir_code_param = "CODE"
        conf.set_smsir_api_key("k123")
        conf.save()

    def fake_urlopen(self, status=1):
        captured = {}

        class Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return json.dumps({"status": status, "message": "ok", "data": {"messageId": 1}}).encode()

        def opener(req, timeout=None):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode())
            return Resp()
        return opener, captured

    def test_verify_payload(self):
        opener, cap = self.fake_urlopen()
        with mock.patch("urllib.request.urlopen", opener):
            sms.send_otp("09121234567", "12345")
        self.assertEqual(cap["url"], "https://api.sms.ir/v1/send/verify")
        self.assertEqual(cap["headers"]["X-api-key"], "k123")
        self.assertEqual(cap["body"], {"mobile": "9121234567", "templateId": 456789,
                                       "parameters": [{"name": "CODE", "value": "12345"}]})

    def test_error_status(self):
        opener, _ = self.fake_urlopen(status=0)
        with mock.patch("urllib.request.urlopen", opener), self.assertRaises(sms.SMSError):
            sms.send_otp("09121234567", "12345")

    def test_missing_config(self):
        SiteSettings.objects.filter(pk=1).update(smsir_template_id="")
        with self.assertRaises(sms.SMSError):
            sms.send_otp("09121234567", "12345")
