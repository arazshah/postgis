"""ایمیل سکو: صف، سیاست دسته/تأیید/رضایت، سقف روزانه، تلاش دوباره، تکرارگیری و امنیت رمز SMTP."""
import datetime
import smtplib
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail as djmail
from django.test import TestCase, override_settings
from django.utils import timezone

from kernel import mail
from kernel.models import MailConfig, OutgoingEmail

U = get_user_model()
S = OutgoingEmail.Status


class MailTests(TestCase):
    def setUp(self):
        self.user = U.objects.create_user(None, password="x", email="a@example.com", full_name="الف")

    def verified(self):
        self.user.email_verified_at = timezone.now()
        self.user.save()

    def test_unverified_gets_only_security(self):
        row = mail.send("welcome", user=self.user)
        self.assertEqual((row.status, row.error), (S.SKIPPED, "unverified"))
        row = mail.send("verify_email", user=self.user, context={"url": "https://x/y"})
        self.assertEqual(row.status, S.QUEUED)

    def test_queue_then_tick_sends_html_and_text(self):
        self.verified()
        mail.send("welcome", user=self.user, context={"start_url": "https://x/start"})
        self.assertEqual(len(djmail.outbox), 0)  # صف؛ درخواست منتظر SMTP نمی‌ماند
        self.assertEqual(mail.tick()["sent"], 1)
        m = djmail.outbox[0]
        self.assertEqual(m.to, ["a@example.com"])
        self.assertIn("https://x/start", m.body)
        self.assertEqual(m.alternatives[0][1], "text/html")
        self.assertIn('dir="rtl"', m.alternatives[0][0])
        self.assertEqual(m.extra_headers.get("Auto-Submitted"), "auto-generated")

    def test_urgent_sends_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            mail.send("verify_email", user=self.user, context={"url": "https://x/y"}, urgent=True)
        self.assertEqual(len(djmail.outbox), 1)

    def test_dedupe_by_key(self):
        self.verified()
        self.assertIsNotNone(mail.send("welcome", user=self.user, key="k", context={"start_url": "u"}))
        self.assertIsNone(mail.send("welcome", user=self.user, key="k", context={"start_url": "u"}))

    def test_marketing_needs_consent(self):
        mail.register("t_mk", plugin="kernel", category=mail.MARKETING, subject="s", template="mail/test.html")
        self.verified()
        self.assertEqual(mail.send("t_mk", user=self.user).error, "no-consent")
        mail.set_consent_provider(lambda u: True)
        self.addCleanup(mail.set_consent_provider, None)
        row = mail.send("t_mk", user=self.user)
        self.assertEqual(row.status, S.QUEUED)
        self.assertEqual(row.headers["Precedence"], "bulk")

    def test_daily_cap_reserves_for_security(self):
        self.verified()
        MailConfig.objects.create(daily_limit=25)
        for _ in range(5):
            OutgoingEmail.objects.create(to="z@example.com", template="x", category="service", subject="s",
                                         status=S.SENT, sent_at=timezone.now())
        row = mail.send("welcome", user=self.user, context={"start_url": "u"})
        self.assertFalse(mail.deliver(row.pk))  # ۵ از ۲۵-۲۰
        self.assertEqual(len(djmail.outbox), 0)
        sec = mail.send("verify_email", user=self.user, context={"url": "u"})
        self.assertTrue(mail.deliver(sec.pk))

    def test_retry_backoff_then_fail(self):
        row = mail.send("verify_email", user=self.user, context={"url": "u"})
        now = timezone.now()
        with mock.patch.object(mail, "_connection", side_effect=smtplib.SMTPServerDisconnected("secret-host")):
            for i in range(mail.MAX_ATTEMPTS):
                mail.deliver(row.pk, now)
                row.refresh_from_db()
                if i < mail.MAX_ATTEMPTS - 1:
                    self.assertEqual(row.status, S.QUEUED)
                    self.assertGreater(row.next_try, now)
        self.assertEqual(row.status, S.FAILED)
        self.assertNotIn("secret-host", row.error)

    def test_auth_failure_is_fatal_and_hides_secrets(self):
        row = mail.send("verify_email", user=self.user, context={"url": "u"})
        with mock.patch.object(mail, "_connection", side_effect=smtplib.SMTPAuthenticationError(535, b"bad pass hunter2")):
            mail.deliver(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, S.FAILED)
        self.assertNotIn("hunter2", row.error)

    def test_password_is_encrypted_and_blank_keeps_it(self):
        cfg = mail.save_config(enabled=True, host="h", port=587, security="starttls", username="u", password="hunter2")
        self.assertTrue(cfg.enabled)
        self.assertNotIn("hunter2", cfg.password_enc)
        enc = cfg.password_enc
        cfg = mail.save_config(enabled=True, host="h", port=587, security="starttls", username="u", password="")
        self.assertEqual(cfg.password_enc, enc)
        self.assertFalse(mail.save_config(enabled=True, host="h", port=587, security="starttls", username="u").enabled is False)

    def test_not_enabled_without_password(self):
        cfg = mail.save_config(enabled=True, host="h", port=587, security="starttls", username="u")
        self.assertFalse(cfg.enabled)

    @override_settings(DEFAULT_FROM_EMAIL="d@example.com")
    def test_from_and_reply_to_from_config(self):
        mail.save_config(enabled=False, host="h", port=587, security="starttls", username="u",
                         from_name="ژئوپایگاه", from_email="no-reply@postgis.ir", reply_to="support@postgis.ir")
        row = mail.send("verify_email", user=self.user, context={"url": "u"})
        mail.deliver(row.pk)
        m = djmail.outbox[0]
        self.assertIn("no-reply@postgis.ir", m.from_email)
        self.assertEqual(m.extra_headers["Reply-To"], "support@postgis.ir")

    def test_old_ledger_is_purged(self):
        old = OutgoingEmail.objects.create(to="o@example.com", template="x", category="service", subject="s")
        OutgoingEmail.objects.filter(pk=old.pk).update(created_at=timezone.now() - datetime.timedelta(days=mail.KEEP_DAYS + 1))
        mail.tick()
        self.assertFalse(OutgoingEmail.objects.filter(pk=old.pk).exists())

    def test_to_text_keeps_links(self):
        self.assertIn("متن (https://a.b/c)", mail.to_text('<p>سلام</p><a href="https://a.b/c">متن</a>'))
