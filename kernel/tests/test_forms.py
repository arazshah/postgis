"""فرم ثبت ردیف در کیت صفحه: مشخصات، تبدیل مقدار، ساخت INSERT امن و نمای ثبت."""
import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

import psycopg
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from databases import services
from databases.tests.test_services import BaseCase
from kernel import entitlements, metering, pagekit
from kernel.models import Entitlement, PluginState
from kernel.plugins import registry
from kernel.tests.test_pagekit import STORAGES

PG_HOST = os.environ.get("TEST_PG_HOST", "")
FORM = {"key": "report", "title": "گزارش حادثه", "table": "incidents", "fields": [
    {"name": "title", "kind": "text", "label": "عنوان", "required": True, "max": 50},
    {"name": "severity", "kind": "choice", "label": "شدت", "choices": [["low", "کم"], ["high", "زیاد"]], "required": True},
    {"name": "count", "kind": "int", "label": "تعداد", "min": 0, "max": 100},
    {"name": "seen", "kind": "date", "label": "تاریخ"},
    {"name": "ok", "kind": "bool", "label": "تأیید شده"}]}
PAGE = {"key": "inc", "title": "حوادث", "need": "editor", "blocks": [{"kind": "text", "text": "x"}], "forms": [FORM]}


class SpecTests(SimpleTestCase):
    def test_valid_and_defaults(self):
        p = pagekit.parse_page("demo", PAGE)
        self.assertEqual(p.forms[0].table, "incidents")
        self.assertEqual(len(p.forms[0].fields), 5)

    def test_writes_need_editor_level(self):
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "need": "viewer"})

    def test_rejections(self):
        bad = [{**FORM, "table": "x; drop table y"}, {**FORM, "table": "A.b"}, {**FORM, "fields": []},
               {**FORM, "fields": [{"name": "a b", "label": "x"}]}, {**FORM, "fields": [{"name": "a", "label": "x"}, {"name": "a", "label": "y"}]},
               {**FORM, "fields": [{"name": "k", "kind": "weird", "label": "x"}]},
               {**FORM, "fields": [{"name": "k", "kind": "choice", "label": "x"}]},
               {**FORM, "key": "Bad Key"}]
        for f in bad:
            with self.subTest(f=f), self.assertRaises(pagekit.SpecError):
                pagekit.parse_page("demo", {**PAGE, "forms": [f]})
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "forms": [{**FORM, "key": f"f{i}"} for i in range(4)]})
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "forms": [FORM, FORM]})

    def test_conversion(self):
        form = pagekit.parse_page("demo", PAGE).forms[0]
        ok, err = pagekit.read_form(form, {"f_title": " سیل ", "f_severity": "high", "f_count": "7", "f_seen": "2026-01-02", "f_ok": "on"})
        self.assertEqual(err, [])
        self.assertEqual((ok["title"], ok["count"], ok["ok"], str(ok["seen"])), ("سیل", 7, True, "2026-01-02"))
        _v, errs = pagekit.read_form(form, {"f_title": "", "f_severity": "zzz", "f_count": "500", "f_seen": "x"})
        self.assertEqual(len(errs), 4)  # عنوان، شدت، تعداد، تاریخ
        _v, errs = pagekit.read_form(form, {"f_title": "a" * 80, "f_severity": "low", "f_count": "nan"})
        self.assertEqual(len(errs), 2)
        v, _e = pagekit.read_form(form, {"f_title": "t", "f_severity": "low"})
        self.assertIsNone(v["count"])  # خالی و غیراجباری


class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, q, args=None, **kw):
        self.calls.append((q if isinstance(q, str) else q.as_string(None) if hasattr(q, "as_string") else str(q), args))
        return self

    def commit(self):
        self.calls.append(("COMMIT", None))

    def cursor(self):
        conn = self

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def executemany(self, q, rows):
                for r in rows:
                    conn.execute(q, r)

        return Cur()


class InsertTests(SimpleTestCase):
    def setUp(self):
        self.form = pagekit.parse_page("demo", PAGE).forms[0]
        self.vals = {"title": "t", "severity": "low", "count": 1, "seen": None, "ok": False}
        self.table = SimpleNamespace(schema="public", name="incidents", kind="r")
        cols = [{"name": n, "generated": False, "identity": "", "spatial": False} for n in self.vals]
        self.cat = mock.Mock()
        self.cat.tables.return_value = [self.table]
        self.cat.columns.return_value = cols
        self.conn = FakeConn()

        @contextmanager
        def connect(ws, **kw):
            self.kw = kw
            yield self.conn

        for target, val in (("kernel.tenantdb.catalog", lambda ws: self.cat), ("kernel.tenantdb.connect", connect)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)

    def test_insert_is_parametrised_owner_write(self):
        pagekit.insert_row(object(), self.form, self.vals)
        self.assertEqual(self.kw, {"write": True, "as_owner": True})
        self.assertEqual(self.conn.calls[-1], ("COMMIT", None))
        args = [a for _q, a in self.conn.calls if a is not None]
        self.assertEqual(args, [["t", "low", 1, None, False]])  # مقدارها فقط پارامتر؛ هیچ مقداری در متن SQL نیست

    def test_missing_table_view_and_system_names(self):
        self.cat.tables.return_value = []
        with self.assertRaises(pagekit.SpecError):
            pagekit.insert_row(object(), self.form, self.vals)
        self.cat.tables.return_value = [SimpleNamespace(schema="public", name="incidents", kind="v")]
        with self.assertRaises(pagekit.SpecError):
            pagekit.insert_row(object(), self.form, self.vals)
        for table in ("pg_catalog.pg_class", "information_schema.tables", "public.spatial_ref_sys"):
            f = pagekit.parse_page("demo", {**PAGE, "forms": [{**FORM, "table": table}]}).forms[0]
            with self.assertRaises(pagekit.SpecError):
                pagekit.insert_row(object(), f, self.vals)

    def test_unknown_generated_identity_and_spatial_columns_refused(self):
        self.cat.columns.return_value = [{"name": "title", "generated": False, "identity": "", "spatial": False}]
        with self.assertRaises(pagekit.SpecError):
            pagekit.insert_row(object(), self.form, self.vals)  # ستون‌های دیگر نیستند
        for patch in ({"generated": True}, {"identity": "a"}, {"spatial": True}):
            cols = [{"name": n, "generated": False, "identity": "", "spatial": False, **(patch if n == "count" else {})} for n in self.vals]
            self.cat.columns.return_value = cols
            with self.subTest(patch=patch), self.assertRaises(pagekit.SpecError):
                pagekit.insert_row(object(), self.form, self.vals)
        self.assertFalse(self.conn.calls)  # هیچ نوشتنی انجام نشد


class SubmitViewTests(BaseCase):
    def setUp(self):
        super().setUp()
        entitlements.invalidate()
        self.addCleanup(entitlements.invalidate)
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        pagekit.register("demo", pagekit.parse_page("demo", PAGE))
        self.db = services.create_database(self.user, "fdb", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        self.url = reverse("kernel:form", args=[self.db.pk, "demo", "inc", "report"])
        self.page_url = reverse("kernel:page", args=[self.db.pk, "demo", "inc"])
        self.good = {"f_title": "سیل", "f_severity": "high", "f_count": "3"}
        p = mock.patch("kernel.pagekit.insert_row")
        self.insert = p.start()
        self.addCleanup(p.stop)

    def test_get_not_allowed_and_anonymous_redirected(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.url, self.good).status_code, 302)
        self.insert.assert_not_called()

    def test_success_inserts_meters_and_redirects(self):
        r = self.client.post(self.url, self.good)
        self.assertRedirects(r, self.page_url, fetch_redirect_response=False)
        self.insert.assert_called_once()
        self.assertEqual(self.insert.call_args[0][2]["title"], "سیل")
        self.assertEqual(metering.used("demo", "form_submits", ws=self.db), 1)

    def test_invalid_values_do_not_insert(self):
        self.client.post(self.url, {"f_title": "", "f_severity": "zzz"})
        self.insert.assert_not_called()
        self.assertEqual(metering.used("demo", "form_submits", ws=self.db), 0)

    def test_database_error_is_short_and_not_metered(self):
        self.insert.side_effect = psycopg.errors.NotNullViolation("null value in column x")
        r = self.client.post(self.url, self.good)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(metering.used("demo", "form_submits", ws=self.db), 0)

    def test_monthly_cap(self):
        st = PluginState.objects.create(plugin_id="demo")
        Entitlement.objects.create(state=st, kind=Entitlement.Kind.ALL, limits={"form_submits_per_month": 1})
        entitlements.invalidate()
        self.client.post(self.url, self.good)
        self.client.post(self.url, self.good)
        self.assertEqual(self.insert.call_count, 1)

    def test_other_users_and_off_plugin_get_404(self):
        from accounts.models import User

        self.client.force_login(User.objects.create_user("09120000099"))
        self.assertEqual(self.client.post(self.url, self.good).status_code, 404)
        self.client.force_login(self.user)
        PluginState.objects.create(plugin_id="demo", enabled=False)
        entitlements.invalidate()
        self.assertEqual(self.client.post(self.url, self.good).status_code, 404)
        self.assertEqual(self.client.post(reverse("kernel:form", args=[self.db.pk, "demo", "inc", "nope"]), self.good).status_code, 404)
        self.insert.assert_not_called()

    @override_settings(STORAGES=STORAGES)
    def test_form_is_rendered_with_csrf(self):
        with mock.patch("kernel.tenantdb.catalog"):
            r = self.client.get(self.page_url)
        self.assertContains(r, "گزارش حادثه")
        self.assertContains(r, 'name="f_title"')
        self.assertContains(r, "csrfmiddlewaretoken")


@unittest.skipUnless(PG_HOST, "به TEST_PG_HOST نیاز دارد")
class RealInsertTests(SimpleTestCase):
    def test_real_insert_and_constraint_error(self):
        kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                  password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        with psycopg.connect(dbname="postgres", **kw) as c:
            c.execute("DROP DATABASE IF EXISTS pagekit_f")
            c.execute("CREATE DATABASE pagekit_f")
        with psycopg.connect(dbname="pagekit_f", **kw) as c:
            c.execute("CREATE TABLE incidents(id serial primary key, title text not null, severity text, count int, seen date, ok bool)")
        form = pagekit.parse_page("demo", PAGE).forms[0]
        table = SimpleNamespace(schema="public", name="incidents", kind="r", oid=0)
        cat = mock.Mock()
        cat.tables.return_value = [table]
        cat.columns.return_value = [{"name": n, "generated": False, "identity": "", "spatial": False} for n in ("title", "severity", "count", "seen", "ok")]

        @contextmanager
        def connect(ws, **kw2):
            conn = psycopg.connect(dbname="pagekit_f", **kw)
            conn.autocommit = False
            try:
                yield conn
            finally:
                conn.close()

        with mock.patch("kernel.tenantdb.catalog", lambda ws: cat), mock.patch("kernel.tenantdb.connect", connect):
            pagekit.insert_row(object(), form, {"title": "x'; drop table incidents;--", "severity": "low", "count": 2, "seen": None, "ok": True})
            with self.assertRaises(psycopg.errors.NotNullViolation):
                pagekit.insert_row(object(), form, {"title": None, "severity": "low", "count": 2, "seen": None, "ok": True})
        with psycopg.connect(dbname="pagekit_f", **kw) as c:
            rows = c.execute("SELECT title, count FROM incidents").fetchall()
        self.assertEqual(rows, [("x'; drop table incidents;--", 2)])
