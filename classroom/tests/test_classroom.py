"""پلن کلاس: درخواست قرارداد، ساخت کلاس، ثبت‌نام دانشجو با پایگاه داده واقعی، بایگانی پایان ترم."""
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import psycopg
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from classroom import services
from classroom.models import Classroom, Contract, ContractRequest, Enrollment
from databases import services as db_services
from databases.models import DatabaseServer, UserDatabase
from databases.provisioner import Provisioner
from jobs import services as jobs

PG_HOST = os.environ.get("TEST_PG_HOST", "")
HAS_GDAL = bool(shutil.which("ogr2ogr"))


@override_settings(ALLOWED_HOSTS=["testserver"])
class LandingTests(TestCase):
    def test_request_form(self):
        r = self.client.get(reverse("classroom:landing"))
        self.assertContains(r, "درخواست قرارداد")
        r = self.client.post(reverse("classroom:landing"), {"institution": "دانشگاه تهران", "name": "دکتر الف",
                                                            "phone": "۰۹۱۲۱۱۱۲۲۳۳", "students": "۴۵", "course": "GIS"})
        self.assertContains(r, "ثبت شد")
        req = ContractRequest.objects.get()
        self.assertEqual((req.phone, req.students), ("09121112233", 45))
        r = self.client.post(reverse("classroom:landing"), {"institution": "", "name": "x", "phone": "123"})
        self.assertContains(r, "معتبر نیست")
        self.assertEqual(ContractRequest.objects.count(), 1)
        self.client.post(reverse("classroom:landing"), {"institution": "a", "name": "b", "phone": "09121112233",
                                                        "website": "spam"})
        self.assertEqual(ContractRequest.objects.count(), 1)

    def test_not_teacher(self):
        self.client.force_login(User.objects.create_user("09120000051"))
        self.assertContains(self.client.get(reverse("classroom:teach")), "قرارداد کلاسی")


@unittest.skipUnless(PG_HOST and HAS_GDAL, "TEST_PG_HOST or ogr2ogr missing")
@override_settings(ALLOWED_HOSTS=["testserver"])
class ClassFlowTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        o = override_settings(BACKUP_ROOT=str(self.tmp / "bk"))
        o.enable()
        self.addCleanup(o.disable)
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        self.server = server
        Provisioner.for_server(server).harden()
        today = timezone.localdate()
        self.contract = Contract.objects.create(institution="دانشگاه آزمون", seats=2, starts_at=today - timedelta(days=1),
                                                ends_at=today + timedelta(days=90), quota_mb=300,
                                                teacher_phones="09120000052\n")
        self.teacher = User.objects.create_user("09120000052")
        self.addCleanup(self._drop_all)

    def _drop_all(self):
        for db in UserDatabase.objects.exclude(status="deleted"):
            db_services.delete_database(db)

    def test_full_term(self):
        # استاد با شماره ثبت‌شده در قرارداد وارد می‌شود و کلاس می‌سازد
        self.client.force_login(self.teacher)
        r = self.client.get(reverse("classroom:teach"))
        self.assertContains(r, "دانشگاه آزمون")
        r = self.client.post(reverse("classroom:teach"), {"title": "پایگاه داده مکانی", "contract": self.contract.pk,
                                                          "capacity": "5", "template": "sample"})
        self.assertContains(r, "صندلی خالی")  # ظرفیت ۵ بیشتر از ۲ صندلی قرارداد
        self.client.post(reverse("classroom:teach"), {"title": "پایگاه داده مکانی", "contract": self.contract.pk,
                                                      "capacity": "2", "template": "sample"})
        c = Classroom.objects.get()
        self.assertContains(self.client.get(reverse("classroom:detail", args=[c.pk])), c.code)

        # دانشجو با کد ثبت‌نام می‌کند؛ پایگاه داده با داده تمرینی ساخته می‌شود
        s1 = User.objects.create_user("09120000053")
        for i in range(3):  # سقف تعداد پایگاه داده شخصی مانع کلاس نمی‌شود
            UserDatabase.objects.create(owner=s1, server=self.server, plan=services.class_plan(10),
                                        db_name=f"x{i}_{s1.pk}", role_name=f"x{i}_{s1.pk}_u", status="active")
        self.client.force_login(s1)
        url = reverse("classroom:join", args=[c.code.lower()])
        self.assertContains(self.client.get(url), "ثبت‌نام و ساخت")
        r = self.client.post(url, {"full_name": "سارا احمدی", "student_no": "4001"}, follow=True)
        pw = r.context["password"]
        self.assertTrue(pw)
        e = Enrollment.objects.get(student=s1)
        db = e.database
        self.assertEqual(db.plan.slug, "class-300")
        self.assertFalse(db.plan.is_renewable)
        self.assertEqual(timezone.localtime(db.expires_at).date(), self.contract.ends_at)
        with psycopg.connect(host=self.server.host, port=self.server.port, user=db.role_name, password=pw,
                             dbname=db.db_name) as conn:
            n = conn.execute("SELECT count(*) FROM schools").fetchone()[0]
            self.assertGreater(n, 50)
            self.assertEqual(conn.execute("SELECT count(*) FROM metro_stations").fetchone()[0] > 0, True)
        self.assertIsNone(self.client.get(url).context["password"])  # رمز فقط یک بار

        # استاد پایگاه داده دانشجو را فقط می‌بیند
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("databases:explore", args=[db.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("databases:import", args=[db.pk])).status_code, 404)
        csv = self.client.get(reverse("classroom:detail", args=[c.pk]), {"format": "csv"}).content.decode()
        self.assertIn("سارا احمدی", csv)
        self.assertIn(db.role_name, csv)

        # ظرفیت قرارداد
        s2, s3 = User.objects.create_user("09120000054"), User.objects.create_user("09120000055")
        services.join(c, s2, "دانشجو دو")
        with self.assertRaisesMessage(services.ClassError, "ظرفیت"):
            services.join(c, s3, "دانشجو سه")
        with self.assertRaisesMessage(services.ClassError, "قبلاً"):
            services.join(c, s2, "دوباره")

        # پایان ترم: tick شب آخر بایگانی می‌کند و بکاپ‌ها برای استاد قابل دانلودند
        Contract.objects.filter(pk=self.contract.pk).update(ends_at=timezone.localdate())
        night = timezone.make_aware(timezone.datetime.combine(timezone.localdate(), timezone.datetime.min.time())
                                    ) + timedelta(hours=22, minutes=30)
        self.assertEqual(services.tick(night - timedelta(hours=3)), 0)
        self.assertEqual(services.tick(night), 1)
        c.refresh_from_db()
        self.assertEqual(c.status, "archived")
        e.refresh_from_db()
        jobs.run_inline(e.archive)
        e.archive.refresh_from_db()
        self.assertEqual(e.archive.status, "done", e.archive.message)
        self.assertGreater((e.archive.expires_at - timezone.now()).days, 170)
        r = self.client.get(reverse("classroom:archive", args=[c.pk, e.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(b"".join(r.streaming_content).startswith(b"PGDMP"))
        # کلاس بایگانی‌شده ثبت‌نام نمی‌پذیرد
        with self.assertRaisesMessage(services.ClassError, "بسته"):
            services.join(c, s3, "دیر")

    def test_other_teacher_cannot_see(self):
        c = services.create_class(self.teacher, self.contract, "کلاس", "empty", 1)
        other = User.objects.create_user("09120000056")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("classroom:detail", args=[c.pk])).status_code, 404)
        with self.assertRaisesMessage(services.ClassError, "فعال نیست"):
            services.create_class(other, self.contract, "x", "empty", 1)
        expired = Contract.objects.create(institution="قدیمی", seats=5, starts_at=date(2025, 1, 1),
                                          ends_at=date(2025, 6, 1))
        expired.teachers.add(self.teacher)
        with self.assertRaises(services.ClassError):
            services.create_class(self.teacher, expired, "x", "empty", 1)
