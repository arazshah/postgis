"""ساخت خودکار جدول پلاگین (`[[tables]]`، ADR-0008 مرحله‌ی ۲)."""
import json
import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

import psycopg
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from databases import services
from databases.tests.test_services import BaseCase
from kernel import entitlements, ingest, pagekit, tables
from kernel.models import PluginTable
from kernel.plugins import registry
from kernel.tests.test_pagekit import STORAGES

PG_HOST = os.environ.get("TEST_PG_HOST", "")
TBL = {"name": "mon_points", "columns": [
    {"name": "device", "type": "text", "required": True},
    {"name": "lat", "type": "double", "required": True},
    {"name": "lon", "type": "double", "required": True},
    {"name": "speed", "type": "double"},
    {"name": "at", "type": "timestamptz", "auto_now": True}], "indexes": [["device", "at"]]}
ING = {"key": "feed", "title": "دریافت", "table": "mon_points", "fields": [
    {"name": "device", "kind": "text", "label": "d", "required": True, "max": 40},
    {"name": "lat", "kind": "number", "label": "a", "required": True},
    {"name": "lon", "kind": "number", "label": "o", "required": True},
    {"name": "speed", "kind": "number", "label": "s"}]}
PAGE = {"key": "live", "title": "پایش", "need": "editor", "blocks": [{"kind": "text", "text": "x"}], "tables": [TBL], "ingest": [ING]}


class SpecTests(SimpleTestCase):
    def test_valid(self):
        t = pagekit.parse_page("mon", PAGE).tables[0]
        self.assertEqual((t.name, len(t.columns), t.indexes), ("mon_points", 5, (("device", "at"),)))
        self.assertTrue(t.columns[4].auto_now)

    def test_rejections(self):
        bad = [{**TBL, "name": "points"},  # بدون پیشوند پلاگین
               {**TBL, "name": "mon_"}, {**TBL, "name": "Mon_x"}, {**TBL, "name": "mon_" + "x" * 70},
               {**TBL, "columns": []}, {**TBL, "columns": [{"name": "id", "type": "text"}]},
               {**TBL, "columns": [{"name": "a b", "type": "text"}]}, {**TBL, "columns": [{"name": "a", "type": "serial"}]},
               {**TBL, "columns": [{"name": "a", "type": "text", "auto_now": True}]},
               {**TBL, "columns": [{"name": "a", "type": "text"}, {"name": "a", "type": "text"}]},
               {**TBL, "columns": [{"name": f"c{i}", "type": "text"} for i in range(25)]},
               {**TBL, "indexes": [["nope"]]}, {**TBL, "indexes": [["device"]] * 5}, {**TBL, "indexes": [[]]}]
        for t in bad:
            with self.subTest(t=str(t)[:60]), self.assertRaises(pagekit.SpecError):
                pagekit.parse_page("mon", {**PAGE, "tables": [t]})
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("mon", {**PAGE, "tables": [TBL, TBL]})
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("mon", {**PAGE, "tables": [{**TBL, "name": f"mon_t{i}"} for i in range(6)]})

    def test_hash_changes_with_structure(self):
        a = pagekit.parse_page("mon", PAGE).tables[0]
        b = pagekit.parse_page("mon", {**PAGE, "tables": [{**TBL, "columns": TBL["columns"] + [{"name": "extra", "type": "text"}]}]}).tables[0]
        self.assertNotEqual(tables.spec_hash(a), tables.spec_hash(b))
        self.assertEqual(tables.spec_hash(a), tables.spec_hash(pagekit.parse_page("mon", PAGE).tables[0]))

    def test_statements_are_whitelisted_and_quoted(self):
        t = pagekit.parse_page("mon", {**PAGE, "tables": [{**TBL, "indexes": [], "columns": [
            {"name": "p", "type": "point", "required": True}, {"name": "j", "type": "jsonb"}]}]}).tables[0]
        text = tables.create_statement(t).as_string(None)
        self.assertIn('"public"."mon_points"', text)
        self.assertIn("geometry(Point, 4326) NOT NULL", text)
        self.assertIn("id bigserial PRIMARY KEY", text)
        self.assertTrue(any("gist" in s.as_string(None) for s in tables.index_statements(t)))


@unittest.skipUnless(PG_HOST, "به PostgreSQL آزمون نیاز دارد (TEST_PG_HOST)")
@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class RealTests(BaseCase):
    """روی PostgreSQL واقعی: ساخت، تکرارپذیری، افزودن ستون، تعارض، و مسیر کامل دریافت داده."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        registry.register("mon", "پایش", kind="custom")
        self.addCleanup(registry.remove_plugin, "mon")
        self.page = pagekit.parse_page("mon", PAGE)
        self.kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                       password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        with psycopg.connect(dbname="postgres", **self.kw) as c:
            c.execute("DROP DATABASE IF EXISTS pagekit_tbl")
            c.execute("CREATE DATABASE pagekit_tbl")
        kw = self.kw

        def conn():
            c = psycopg.connect(dbname="pagekit_tbl", **kw)
            c.autocommit = False
            return c

        @contextmanager
        def connect(ws, **kw2):
            c = conn()
            try:
                yield c
            finally:
                c.close()

        class Cat:
            def tables(self_):
                with conn() as c:
                    rows = c.execute("select schemaname, tablename from pg_tables where schemaname='public'").fetchall()
                return [SimpleNamespace(schema=a, name=b, kind="r", oid=0) for a, b in rows]

            def columns(self_, t):
                with conn() as c:
                    rows = c.execute("select column_name, is_generated, identity_generation from information_schema.columns "
                                     "where table_schema='public' and table_name=%s", [t.name]).fetchall()
                return [{"name": n, "generated": g == "ALWAYS", "identity": "a" if i == "ALWAYS" else "", "spatial": False} for n, g, i in rows]

        for target, val in (("kernel.pagekit.get", lambda a, b: self.page if (a, b) == ("mon", "live") else None),
                            ("kernel.tenantdb.catalog", lambda ws: Cat()), ("kernel.tenantdb.connect", connect)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(entitlements.invalidate)
        self.db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])

    def cols(self, name="mon_points"):
        with psycopg.connect(dbname="pagekit_tbl", **self.kw) as c:
            return {r[0]: (r[1], r[2]) for r in c.execute(
                "select column_name, data_type, is_nullable from information_schema.columns where table_name=%s", [name]).fetchall()}

    def test_creates_table_once_and_is_idempotent(self):
        n = tables.ensure(self.db, "mon", self.page.tables)
        self.assertEqual(n, 1)
        cols = self.cols()
        self.assertEqual(set(cols), {"id", "device", "lat", "lon", "speed", "at"})
        self.assertEqual(cols["device"][1], "NO")  # required ← NOT NULL
        self.assertEqual(cols["speed"][1], "YES")
        self.assertEqual(tables.ensure(self.db, "mon", self.page.tables), 0)  # دوباره: بی‌اثر
        self.assertEqual(PluginTable.objects.filter(plugin_id="mon", workspace_id=self.db.pk).count(), 1)

    def test_default_now_and_index(self):
        tables.ensure(self.db, "mon", self.page.tables)
        with psycopg.connect(dbname="pagekit_tbl", **self.kw) as c:
            c.execute("insert into mon_points(device, lat, lon) values ('a', 1, 2)")
            self.assertIsNotNone(c.execute("select at from mon_points").fetchone()[0])
            idx = [r[0] for r in c.execute("select indexname from pg_indexes where tablename='mon_points'").fetchall()]
        self.assertTrue(any(i.endswith("_ix1") for i in idx), idx)

    def test_new_version_adds_columns_only(self):
        tables.ensure(self.db, "mon", self.page.tables)
        newer = pagekit.parse_page("mon", {**PAGE, "tables": [{**TBL, "columns": TBL["columns"] + [{"name": "battery", "type": "integer", "required": True}]}]})
        self.assertEqual(tables.ensure(self.db, "mon", newer.tables), 1)
        cols = self.cols()
        self.assertIn("battery", cols)
        self.assertEqual(cols["battery"][1], "YES")  # ستون تازه همیشه nullable (جدول پر قفل نشود)
        # نسخه‌ای که ستونی را حذف کرده، چیزی را حذف نمی‌کند
        older = pagekit.parse_page("mon", {**PAGE, "tables": [{**TBL, "indexes": [], "columns": TBL["columns"][:2]}]})
        tables.ensure(self.db, "mon", older.tables)
        self.assertIn("speed", self.cols())

    def test_foreign_table_with_same_name_is_not_touched(self):
        with psycopg.connect(dbname="pagekit_tbl", **self.kw) as c:
            c.execute("create table mon_points (customer_data text)")
            c.execute("insert into mon_points values ('مهم')")
        with self.assertRaises(tables.TableError):
            tables.ensure(self.db, "mon", self.page.tables)
        self.assertEqual(set(self.cols()), {"customer_data"})
        self.assertFalse(PluginTable.objects.exists())

    def test_dropped_table_is_restored(self):
        tables.ensure(self.db, "mon", self.page.tables)
        with psycopg.connect(dbname="pagekit_tbl", **self.kw) as c:
            c.execute("drop table mon_points")
        self.assertEqual(self.cols(), {})
        restored = []
        self.assertEqual(tables.ensure(self.db, "mon", self.page.tables, restored), 1)
        self.assertEqual(restored, ["mon_points"])
        self.assertEqual(set(self.cols()), {"id", "device", "lat", "lon", "speed", "at"})
        self.assertEqual(tables.ensure(self.db, "mon", self.page.tables), 0)  # سالم: بی‌اثر

    def test_dropped_column_is_restored(self):
        tables.ensure(self.db, "mon", self.page.tables)
        with psycopg.connect(dbname="pagekit_tbl", **self.kw) as c:
            c.execute("alter table mon_points drop column speed")
        restored = []
        tables.ensure(self.db, "mon", self.page.tables, restored)
        self.assertEqual(restored, ["mon_points"])
        self.assertIn("speed", self.cols())

    def test_owners(self):
        tables.ensure(self.db, "mon", self.page.tables)
        self.assertEqual(tables.owners(self.db, "public", "mon_points"), ["mon"])
        self.assertEqual(tables.owners(self.db, "public", "other"), [])
        self.assertEqual(tables.owners(self.db, "x", "mon_points"), [])

    def test_another_plugin_cannot_adopt_my_table(self):
        tables.ensure(self.db, "mon", self.page.tables)
        PluginTable.objects.all().delete()  # ردپا نیست ⇒ جدول «از آن کسی نیست»
        with self.assertRaises(tables.TableError):
            tables.ensure(self.db, "mon", self.page.tables)

    def test_database_failure_is_short_message(self):
        with mock.patch("kernel.tenantdb.connect", side_effect=RuntimeError("secret detail\nmore")):
            with self.assertRaises(tables.TableError) as cm:
                tables.ensure(self.db, "mon", self.page.tables)
        self.assertNotIn("secret", str(cm.exception))

    def test_page_view_provisions_and_ingest_works_without_manual_sql(self):
        entitlements.invalidate()
        self.client.force_login(self.user)
        with mock.patch("kernel.pagekit.render_block", lambda *a, **k: {"kind": "text", "title": "", "width": 12, "hint": "", "error": "", "paras": ["x"]}):
            r = self.client.get(reverse("kernel:page", args=[self.db.pk, "mon", "live"]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("device", self.cols())  # جدول ساخته شد
        # دریافت داده‌ی دستگاه روی پایگاه دیگر که صفحه‌اش هرگز باز نشده: جدول خودکار ساخته می‌شود
        with psycopg.connect(dbname="pagekit_tbl", **self.kw) as c:
            c.execute("drop table mon_points")
        PluginTable.objects.all().delete()
        _row, raw = ingest.create_token(self.db, "mon", "live", "feed", self.user)
        r = self.client.post(reverse("kernel:ingest"), data=json.dumps([{"device": "d1", "lat": 35.7, "lon": 51.4}]),
                             content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True, "inserted": 1}))
        with psycopg.connect(dbname="pagekit_tbl", **self.kw) as c:
            self.assertEqual(c.execute("select device, lat from mon_points").fetchall(), [("d1", 35.7)])

    def test_conflict_surfaces_as_503_on_ingest_and_message_on_page(self):
        with psycopg.connect(dbname="pagekit_tbl", **self.kw) as c:
            c.execute("create table mon_points (customer_data text)")
        _row, raw = ingest.create_token(self.db, "mon", "live", "feed", self.user)
        r = self.client.post(reverse("kernel:ingest"), data=json.dumps({"device": "d", "lat": 1, "lon": 2}),
                             content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("customer_data", json.dumps(r.json(), ensure_ascii=False))
