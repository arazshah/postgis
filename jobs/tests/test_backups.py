import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import psycopg
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from databases import services as db_services
from databases.explorer import Explorer
from databases.models import DatabaseServer, Plan, UserDatabase
from databases.provisioner import Provisioner
from jobs import services
from jobs.models import Job

TEHRAN = ZoneInfo("Asia/Tehran")
PG_HOST = os.environ.get("TEST_PG_HOST", "")


class _Base(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(BACKUP_ROOT=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.server = DatabaseServer(name="s1", host="10.0.0.5", public_host="db.postgis.ir", is_default=True)
        self.server.set_admin_password("secret")
        self.server.save()
        self.user = User.objects.create_user("09120000011")
        self.plan = Plan.objects.get(slug="free")
        self.db = UserDatabase.objects.create(owner=self.user, server=self.server, plan=self.plan, label="tehran",
                                              db_name="gp_tehran", role_name="gp_tehran_user",
                                              status=UserDatabase.Status.ACTIVE)


class QueueTests(_Base):
    def test_manual_backup_limits(self):
        job = services.request_backup(self.db, self.user)
        self.assertEqual((job.kind, job.trigger, job.status), ("backup", "manual", "queued"))
        with self.assertRaisesMessage(services.JobError, "در جریان است"):
            services.request_backup(self.db, self.user)
        Job.objects.update(status=Job.Status.DONE)
        services.request_backup(self.db, self.user)
        Job.objects.update(status=Job.Status.DONE)
        services.request_backup(self.db, self.user)
        Job.objects.update(status=Job.Status.DONE)
        with self.assertRaisesMessage(services.JobError, "حداکثر 3"):
            services.request_backup(self.db, self.user)

    def test_inactive_database_rejected(self):
        self.db.status = UserDatabase.Status.EXPIRED
        self.db.save()
        with self.assertRaises(services.JobError):
            services.request_backup(self.db, self.user)

    def test_restore_needs_own_downloadable_backup(self):
        other = UserDatabase.objects.create(owner=self.user, server=self.server, plan=self.plan, label="b",
                                            db_name="gp_b", role_name="gp_b_user", status="active")
        foreign = Job.objects.create(kind="backup", database=other, status="done", file="x.dump")
        with self.assertRaises(services.JobError):
            services.request_restore(self.db, foreign, self.user)
        failed = Job.objects.create(kind="backup", database=self.db, status="failed")
        with self.assertRaises(services.JobError):
            services.request_restore(self.db, failed, self.user)
        ok = Job.objects.create(kind="backup", database=self.db, status="done", file="1/a.dump")
        job = services.request_restore(self.db, ok, self.user)
        self.assertEqual((job.kind, job.source), ("restore", ok))

    def test_claim_marks_running(self):
        services.request_backup(self.db, self.user)
        job = services.claim_next()
        self.assertEqual(job.status, "running")
        self.assertIsNone(services.claim_next())


class ScheduleTests(_Base):
    def test_nightly_once_per_day_after_3am(self):
        before = datetime(2026, 10, 15, 2, 30, tzinfo=TEHRAN)
        after = datetime(2026, 10, 15, 3, 5, tzinfo=TEHRAN)
        self.assertEqual(services.schedule_nightly(before), 0)
        with mock.patch("django.utils.timezone.now", return_value=after):
            self.assertEqual(services.schedule_nightly(after), 1)
            self.assertEqual(services.schedule_nightly(after + timedelta(hours=2)), 0)
        job = Job.objects.get()
        self.assertEqual(job.trigger, "auto")

    def test_deleted_databases_not_backed_up(self):
        self.db.status = UserDatabase.Status.DELETED
        self.db.save()
        self.assertEqual(services.schedule_nightly(datetime(2026, 10, 15, 4, 0, tzinfo=TEHRAN)), 0)

    def test_cleanup_removes_expired_files(self):
        path = os.path.join(self.tmp.name, "1")
        os.makedirs(path)
        f = os.path.join(path, "a.dump")
        open(f, "wb").write(b"x")
        job = Job.objects.create(kind="backup", database=self.db, status="done", file="1/a.dump",
                                 expires_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(services.cleanup(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, "expired")
        self.assertFalse(os.path.exists(f))

    def test_stuck_jobs_failed(self):
        Job.objects.create(kind="backup", database=self.db, status="running",
                           started_at=timezone.now() - timedelta(hours=5))
        services.cleanup()
        self.assertEqual(Job.objects.get().status, "failed")

    @mock.patch("core.alerts.notify_admins")
    def test_failed_jobs_alerted_once(self, notify):
        Job.objects.create(kind="backup", database=self.db, status="failed", message="boom")
        services.alerts()
        services.alerts()
        notify.assert_called_once()
        self.assertIn("boom", notify.call_args[0][1])

    def test_restore_test_weekly(self):
        self.assertTrue(services.schedule_restore_test())
        self.assertFalse(services.schedule_restore_test())


@override_settings(ALLOWED_HOSTS=["testserver"])
class BackupViewTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_page_and_request(self):
        url = reverse("databases:backups", args=[self.db.pk])
        r = self.client.get(url)
        self.assertContains(r, "بکاپ و بازگردانی")
        self.assertContains(r, "هنوز بکاپی گرفته نشده")
        r = self.client.post(reverse("databases:backup_new", args=[self.db.pk]), follow=True)
        self.assertContains(r, "در صف قرار گرفت")
        self.assertEqual(Job.objects.filter(database=self.db).count(), 1)

    def test_download_only_own_done_backup(self):
        os.makedirs(os.path.join(self.tmp.name, "9"))
        open(os.path.join(self.tmp.name, "9", "a.dump"), "wb").write(b"PGDMP")
        job = Job.objects.create(kind="backup", database=self.db, status="done", file="9/a.dump", size_bytes=5)
        r = self.client.get(reverse("databases:backup_download", args=[self.db.pk, job.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"PGDMP")
        stranger = User.objects.create_user("09120000012")
        self.client.force_login(stranger)
        r = self.client.get(reverse("databases:backup_download", args=[self.db.pk, job.pk]))
        self.assertEqual(r.status_code, 404)

    def test_restore_requires_typed_name(self):
        job = Job.objects.create(kind="backup", database=self.db, status="done", file="9/a.dump")
        url = reverse("databases:backup_restore", args=[self.db.pk, job.pk])
        self.client.post(url, {"confirm": "wrong"})
        self.assertFalse(Job.objects.filter(kind="restore").exists())
        self.client.post(url, {"confirm": "tehran"})
        self.assertTrue(Job.objects.filter(kind="restore", source=job).exists())


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
class BackupRestoreIntegrationTests(TestCase):
    """بکاپ واقعی با pg_dump، تغییر داده، بازگردانی امن و آزمون بازگردانی روی PostGIS واقعی."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(BACKUP_ROOT=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000098")
        self.db = db_services.create_database(self.user, f"bk_{uuid.uuid4().hex[:8]}", "Backup-Pass-12", ["postgis"])
        self.addCleanup(self._drop)
        self.conn_kw = dict(host=server.host, port=server.port, user=self.db.role_name, password="Backup-Pass-12",
                            dbname=self.db.db_name, autocommit=True)
        with psycopg.connect(**self.conn_kw) as c:
            c.execute("CREATE TABLE parcels(id serial PRIMARY KEY, name text, geom geometry(Point, 4326))")
            c.execute("INSERT INTO parcels(name, geom) SELECT 'p' || g, ST_SetSRID(ST_MakePoint(51 + g / 100.0, 35.7),"
                      " 4326) FROM generate_series(1, 30) g")

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _count(self):
        with psycopg.connect(**self.conn_kw) as c:
            return c.execute("SELECT count(*) FROM parcels").fetchone()[0]

    def test_backup_change_restore(self):
        backup = services.run_inline(services.request_backup(self.db, self.user))
        self.assertEqual(backup.status, "done", backup.message)
        self.assertGreater(backup.size_bytes, 1000)
        self.assertTrue(backup.path.read_bytes().startswith(b"PGDMP"))

        with psycopg.connect(**self.conn_kw) as c:
            c.execute("DELETE FROM parcels WHERE id > 10")
            c.execute("CREATE TABLE junk(x int)")
        self.assertEqual(self._count(), 10)

        restore = services.run_inline(services.request_restore(self.db, backup, self.user))
        self.assertEqual(restore.status, "done", restore.message)
        self.assertEqual(self._count(), 30)
        with psycopg.connect(**self.conn_kw) as c:
            owner = c.execute("SELECT tableowner FROM pg_tables WHERE tablename='parcels'").fetchone()[0]
            self.assertEqual(owner, self.db.role_name)  # کاربر صاحب جدول‌های بازگردانده است
            self.assertIsNone(c.execute("SELECT to_regclass('public.junk')").fetchone()[0])
            c.execute("INSERT INTO parcels(name) VALUES ('after')")  # کاربر هنوز می‌تواند بنویسد
        safety = Job.objects.get(pk=restore.params["safety_backup"])
        self.assertEqual((safety.status, safety.params.get("safety")), ("done", True))
        # مرورگر پنل بعد از جابه‌جایی دیتابیس هنوز کار می‌کند
        self.db.refresh_from_db()
        self.assertIn("public.parcels", [t.qualified for t in Explorer(self.db).tables()])

        Job.objects.filter(pk=backup.pk).update(trigger="auto")
        test = services.run_inline(Job.objects.create(kind="restore_test", trigger="system"))
        self.assertEqual(test.status, "done", test.message)
        self.assertIn("1 جدول", test.message)

    def test_sql_console_tables_owned_by_user(self):
        ex = Explorer(self.db)
        ex.run_sql("CREATE TABLE made_in_console AS SELECT * FROM parcels", allow_write=True)
        with psycopg.connect(**self.conn_kw) as c:
            owner = c.execute("SELECT tableowner FROM pg_tables WHERE tablename='made_in_console'").fetchone()[0]
        self.assertEqual(owner, self.db.role_name)
