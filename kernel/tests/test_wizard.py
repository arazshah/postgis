"""ویزارد ساخت پلاگین: مشخصات ساخت‌یافته ← صفحه‌ی TOML (ADR-0008 مرحله‌ی ۳)."""
import copy
import os
import tomllib
import unittest

import psycopg
from django.test import SimpleTestCase

from kernel import pagekit, wizard

PG_HOST = os.environ.get("TEST_PG_HOST", "")
TABLE = {"name": "mon_points", "columns": [
    {"name": "device", "type": "text", "required": True}, {"name": "lat", "type": "double", "required": True},
    {"name": "lon", "type": "double", "required": True}, {"name": "speed", "type": "double"},
    {"name": "at", "type": "timestamptz", "auto_now": True}], "indexes": [["device", "at"]]}


def spec(**over):
    page = {"key": "p1", "title": "پایش", "icon": "pulse", "group": "data", "need": "editor", "refresh": 15, "blocks": [
        {"kind": "kpi", "title": "دستگاه فعال", "table": "mon_points", "agg": "count", "distinct": "device",
         "since_col": "at", "since_minutes": 5, "unit": "دستگاه", "width": "third"},
        {"kind": "kpi", "title": "میانگین سرعت", "table": "mon_points", "agg": "avg", "column": "speed", "width": "third"},
        {"kind": "bars", "title": "رکورد هر دستگاه", "table": "mon_points", "label": "device", "agg": "count"},
        {"kind": "map", "title": "موقعیت", "table": "mon_points", "lat": "lat", "lon": "lon", "props": ["device", "speed"],
         "latest_by": "device", "time_col": "at"},
        {"kind": "table", "title": "آخرین‌ها", "table": "mon_points", "columns": ["device", "speed", "at"], "order_by": "at", "limit": 20},
        {"kind": "text", "title": "راهنما", "text": "داده هر ۱۵ ثانیه تازه می‌شود."},
        {"kind": "ingest", "title": "دریافت از دستگاه", "table": "mon_points", "fields": ["device", "lat", "lon", "speed"]},
        {"kind": "form", "title": "ثبت دستی", "table": "mon_points", "fields": ["device", "lat", "lon"]}]}
    return copy.deepcopy({"tables": [TABLE], "pages": [page], **over})


class TomlTests(SimpleTestCase):
    def test_roundtrip(self):
        page = {"key": "p1", "title": 'عنوان با "نقل‌قول" و \\', "n": 3, "f": 1.5, "ok": True, "arr": ["a", "b"],
                "blocks": [{"kind": "text", "text": "خط۱\nخط۲"}],
                "tables": [{"name": "x_t", "columns": [{"name": "a", "type": "text", "required": True}], "indexes": [["a"]]}]}
        back = tomllib.loads(wizard.toml_dumps(page))
        self.assertEqual(back["title"], page["title"])
        self.assertEqual(back["blocks"], page["blocks"])
        self.assertEqual(back["tables"][0]["columns"][0]["required"], True)
        self.assertEqual(back["tables"][0]["indexes"], [["a"]])


class CompileTests(SimpleTestCase):
    def test_full_page_compiles_and_passes_the_kit_validation(self):
        out = wizard.compile_pages("mon", spec())
        text = out["p1"]
        page = pagekit.parse_page("mon", tomllib.loads(text))
        self.assertEqual([b.kind for b in page.blocks], ["kpi", "kpi", "bars", "map", "table", "text"])
        self.assertEqual((page.ingests[0].table, page.forms[0].table, page.tables[0].name), ("mon_points",) * 3)
        self.assertEqual(page.need, "editor")
        self.assertEqual(page.refresh, 15)
        self.assertIn('count(distinct "device")', page.blocks[0].sql)
        self.assertIn("interval '5 minutes'", page.blocks[0].sql)

    def test_actions_force_editor(self):
        s = spec()
        s["pages"][0]["need"] = "viewer"
        page = pagekit.parse_page("mon", tomllib.loads(wizard.compile_pages("mon", s)["p1"]))
        self.assertEqual(page.need, "editor")

    def test_auto_columns_are_not_writable_fields(self):
        page = pagekit.parse_page("mon", tomllib.loads(wizard.compile_pages("mon", spec())["p1"]))
        self.assertNotIn("at", [f.name for f in page.ingests[0].fields])
        s = spec()
        s["pages"][0]["blocks"][-2]["fields"] = ["device", "at"]
        with self.assertRaises(wizard.WizardError):
            wizard.compile_pages("mon", s)

    def test_rejections(self):
        def bad(mutate, msg=None):
            s = spec()
            mutate(s)
            with self.assertRaises(wizard.WizardError) as cm:
                wizard.compile_pages("mon", s)
            if msg:
                self.assertIn(msg, str(cm.exception))

        b = lambda s: s["pages"][0]["blocks"]  # noqa: E731
        bad(lambda s: s["tables"][0].update(name="points"), "mon_")
        bad(lambda s: b(s)[0].update(table="other"), "جدول")
        bad(lambda s: b(s)[0].update(distinct="nope"), "یکتا")
        bad(lambda s: b(s)[1].update(column="device"), "نوع")  # avg روی متن
        bad(lambda s: b(s)[0].update(since_minutes="x"), "عدد")
        bad(lambda s: b(s)[0].update(since_minutes=0), "بازه")
        bad(lambda s: b(s)[4].update(columns=["nope"]), "نیست")
        bad(lambda s: b(s)[4].update(limit=1000), "۲۰۰")
        bad(lambda s: b(s)[3].update(lat="device"), "نوع")
        bad(lambda s: b(s)[2].update(label="nope"), "برچسب")
        bad(lambda s: s["pages"][0].update(blocks=[b(s)[6]]), "بلوک نمایشی")
        bad(lambda s: s.update(pages=[{**s["pages"][0], "key": f"p{i}"} for i in range(8)]), "حداکثر")

    def test_names_cannot_smuggle_sql(self):
        s = spec()
        s["tables"][0]["columns"][0]["name"] = 'device"; drop table x; --'
        with self.assertRaises(wizard.WizardError):
            wizard.compile_pages("mon", s)
        s = spec()
        s["pages"][0]["blocks"][4]["order_by"] = 'at"; drop table x; --'
        with self.assertRaises(wizard.WizardError):
            wizard.compile_pages("mon", s)
        with self.assertRaises(wizard.WizardError):
            wizard.q('a"b')

    def test_page_without_display_block_is_rejected_and_sql_block_allowed(self):
        s = spec()
        s["pages"][0]["blocks"] = [{"kind": "sql", "title": "x", "display": "table", "sql": "select 1 as n"}]
        page = pagekit.parse_page("mon", tomllib.loads(wizard.compile_pages("mon", s)["p1"]))
        self.assertEqual(page.blocks[0].sql, "select 1 as n")

    def test_invalid_plugin_id(self):
        with self.assertRaises(wizard.WizardError):
            wizard.compile_pages("Bad-Id", spec())

    def test_next_page_key(self):
        self.assertEqual(wizard.next_page_key({"pages": []}), "p1")
        self.assertEqual(wizard.next_page_key({"pages": [{"key": "p1"}, {"key": "p3"}]}), "p2")


@unittest.skipUnless(PG_HOST, "به PostgreSQL آزمون نیاز دارد (TEST_PG_HOST)")
class GeneratedSqlRunsTests(SimpleTestCase):
    """SQL ساخته‌شده روی PostgreSQL واقعی درست اجرا می‌شود و نتیجه‌ی درست می‌دهد."""

    def test_blocks_run(self):
        kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                  password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        with psycopg.connect(dbname="postgres", **kw) as c:
            c.execute("DROP DATABASE IF EXISTS pagekit_wiz")
            c.execute("CREATE DATABASE pagekit_wiz")
        with psycopg.connect(dbname="pagekit_wiz", **kw) as c:
            try:
                c.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            except psycopg.Error:
                self.skipTest("PostGIS در این PostgreSQL نیست")
            c.execute("CREATE TABLE mon_points (id bigserial primary key, device text, lat double precision, lon double precision, "
                      "speed double precision, at timestamptz default now())")
            c.execute("INSERT INTO mon_points(device, lat, lon, speed) VALUES ('a', 35.7, 51.4, 10), ('a', 35.8, 51.5, 20), ('b', 36, 52, 30)")
            page = pagekit.parse_page("mon", tomllib.loads(wizard.compile_pages("mon", spec())["p1"]))
            res = {}
            for blk in page.blocks:
                if blk.kind != "text":
                    res[blk.title] = c.execute(blk.sql).fetchall()
        self.assertEqual(res["دستگاه فعال"], [(2,)])
        self.assertEqual(res["میانگین سرعت"], [(20.0,)])
        self.assertEqual(dict(res["رکورد هر دستگاه"]), {"a": 2, "b": 1})
        self.assertEqual(len(res["موقعیت"]), 2)  # آخرین موقعیت هر دستگاه
        self.assertEqual(len(res["آخرین‌ها"]), 3)
