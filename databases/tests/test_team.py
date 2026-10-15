"""اعضای تیم (حساب‌های سایت) و کاربران اضافه PostgreSQL روی سرور واقعی."""
import os
import unittest
import uuid

import psycopg
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases import services as db_services
from databases import team
from databases.models import DatabaseServer, DbRole, Member, Plan, UserDatabase
from databases.provisioner import Provisioner

PG_HOST = os.environ.get("TEST_PG_HOST", "")


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"])
class TeamTests(TestCase):
    def setUp(self):
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        self.server = server
        Provisioner.for_server(server).harden()
        self.owner = User.objects.create_user("09120000071")
        self.db = db_services.create_database(self.owner, f"tm_{uuid.uuid4().hex[:8]}", "Team-Pass-123", ["postgis"])
        self.addCleanup(self._drop)
        self.paid = Plan.objects.create(name="حرفه‌ای آزمون", slug="t-pro", is_free=False, db_roles=3, team_members=3)
        self.db.plan = self.paid
        self.db.save(update_fields=["plan"])
        with self._conn(self.db.role_name, "Team-Pass-123") as c:
            c.execute("CREATE TABLE parcels(id serial PRIMARY KEY, name text)")
            c.execute("INSERT INTO parcels(name) VALUES ('الف')")

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _conn(self, user, password, dbname=None):
        return psycopg.connect(host=self.server.host, port=self.server.port, user=user, password=password,
                               dbname=dbname or self.db.db_name, autocommit=True, connect_timeout=5)

    # ------------------------------------------------------------------ اعضای تیم
    def test_member_levels(self):
        self.client.force_login(self.owner)
        url = reverse("databases:team", args=[self.db.pk])
        self.client.post(url, {"action": "invite", "phone": "۰۹۱۲۰۰۰۰۰۷۲", "role": "viewer"})
        self.client.post(url, {"action": "invite", "phone": "09120000073", "role": "editor"})
        m = Member.objects.get(phone="09120000072")
        self.assertIsNone(m.user)  # هنوز ثبت‌نام نکرده
        viewer = User.objects.create_user("09120000072")
        editor = User.objects.create_user("09120000073")

        # مشاهده‌گر: بعد از ورود، پایگاه داده را در داشبورد می‌بیند
        self.client.force_login(viewer)
        self.assertContains(self.client.get(reverse("databases:dashboard")), self.db.db_name)
        self.assertContains(self.client.get(reverse("databases:detail", args=[self.db.pk])), "مشاهده‌گر")
        r = self.client.get(reverse("databases:explore_table", args=[self.db.pk, "public", "parcels"]))
        self.assertEqual(r.status_code, 200)
        for name in ("import", "team", "backups"):
            self.assertEqual(self.client.get(reverse(f"databases:{name}", args=[self.db.pk])).status_code, 404, name)
        self.assertEqual(self.client.get(reverse("publish:manage", args=[self.db.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("iranmap:ready", args=[self.db.pk])).status_code, 404)
        r = self.client.post(reverse("databases:explore_sql", args=[self.db.pk]),
                             {"query": "DELETE FROM parcels", "allow_write": "on"})
        self.assertContains(r, "خواندنی")
        with self._conn(self.db.role_name, "Team-Pass-123") as c:
            self.assertEqual(c.execute("SELECT count(*) FROM parcels").fetchone()[0], 1)

        # ویرایشگر: ورود فایل و انتشار دارد، اما بکاپ و تیم و حذف نه
        self.client.force_login(editor)
        self.assertEqual(self.client.get(reverse("databases:import", args=[self.db.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("publish:manage", args=[self.db.pk])).status_code, 200)
        r = self.client.post(reverse("databases:explore_sql", args=[self.db.pk]),
                             {"query": "INSERT INTO parcels(name) VALUES ('ب')", "allow_write": "on"})
        self.assertEqual(r.status_code, 200)
        with self._conn(self.db.role_name, "Team-Pass-123") as c:
            self.assertEqual(c.execute("SELECT count(*) FROM parcels").fetchone()[0], 2)
        for name in ("team", "backups"):
            self.assertEqual(self.client.get(reverse(f"databases:{name}", args=[self.db.pk])).status_code, 404, name)
        self.assertEqual(self.client.post(reverse("databases:delete", args=[self.db.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("publish:create_key", args=[self.db.pk])).status_code, 404)

        # حذف عضو: دسترسی فوراً قطع می‌شود
        self.client.force_login(self.owner)
        self.client.post(url, {"action": "remove", "id": Member.objects.get(user=editor).pk})
        self.client.force_login(editor)
        self.assertEqual(self.client.get(reverse("databases:explore", args=[self.db.pk])).status_code, 404)

    def test_member_caps_and_validation(self):
        with self.assertRaisesMessage(team.TeamError, "۰۹۱۲"):
            team.invite(self.db, self.owner, "12345", "viewer")
        with self.assertRaisesMessage(team.TeamError, "خود مالک"):
            team.invite(self.db, self.owner, self.owner.phone, "viewer")
        for i in range(3):
            team.invite(self.db, self.owner, f"0912000010{i}", "viewer")
        with self.assertRaisesMessage(team.TeamError, "حداکثر"):
            team.invite(self.db, self.owner, "09120000109", "viewer")
        team.invite(self.db, self.owner, "09120000100", "editor")  # تغییر نقش عضو موجود مجاز است
        self.assertEqual(Member.objects.get(phone="09120000100").role, "editor")
        free = Plan.objects.create(name="رایگان آزمون", slug="t-free", is_free=True)
        self.db.plan = free
        with self.assertRaisesMessage(team.TeamError, "پولی"):
            team.invite(self.db, self.owner, "09120000108", "viewer")

    # ------------------------------------------------------------------ کاربران PostgreSQL
    def test_read_and_write_roles(self):
        self.client.force_login(self.owner)
        url = reverse("databases:team", args=[self.db.pk])
        self.client.post(url, {"action": "role_create", "suffix": "reader", "access": "read", "note": "GeoServer"})
        r = self.client.get(url)
        pw = r.context["new_pw"]["password"]
        name = team.role_name_for(self.db, "reader")
        self.assertEqual(r.context["new_pw"]["name"], name)
        self.assertIsNone(self.client.get(url).context["new_pw"])  # فقط یک بار
        with self._conn(name, pw) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM parcels").fetchone()[0], 1)
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                c.execute("INSERT INTO parcels(name) VALUES ('x')")
        # پایگاه داده دیگر روی همان سرور: اجازه اتصال ندارد
        with self.assertRaises(psycopg.OperationalError):
            self._conn(name, pw, dbname="postgres").close()

        team.create_role(self.db, self.owner, "editor1", "write", "Writer-Pass-123")
        wname = team.role_name_for(self.db, "editor1")
        with self._conn(wname, "Writer-Pass-123") as c:
            c.execute("INSERT INTO parcels(name) VALUES ('پ')")
            c.execute("UPDATE parcels SET name = 'ت' WHERE name = 'پ'")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("CREATE TABLE evil(id int)")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("DROP TABLE parcels")

        # تعلیق پایگاه داده کاربران اضافه را هم می‌بندد؛ فعال‌سازی دوباره بازشان می‌کند
        db_services.set_status(self.db, UserDatabase.Status.SUSPENDED)
        with self.assertRaises(psycopg.OperationalError):
            self._conn(wname, "Writer-Pass-123").close()
        db_services.set_status(self.db, UserDatabase.Status.ACTIVE)
        self._conn(wname, "Writer-Pass-123").close()

        # رمز جدید و حذف
        role = DbRole.objects.get(name=wname)
        team.reset_role_password(self.db, self.owner, role, "New-Writer-Pass-1")
        with self.assertRaises(psycopg.OperationalError):
            self._conn(wname, "Writer-Pass-123").close()
        self._conn(wname, "New-Writer-Pass-1").close()
        self.client.post(url, {"action": "role_drop", "id": role.pk})
        self.assertFalse(DbRole.objects.filter(name=wname).exists())
        with self._conn(self.db.role_name, "Team-Pass-123") as c:
            self.assertIsNone(c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (wname,)).fetchone())

    def test_role_validation_and_delete_database(self):
        for bad in ("1abc", "web", "a", "x" * 13, "re-ad"):
            with self.assertRaises(team.TeamError, msg=bad):
                team.create_role(self.db, self.owner, bad, "read", "Pass-12345678")
        team.create_role(self.db, self.owner, "gis", "read", "Pass-12345678")
        with self.assertRaisesMessage(team.TeamError, "قبلاً"):
            team.create_role(self.db, self.owner, "gis", "read", "Pass-12345678")
        name = team.role_name_for(self.db, "gis")
        db_services.delete_database(self.db)
        with psycopg.connect(**self.server.connection_kwargs(), autocommit=True) as c:
            self.assertIsNone(c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone())
