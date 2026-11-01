"""اعلان‌ها: ساخت از وضعیت کار، poll/خواندن، ثبت پیام خطا و حضور زنگ در قاب برنامه (بدون PostgreSQL واقعی)."""
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from databases import services
from databases.tests.test_services import BaseCase
from jobs.models import Job
from notifications import services as ns
from notifications.models import Notification

STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


@override_settings(STORAGES=STORAGES)
class NotificationTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "notif", "Abcdefgh123", ["postgis"])

    def _job(self, **kw):
        kw.setdefault("kind", Job.Kind.IMPORT)
        return Job.objects.create(database=self.db, user=self.user, **kw)

    def test_finished_job_notifies_once(self):
        job = self._job(status=Job.Status.RUNNING)
        self.assertFalse(Notification.objects.exists())
        job.status, job.message = Job.Status.DONE, "ok"
        job.save()
        job.save()  # ذخیرهٔ دوباره، اعلان تکراری نمی‌سازد
        n = Notification.objects.get()
        self.assertEqual((n.user, n.level, n.database), (self.user, "success", self.db))
        self.assertIn("دریافت", n.title)

    def test_failed_job_is_error_with_short_reason_and_raw_detail(self):
        job = self._job(kind=Job.Kind.ASK, status=Job.Status.FAILED,
                        message="canceling statement due to statement timeout\nCONTEXT: ...")
        n = Notification.objects.get(job=job)
        self.assertEqual(n.level, "error")
        self.assertIn("طول کشید", n.body)  # توضیح فارسی، نه متن خام
        self.assertIn("CONTEXT", n.detail)  # متن فنی در «جزئیات»
        self.assertIn(f"/dashboard/{self.db.pk}/analysis/", n.url)

    def test_automatic_success_is_quiet_but_automatic_failure_is_not(self):
        self._job(kind=Job.Kind.BACKUP, trigger=Job.Trigger.AUTO, status=Job.Status.DONE)
        self.assertFalse(Notification.objects.exists())
        self._job(kind=Job.Kind.BACKUP, trigger=Job.Trigger.AUTO, status=Job.Status.FAILED, message="disk full")
        self.assertEqual(Notification.objects.get().level, "error")

    def test_job_without_user_goes_to_database_owner(self):
        Job.objects.create(kind=Job.Kind.CLONE, database=self.db, status=Job.Status.DONE)
        self.assertEqual(Notification.objects.get().user, self.user)

    def test_for_job_ignores_unfinished(self):
        self.assertIsNone(ns.for_job(self._job(status=Job.Status.QUEUED)))

    def test_plan_ready_is_info_with_action(self):
        from analysis.models import Question

        job = self._job(kind=Job.Kind.ASK, status=Job.Status.RUNNING)
        Question.objects.create(database=self.db, user=self.user, text="مدرسه‌ها", output_table="x", job=job,
                                result_kind=Question.Result.PLAN)
        job.refresh_from_db()
        job.status = Job.Status.DONE
        job.save()
        n = Notification.objects.get(job=job)
        self.assertEqual(n.level, "info")
        self.assertEqual(n.action, "بررسی برنامه")

    def test_tool_title_uses_tool_name(self):
        from analysis.models import ToolRun

        job = self._job(kind=Job.Kind.TOOL, status=Job.Status.RUNNING)
        ToolRun.objects.create(database=self.db, user=self.user, tool="buffer", output_table="b", job=job)
        job.refresh_from_db()
        job.status = Job.Status.DONE
        job.save()
        n = Notification.objects.get(job=job)
        self.assertIn("حریم", n.title)
        self.assertIn(f"/dashboard/{self.db.pk}/tools/", n.url)

    def test_stuck_job_cleanup_notifies_the_user(self):
        from datetime import timedelta

        from django.utils import timezone

        from jobs import services as jobs

        job = self._job(status=Job.Status.RUNNING, started_at=timezone.now() - timedelta(days=2))
        jobs.cleanup()
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertEqual(Notification.objects.get(job=job).level, "error")


@override_settings(STORAGES=STORAGES)
class NotificationApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("09120000011")
        self.other = User.objects.create_user("09120000012")
        self.client.force_login(self.user)
        self.poll = reverse("notifications:poll")

    def _n(self, user=None, **kw):
        return Notification.objects.create(user=user or self.user, title=kw.pop("title", "t"), **kw)

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.poll).status_code, 302)
        self.assertEqual(self.client.post(reverse("notifications:read")).status_code, 302)

    def test_first_poll_returns_only_latest_id_then_fresh_after(self):
        old = self._n(title="قدیمی")
        d = self.client.get(self.poll).json()
        self.assertEqual((d["latest"], d["fresh"], d["unread"]), (old.pk, [], 1))
        new = self._n(title="تازه", level="error", body="b", detail="d")
        self._n(user=self.other, title="دیگری")
        d = self.client.get(self.poll, {"after": old.pk}).json()
        self.assertEqual([x["title"] for x in d["fresh"]], ["تازه"])
        self.assertEqual(d["fresh"][0]["level"], "error")
        self.assertEqual(d["latest"], new.pk)
        self.assertIsNone(d["items"])
        # پیام خوانده‌شده (مثل خطایی که همان لحظه با مودال دیده شد) دوباره toast نمی‌شود
        self._n(title="دیده‌شده", read_at=timezone.now())
        d = self.client.get(self.poll, {"after": new.pk}).json()
        self.assertEqual(d["fresh"], [])

    def test_panel_items_are_only_mine(self):
        self._n(title="من")
        self._n(user=self.other, title="او")
        d = self.client.get(self.poll, {"panel": "1"}).json()
        self.assertEqual([x["title"] for x in d["items"]], ["من"])

    def test_read_one_and_all_only_for_owner(self):
        a, b = self._n(), self._n()
        theirs = self._n(user=self.other)
        r = self.client.post(reverse("notifications:read"), {"id": a.pk}).json()
        self.assertEqual(r["unread"], 1)
        self.client.post(reverse("notifications:read"), {"id": theirs.pk})
        theirs.refresh_from_db()
        self.assertIsNone(theirs.read_at)
        self.assertEqual(self.client.post(reverse("notifications:read")).json()["unread"], 0)
        b.refresh_from_db()
        self.assertIsNotNone(b.read_at)
        self.assertEqual(self.client.post(reverse("notifications:read"), {"id": "x"}).json()["unread"], 0)

    def test_log_stores_only_error_and_warning_as_read(self):
        url = reverse("notifications:log")
        self.assertEqual(self.client.post(url, {"level": "success", "title": "ok"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"level": "error", "title": ""}).status_code, 400)
        self.assertEqual(self.client.post(url, {"level": "error", "title": "خطا", "body": "متن"}).status_code, 200)
        n = Notification.objects.get()
        self.assertEqual((n.level, n.body), ("error", "متن"))
        self.assertIsNotNone(n.read_at)  # کاربر همان لحظه مودال را دیده است

    def test_log_is_rate_limited(self):
        url = reverse("notifications:log")
        for _ in range(20):
            self.assertEqual(self.client.post(url, {"level": "warning", "title": "w"}).status_code, 200)
        self.assertEqual(self.client.post(url, {"level": "warning", "title": "w"}).status_code, 429)

    def test_bell_and_flash_markup_in_app_frame(self):
        r = self.client.get(reverse("databases:dashboard"))
        self.assertContains(r, 'id="ntf-bell"')
        self.assertContains(r, "js/notifications.js")
        self.assertContains(r, "css/notify.css")
