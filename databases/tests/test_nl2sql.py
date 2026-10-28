"""پرسش فارسی در کنسول SQL: تجزیه پاسخ مدل، دسته‌بندی دستور، نمای کنسول و (با PostGIS واقعی) ساخت و سنجش SQL."""
import json
import os
import unittest
import uuid
from unittest import mock

import psycopg
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from analysis.models import LlmConfig
from databases import nl2sql, services
from databases.explorer import Explorer, TableRef
from databases.models import DatabaseServer
from databases.provisioner import Provisioner
from databases.tests.test_services import BaseCase
from databases.tests.test_workspace_nav import STORAGES

PG_HOST = os.environ.get("TEST_PG_HOST", "")


class ParseTests(SimpleTestCase):
    def test_parse_json_with_fence_and_text(self):
        d = nl2sql._parse('بفرمایید:\n```json\n{"sql": "SELECT 1;", "kind": "read"}\n```')
        self.assertEqual(nl2sql.clean_sql(d["sql"]), "SELECT 1")

    def test_parse_plain_sql_block(self):
        d = nl2sql._parse("```sql\nSELECT count(*) FROM roads\n```")
        self.assertEqual(d["sql"].strip(), "SELECT count(*) FROM roads")

    def test_parse_garbage(self):
        with self.assertRaises(nl2sql.NLError):
            nl2sql._parse("نمی‌دانم")

    def test_classify(self):
        self.assertEqual(nl2sql.classify("SELECT count(*) FROM a"), "read")
        self.assertEqual(nl2sql.classify("-- note\nWITH x AS (SELECT 1) SELECT * FROM x"), "read")
        self.assertEqual(nl2sql.classify("WITH d AS (DELETE FROM a RETURNING *) SELECT 1"), "modify")
        self.assertEqual(nl2sql.classify("CREATE TABLE pts_in AS SELECT * FROM a"), "create")
        self.assertEqual(nl2sql.classify("UPDATE a SET x = 1 WHERE id = 2"), "modify")

    def test_created_table(self):
        self.assertEqual(nl2sql.created_table('CREATE TABLE "Schools_In" AS SELECT 1'), ("public", "Schools_In"))
        self.assertEqual(nl2sql.created_table("create table if not exists gis.zone_pts as select 1"),
                         ("gis", "zone_pts"))
        self.assertIsNone(nl2sql.created_table("SELECT 1"))

    def test_warnings(self):
        self.assertTrue(nl2sql._warnings("DROP TABLE a", "modify", None, set()))
        self.assertIn("WHERE", nl2sql._warnings("DELETE FROM a", "modify", None, set())[0])
        self.assertEqual(nl2sql._warnings("SELECT 1", "read", None, set()), [])

    def test_fold_and_literals(self):
        self.assertEqual(nl2sql.fold("منطقه 6 كرج ٧"), "منطقه ۶ کرج ۷")
        lits = nl2sql.sql_literals("SELECT * FROM z WHERE name = 'منطقه 6' AND t ILIKE '%O''Brien%' AND d > '2024-01-01'")
        self.assertEqual(lits, ["منطقه 6", "O'Brien"])

    def test_question_words_skip_common(self):
        words = nl2sql.question_words("نقاطی که داخل لایه پلیگونی با نام کرج هستند را استخراج کن")
        self.assertIn("کرج", words)
        self.assertNotIn("لایه", words)
        self.assertNotIn("داخل", words)


def _tables():
    return [TableRef("public", "zones", 1, "r", 22, 0, [{"column": "geom", "type": "MULTIPOLYGON", "srid": 4326,
                                                          "geography": False}]),
            TableRef("public", "schools", 2, "r", 900, 0, [{"column": "geom", "type": "POINT", "srid": 4326,
                                                             "geography": False}])]


@override_settings(STORAGES=STORAGES)
class ConsoleViewTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "nlview", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        p = mock.patch.object(Explorer, "tables", return_value=_tables())
        p.start()
        self.addCleanup(p.stop)

    def test_page_without_key_shows_setup(self):
        r = self.client.get(reverse("databases:explore_sql", args=[self.db.pk]) + "?mode=nl")
        self.assertContains(r, 'data-dialog-open="nl-key"')
        self.assertContains(r, "پرسش فارسی")
        self.assertContains(r, 'data-mode="nl"')

    def test_page_with_key_shows_form_and_examples(self):
        cfg = LlmConfig(user=self.user)
        cfg.set_key("sk-test-123456")
        cfg.save()
        r = self.client.get(reverse("databases:explore_sql", args=[self.db.pk]))
        self.assertContains(r, "data-nl-form")
        self.assertContains(r, "نقاط schools که داخل zones هستند")

    def test_save_key(self):
        url = reverse("databases:explore_sql_key", args=[self.db.pk])
        r = self.client.post(url, {"base_url": "http://x.ir/v1", "model": "gpt-4o", "api_key": "k"})
        self.assertFalse(LlmConfig.objects.filter(user=self.user).exists())  # فقط https
        self.client.post(url, {"base_url": "https://api.avalai.ir/v1/", "model": "gpt-4o-mini", "api_key": "sk-abc12345"})
        cfg = LlmConfig.objects.get(user=self.user)
        self.assertEqual((cfg.base_url, cfg.model, cfg.get_key()), ("https://api.avalai.ir/v1", "gpt-4o-mini", "sk-abc12345"))
        self.client.post(url, {"action": "delete"})
        self.assertFalse(LlmConfig.objects.filter(user=self.user).exists())
        self.assertEqual(r.status_code, 302)

    def test_ask_returns_draft_and_auto_run_only_for_reads(self):
        url = reverse("databases:explore_sql_ask", args=[self.db.pk])
        with mock.patch.object(nl2sql, "generate", return_value=nl2sql.Draft("SELECT count(*) FROM schools")):
            d = self.client.post(url, {"text": "چند مدرسه داریم؟"}).json()
        self.assertTrue(d["ok"] and d["auto_run"])
        draft = nl2sql.Draft("CREATE TABLE s_in AS SELECT 1", kind="create", table="s_in")
        with mock.patch.object(nl2sql, "generate", return_value=draft):
            d = self.client.post(url, {"text": "مدارس داخل منطقه را لایه جدید کن"}).json()
        self.assertTrue(d["writes"])
        self.assertFalse(d["auto_run"])

    def test_ask_error_is_persian_json(self):
        r = self.client.post(reverse("databases:explore_sql_ask", args=[self.db.pk]), {"text": "چند مدرسه داریم؟"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("کلید مدل زبانی", r.json()["error"])

    def test_empty_result_offers_why_and_map_is_rendered(self):
        url = reverse("databases:explore_sql", args=[self.db.pk])
        cfg = LlmConfig(user=self.user)
        cfg.set_key("sk-test-123456")
        cfg.save()
        empty = {"columns": ["id"], "rows": [], "truncated": False, "rowcount": 0, "status": "SELECT 0", "elapsed_ms": 3}
        with mock.patch.object(Explorer, "run_sql", return_value=empty):
            r = self.client.post(url, {"query": "SELECT id FROM zones WHERE name = 'x'"})
        self.assertContains(r, "data-why-btn")
        geo = {"columns": ["id", "geom"], "rows": [["1", "0101…"]], "truncated": False, "rowcount": 1,
               "status": "SELECT 1", "elapsed_ms": 3, "geom_column": "geom",
               "geojson": {"type": "FeatureCollection", "features": [
                   {"type": "Feature", "geometry": {"type": "Point", "coordinates": [51.4, 35.7]}, "properties": {"id": "1"}}]}}
        with mock.patch.object(Explorer, "run_sql", return_value=geo):
            r = self.client.post(url, {"query": "SELECT id, geom FROM schools"})
        self.assertContains(r, 'id="sql-map"')
        self.assertContains(r, 'id="sql-geojson"')
        self.assertContains(r, "sql-map.js")
        self.assertNotContains(r, "data-why-btn")
        # کوئری تغییر داده «چرا خالی است» ندارد
        with mock.patch.object(Explorer, "run_sql", return_value=empty):
            r = self.client.post(url, {"query": "DELETE FROM zones WHERE id = 0 RETURNING id"})
        self.assertNotContains(r, "data-why-btn")

    def test_why_endpoint(self):
        url = reverse("databases:explore_sql_why", args=[self.db.pk])
        out = {"reason": "نام منطقه با رقم فارسی ثبت شده است.", "sql": "SELECT 1", "explanation": "", "rows": 3}
        with mock.patch.object(nl2sql, "diagnose_empty", return_value=out) as m:
            d = self.client.post(url, {"query": "SELECT 1 WHERE false", "text": "x"}).json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["rows"], 3)
        self.assertEqual(m.call_args.args[2], "SELECT 1 WHERE false")
        d = self.client.post(url, {"query": "DELETE FROM zones"})
        self.assertEqual(d.status_code, 400)

    def test_viewer_of_other_db_gets_404(self):
        other = User.objects.create_user("09120000077")
        self.client.force_login(other)
        r = self.client.post(reverse("databases:explore_sql_ask", args=[self.db.pk]), {"text": "سلام دنیا"})
        self.assertEqual(r.status_code, 404)


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
class NL2SQLIntegrationTests(TestCase):
    def setUp(self):
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000098")
        self.db = services.create_database(self.user, f"nl_{uuid.uuid4().hex[:8]}", "Explorer-Pass-1", ["postgis"])
        self.addCleanup(lambda: services.delete_database(self.db))
        with psycopg.connect(host=server.host, port=server.port, user=self.db.role_name, password="Explorer-Pass-1",
                             dbname=self.db.db_name, autocommit=True) as c:
            c.execute("CREATE TABLE zones(id serial PRIMARY KEY, name text, geom geometry(Polygon, 4326))")
            c.execute("INSERT INTO zones(name, geom) VALUES ('منطقه یک', ST_MakeEnvelope(51, 35, 51.5, 35.5, 4326)),"
                      " ('منطقه دو', ST_MakeEnvelope(52, 35, 52.5, 35.5, 4326)),"
                      " ('منطقه ۶', ST_MakeEnvelope(51, 35, 51.25, 35.5, 4326))")
            c.execute("CREATE TABLE wells(id int, geom geometry(Point, 32639))")
            c.execute("INSERT INTO wells VALUES (1, ST_SetSRID(ST_MakePoint(535000, 3950000), 32639))")
            c.execute("CREATE TABLE schools(id serial PRIMARY KEY, title text, geom geometry(Point, 4326))")
            c.execute("INSERT INTO schools(title, geom) SELECT 'مدرسه ' || g, ST_SetSRID(ST_MakePoint(51 + g * 0.1,"
                      " 35.2), 4326) FROM generate_series(1, 12) g")

    def test_describe_includes_matching_values(self):
        schema, values, names = nl2sql.describe(Explorer(self.db), "نقاط داخل منطقه دو")
        self.assertIn("zones", names)
        self.assertIn("geometry(POLYGON, SRID 4326)", schema)
        self.assertIn("'منطقه دو'", values)
        schema2, values2, _ = nl2sql.describe(Explorer(self.db), "نقاط داخل منطقه دو", share_values=False)
        self.assertEqual(values2, "")

    def test_generate_retries_on_error_and_runs(self):
        replies = iter([
            json.dumps({"sql": "SELECT count(*) FROM school", "kind": "read"}),
            json.dumps({"sql": "CREATE TABLE schools_in_two AS SELECT s.* FROM schools s JOIN zones z "
                               "ON ST_Within(s.geom, z.geom) WHERE z.name = 'منطقه دو'", "kind": "create",
                        "explanation": "مدارس داخل منطقه دو در جدول تازه"}),
        ])
        seen = []

        def chat(messages):
            seen.append(messages[-1]["content"])
            return next(replies)

        d = nl2sql.generate(self.db, self.user, "مدارس داخل منطقه دو را لایه جدید کن", chat=chat)
        self.assertTrue(d.valid)
        self.assertEqual((d.kind, d.table, d.attempts), ("create", "schools_in_two", 2))
        self.assertIn("school", seen[1])  # خطای پایگاه به مدل برگشت
        res = Explorer(self.db).run_sql(d.sql, allow_write=True)
        self.assertEqual(res["rowcount"], 2)  # 52.1 و 52.2؛ 52.0 روی مرز است
        # EXPLAIN چیزی نساخت؛ فقط اجرای کاربر جدول را ساخت
        self.assertIn("schools_in_two", [t.name for t in Explorer(self.db).tables()])

    def test_existing_table_name_is_rejected(self):
        replies = iter([json.dumps({"sql": "CREATE TABLE zones AS SELECT 1", "kind": "create"})] * 2)
        d = nl2sql.generate(self.db, self.user, "یک جدول بساز", chat=lambda m: next(replies))
        self.assertFalse(d.valid)
        self.assertTrue(d.warnings)

    def test_run_sql_returns_map_in_wgs84(self):
        res = Explorer(self.db).run_sql("SELECT id, geom AS g FROM wells")
        self.assertEqual(res["geom_column"], "g")
        f = res["geojson"]["features"][0]
        lon, lat = f["geometry"]["coordinates"]
        self.assertAlmostEqual(lon, 51.39, places=1)
        self.assertAlmostEqual(lat, 35.69, places=1)
        self.assertEqual(f["properties"], {"id": "1"})
        self.assertEqual(res["rows"], [["1", "POINT(535000 3950000)"]])  # خلاصه WKT به‌جای هگز
        self.assertNotIn("geojson", Explorer(self.db).run_sql("SELECT count(*) FROM wells"))
        # geography و نتیجه بدون ردیف
        geog = Explorer(self.db).run_sql("SELECT geom::geography, geom AS g2 FROM zones")
        self.assertIn("geojson", geog)
        self.assertEqual(len(geog["geojson"]["features"]), 3)
        self.assertTrue(all(r[0].startswith("POLYGON((") and r[1].startswith("POLYGON((") for r in geog["rows"]))
        self.assertNotIn("geojson", Explorer(self.db).run_sql("SELECT geom FROM zones WHERE false"))

    def test_diagnose_empty_finds_persian_digit_value(self):
        q = "SELECT s.* FROM schools s JOIN zones z ON ST_Within(s.geom, z.geom) WHERE z.name = 'منطقه 6'"
        self.assertEqual(Explorer(self.db).run_sql(q)["rows"], [])
        seen = {}

        def chat(messages):
            seen["prompt"] = messages[0]["content"]
            return json.dumps({"reason": "در داده رقم فارسی است.", "explanation": "رقم ۶ فارسی شد.",
                               "sql": q.replace("'منطقه 6'", "'منطقه ۶'")})

        d = nl2sql.diagnose_empty(self.db, self.user, q, "مدارس منطقه ۶", chat=chat)
        self.assertIn("'منطقه ۶'", seen["prompt"])  # مقدار نزدیک واقعی پیدا شد
        self.assertIn("schools: 12 rows", seen["prompt"])
        self.assertEqual(d["rows"], 2)  # 51.1 و 51.2
        self.assertIn("منطقه ۶", d["sql"])

    def test_diagnose_drops_invalid_fix(self):
        d = nl2sql.diagnose_empty(self.db, self.user, "SELECT * FROM zones WHERE false", "",
                                  chat=lambda m: json.dumps({"reason": "شرط همیشه نادرست است.", "sql": "SELECT nope FROM zones"}))
        self.assertEqual(d["sql"], "")
        self.assertEqual(d["reason"], "شرط همیشه نادرست است.")
