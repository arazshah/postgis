"""فاز ۳ ایمیل: سیاست کانال (ایمیل اول، پیامک فقط فوری/بی‌ایمیل)، ترجیحات، خلاصه‌ی روزانه و خطای کار."""
import datetime
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail as djmail
from django.test import TestCase
from django.utils import timezone

from core import alerts
from core.models import SiteSettings
from databases import services
from kernel import mail, workspace
from kernel.models import DigestItem, NotifyPref, OutgoingEmail

U = get_user_model()


class PolicyTests(TestCase):
    def setUp(self):
        self.user = U.objects.create_user("09120000001", email="a@example.com", full_name="الف")
        self.user.email_verified_at = timezone.now()
        self.user.save()
        p = mock.patch("accounts.sms.send_text")
        self.sms = p.start()
        self.addCleanup(p.stop)
        a = mock.patch.object(mail, "available", return_value=True)
        a.start()
        self.addCleanup(a.stop)

    def notify(self, **kw):
        workspace.notify_user(self.user, "عنوان", "متن", **kw)

    def test_normal_goes_to_email_only(self):
        self.notify()
        self.assertEqual(OutgoingEmail.objects.filter(template="notice", status="queued").count(), 1)
        self.sms.assert_not_called()

    def test_urgent_goes_to_both(self):
        self.notify(urgent=True)
        self.assertEqual(OutgoingEmail.objects.filter(template="notice").count(), 1)
        self.sms.assert_called_once()

    def test_unverified_email_falls_back_to_sms(self):
        self.user.email_verified_at = None
        self.user.save()
        self.notify()
        self.assertEqual(OutgoingEmail.objects.filter(template="notice").count(), 0)
        self.sms.assert_called_once()

    def test_mail_server_not_configured_falls_back_to_sms(self):
        with mock.patch.object(mail, "available", return_value=False):
            self.notify()
        self.assertEqual(OutgoingEmail.objects.count(), 0)
        self.sms.assert_called_once()

    def test_pref_off_falls_back_to_sms(self):
        NotifyPref.objects.create(user=self.user, email_service=False)
        self.notify()
        self.assertEqual(OutgoingEmail.objects.filter(template="notice").count(), 0)
        self.sms.assert_called_once()

    def test_quota_full_is_urgent(self):
        with mock.patch.object(services, "_notify") as n:
            workspace.notify_user(self.user, "حجم پایگاه داده پر شد", "x", urgent=True)
            n.assert_called_once()
            self.assertTrue(n.call_args.kwargs["urgent"])


class DigestTests(TestCase):
    def setUp(self):
        self.user = U.objects.create_user(None, password="x", email="a@example.com")
        self.user.email_verified_at = timezone.now()
        self.user.save()
        NotifyPref.objects.create(user=self.user, email_digest=True)
        a = mock.patch.object(mail, "available", return_value=True)
        a.start()
        self.addCleanup(a.stop)

    def at(self, hour):
        d = timezone.localtime(timezone.now()).replace(hour=hour, minute=5)
        return d

    def test_non_urgent_is_collected_and_sent_once_after_8(self):
        mail.notice(self.user, "یک", "ب1")
        mail.notice(self.user, "دو", "ب2", url="https://x/y")
        self.assertEqual(DigestItem.objects.count(), 2)
        self.assertEqual(OutgoingEmail.objects.count(), 0)
        self.assertEqual(mail.send_digests(self.at(6)), 0)  # قبل از ۸ صبح
        self.assertEqual(mail.send_digests(self.at(9)), 1)
        self.assertEqual(DigestItem.objects.count(), 0)
        mail.tick(timezone.now() + datetime.timedelta(minutes=5))  # next_try ردیف = اکنون واقعی؛ آزمون به ساعت روز وابسته نباشد
        self.assertEqual(len(djmail.outbox), 1)
        body = djmail.outbox[0].body
        self.assertIn("یک", body)
        self.assertIn("دو", body)

    def test_urgent_bypasses_digest(self):
        mail.notice(self.user, "فوری", "x", urgent=True)
        self.assertEqual(DigestItem.objects.count(), 0)
        self.assertEqual(OutgoingEmail.objects.filter(template="notice").count(), 1)

    def test_at_most_one_digest_per_day(self):
        mail.notice(self.user, "الف", "")
        mail.send_digests(self.at(9))
        mail.notice(self.user, "ب", "")
        self.assertEqual(mail.send_digests(self.at(10)), 0)
        self.assertEqual(DigestItem.objects.count(), 1)  # فردا


class AdminAlertTests(TestCase):
    def test_admin_alert_email_goes_through_queue(self):
        s = SiteSettings.get()
        s.support_email = "support@example.com"
        s.save()
        alerts.notify_admins("موضوع", "متن", sms=False)
        row = OutgoingEmail.objects.get(to="support@example.com")
        self.assertEqual(row.status, "queued")
        self.assertIn("موضوع", row.subject)
        mail.tick()
        self.assertEqual(djmail.outbox[0].to, ["support@example.com"])


class JobFailureTests(TestCase):
    def test_failed_job_emails_verified_owner_once(self):
        from jobs.models import Job

        user = U.objects.create_user(None, password="x", email="a@example.com")
        user.email_verified_at = timezone.now()
        user.save()
        from notifications import services as ns

        with mock.patch.object(mail, "available", return_value=True):
            job = Job.objects.create(user=user, kind="x", status=Job.Status.FAILED, message="statement timeout")  # سیگنال
            ns.for_job(job)  # دوباره: اعلان تکراری ساخته نمی‌شود
        self.assertEqual(OutgoingEmail.objects.filter(template="notice").count(), 1)
