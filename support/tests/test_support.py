from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from core.models import SiteSettings
from databases.models import Plan
from support import services
from support.models import Ticket

MEDIA = "/tmp/claude-0/-home-claude/2234ec6a-5c11-59b3-8baf-aeb4326ca9f5/scratchpad/media-test"


@override_settings(MEDIA_ROOT=MEDIA)
class SupportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("09121110000")
        self.other = User.objects.create_user("09121110001")
        self.admin = User.objects.create_admin("boss", "Very-Secret-123")
        self.plan = Plan.objects.create(name="حرفه‌ای", slug="pro", price_toman=290000, is_free=False)
        self.client.force_login(self.user)
        self.notify = mock.patch("databases.services._notify").start()
        self.addCleanup(mock.patch.stopall)

    def _open(self, **extra):
        data = {"category": "tech", "subject": "اتصال QGIS", "body": "به پورت وصل نمی‌شوم", **extra}
        return self.client.post(reverse("support:new"), data)

    def test_open_reply_and_staff_answer(self):
        r = self._open(attachment=SimpleUploadedFile("err.png", b"\x89PNG....", content_type="image/png"))
        t = Ticket.objects.get(user=self.user)
        self.assertRedirects(r, reverse("support:detail", args=[t.number]))
        self.assertEqual(t.status, "open")
        self.assertTrue(t.messages.first().attachment)
        # پاسخ مدیر از پنل
        admin_client = Client()
        admin_client.force_login(self.admin)
        url = reverse("admin:support_ticket_change", args=[t.pk])
        self.assertEqual(admin_client.get(url).status_code, 200)
        r = admin_client.post(url, {"status": "open", "category": "tech", "reply": "پورت ۵۴۳۴ را بگذارید."})
        self.assertEqual(r.status_code, 302, r.content[:2000])
        t.refresh_from_db()
        self.assertEqual(t.status, "answered")
        self.assertTrue(t.messages.filter(is_staff=True).exists())
        self.notify.assert_called_once()
        # کاربر پاسخ را می‌بیند و جواب می‌دهد
        r = self.client.get(reverse("support:detail", args=[t.number]))
        self.assertContains(r, "پورت ۵۴۳۴ را بگذارید.")
        self.client.post(reverse("support:detail", args=[t.number]), {"body": "درست شد، ممنون"})
        t.refresh_from_db()
        self.assertEqual(t.status, "open")
        self.client.post(reverse("support:close", args=[t.number]))
        t.refresh_from_db()
        self.assertEqual(t.status, "closed")
        r = self.client.post(reverse("support:detail", args=[t.number]), {"body": "باز هم"}, follow=True)
        self.assertEqual(t.messages.count(), 3)

    def test_privacy(self):
        self._open(attachment=SimpleUploadedFile("a.txt", b"secret", content_type="text/plain"))
        t = Ticket.objects.get()
        c = Client()
        c.force_login(self.other)
        self.assertEqual(c.get(reverse("support:detail", args=[t.number])).status_code, 404)
        self.assertEqual(c.get(reverse("support:attachment", args=[t.messages.first().pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("support:attachment", args=[t.messages.first().pk])).status_code,
                         200)

    def test_plan_prefill_from_home(self):
        r = self.client.get(reverse("support:new") + "?plan=pro")
        self.assertContains(r, "درخواست خرید پلن حرفه‌ای")

    def test_home_button_when_payments_off(self):
        SiteSettings.objects.update(pay_enabled=False)
        r = self.client.get("/")
        self.assertContains(r, reverse("support:new") + "?plan=pro")

    def test_limits_and_bad_file(self):
        r = self._open(attachment=SimpleUploadedFile("x.exe", b"MZ", content_type="application/octet-stream"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Ticket.objects.exists())
        for _ in range(services.MAX_OPEN_TICKETS):
            self._open()
        r = self.client.post(reverse("support:new"), {"category": "tech", "subject": "x", "body": "y"}, follow=True)
        self.assertEqual(Ticket.objects.count(), services.MAX_OPEN_TICKETS)

    def test_staff_redirected_from_user_pages(self):
        c = Client()
        c.force_login(self.admin)
        self.assertEqual(c.get(reverse("support:list")).status_code, 302)
