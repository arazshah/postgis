import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts import bale, sms
from accounts import otp as otp_mod
from accounts.models import OTPCode, User
from core.models import SiteSettings


class FakeResp:
    def __init__(self, status, body):
        self.status, self._b = status, json.dumps(body).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class BaleTests(TestCase):
    def setUp(self):
        cache.clear()
        conf = SiteSettings.get()
        conf.bale_enabled = True
        conf.bale_client_id = "cid"
        conf.set_bale_client_secret("csecret")
        conf.save()
        self.requests = []
        self.sent = {}
        self.token_calls = 0

        def opener(req, timeout=None):
            self.requests.append(req)
            if req.full_url.endswith("/auth/token"):
                self.token_calls += 1
                return FakeResp(200, {"access_token": f"tok{self.token_calls}", "expires_in": 3600})
            body = json.loads(req.data)
            self.sent[body["phone"]] = body["otp"]
            return FakeResp(200, {"message": "ok"})

        p = mock.patch("urllib.request.urlopen", opener)
        p.start()
        self.addCleanup(p.stop)

    def test_api_format(self):
        bale.send_otp("09121234567", "40213")
        tok, send = self.requests
        self.assertEqual(tok.full_url, "https://safir.bale.ai/api/v2/auth/token")
        self.assertIn(b"grant_type=client_credentials", tok.data)
        self.assertIn(b"client_secret=csecret", tok.data)
        self.assertEqual(send.full_url, "https://safir.bale.ai/api/v2/send_otp")
        self.assertEqual(send.get_header("Authorization"), "Bearer tok1")
        self.assertEqual(json.loads(send.data), {"phone": "989121234567", "otp": 40213})
        bale.send_otp("09121234567", "50213")
        self.assertEqual(self.token_calls, 1)  # توکن کش شده است

    def test_codes_never_start_with_zero(self):
        conf = SiteSettings.get()
        for _ in range(300):
            _, code = OTPCode.issue("09120000000", None, conf)
            self.assertNotEqual(code[0], "0")
            self.assertEqual(len(code), conf.otp_length)

    def test_auto_fallback_when_sms_fails(self):
        def boom(phone, code):
            raise sms.SMSError("down")

        with mock.patch.object(otp_mod, "send_otp", boom):
            r = self.client.post(reverse("accounts:login"), {"phone": "09121234567"})
        self.assertRedirects(r, reverse("accounts:verify"))
        otp = OTPCode.objects.get()
        self.assertEqual((otp.channel, otp.sent_ok), ("bale", True))
        page = self.client.get(reverse("accounts:verify"))
        self.assertContains(page, "پیام‌رسان <b>بله</b>")
        code = str(self.sent["989121234567"])
        r = self.client.post(reverse("accounts:verify"), {"code": code, "full_name": "علی", "accept_terms": "on"})
        self.assertTrue(User.objects.filter(phone="09121234567").exists())

    def test_fallback_disabled(self):
        SiteSettings.objects.update(bale_fallback=False)
        with mock.patch.object(otp_mod, "send_otp", mock.Mock(side_effect=sms.SMSError("down"))):
            r = self.client.post(reverse("accounts:login"), {"phone": "09121234567"})
        self.assertContains(r, "ارسال پیامک ممکن نشد")
        self.assertEqual(self.sent, {})

    def test_user_requests_bale_without_waiting_once(self):
        with mock.patch.object(otp_mod, "send_otp", mock.Mock()):
            self.client.post(reverse("accounts:login"), {"phone": "09121234567"})
        self.assertContains(self.client.get(reverse("accounts:verify")), "کد را در پیام‌رسان بله بفرست")
        r = self.client.post(reverse("accounts:resend"), {"channel": "bale"}, follow=True)
        self.assertContains(r, "در پیام‌رسان بله فرستادیم")
        self.assertIn("989121234567", self.sent)
        self.assertEqual(OTPCode.objects.filter(channel="bale").count(), 1)
        # درخواست دوباره بله بلافاصله مجاز نیست
        r = self.client.post(reverse("accounts:resend"), {"channel": "bale"}, follow=True)
        self.assertContains(r, "ثانیه صبر کنید")
        self.assertEqual(OTPCode.objects.count(), 2)

    def test_button_hidden_when_disabled(self):
        SiteSettings.objects.update(bale_enabled=False)
        with mock.patch.object(otp_mod, "send_otp", mock.Mock()):
            self.client.post(reverse("accounts:login"), {"phone": "09121234567"})
        self.assertNotContains(self.client.get(reverse("accounts:verify")), "در پیام‌رسان بله بفرست")
        r = self.client.post(reverse("accounts:resend"), {"channel": "bale"}, follow=True)
        self.assertContains(r, "فعال نیست")

    def test_expired_token_is_refreshed(self):
        calls = {"n": 0}

        def opener(req, timeout=None):
            if req.full_url.endswith("/auth/token"):
                calls["n"] += 1
                return FakeResp(200, {"access_token": f"t{calls['n']}", "expires_in": 3600})
            if req.get_header("Authorization") == "Bearer t1":
                import io
                import urllib.error
                raise urllib.error.HTTPError(req.full_url, 401, "x", {}, io.BytesIO(b"{}"))
            return FakeResp(200, {})

        with mock.patch("urllib.request.urlopen", opener):
            bale.send_otp("09121234567", "12345")
        self.assertEqual(calls["n"], 2)
