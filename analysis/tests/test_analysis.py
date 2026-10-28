"""ابزارهای تحلیل بدون SQL و پرسش فارسی (s3geo با پاسخ ثابت مدل زبانی) روی PostGIS واقعی."""
import json
import os
import shutil
import unittest
import uuid
from pathlib import Path

import psycopg
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from analysis import ask, tools
from analysis.models import LlmConfig, Question, ToolRun
from databases import gdal
from databases import services as db_services
from databases.models import DatabaseServer
from databases.provisioner import Provisioner
from jobs.models import Job

PG_HOST = os.environ.get("TEST_PG_HOST", "")
HAS_GDAL = bool(shutil.which("ogr2ogr"))
SAMPLE = Path(__file__).resolve().parents[2] / "classroom" / "sample"
try:
    import s3geo  # noqa: F401
    HAS_S3GEO = True
except ImportError:
    HAS_S3GEO = False


@unittest.skipUnless(PG_HOST and HAS_GDAL, "TEST_PG_HOST or ogr2ogr missing")
@override_settings(ALLOWED_HOSTS=["testserver"])
class AnalysisTests(TestCase):
    def setUp(self):
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000041")
        self.db = db_services.create_database(self.user, f"an_{uuid.uuid4().hex[:8]}", "Anal-Pass-123", ["postgis"])
        self.addCleanup(self._drop)
        self.kw = dict(host=server.host, port=server.port, user=self.db.role_name, password="Anal-Pass-123",
                       dbname=self.db.db_name, autocommit=True)
        for name in ("schools", "metro_stations", "parks"):
            gdal.import_layer(self.db, SAMPLE / f"{name}.geojson",
                              {"name": name, "table": name, "mode": "create", "geom_type": ""}, None)
        with psycopg.connect(**self.kw) as c:
            # یک لایه با SRID متری تا تبدیل‌ها آزموده شوند
            c.execute("CREATE TABLE districts AS SELECT 1 AS id, 'مرکز' AS name, "
                      "ST_Transform(ST_Buffer(ST_SetSRID(ST_MakePoint(51.40, 35.69), 4326)::geography, 6000)::geometry,"
                      " 32639)::geometry(Polygon, 32639) AS geom")
        self.client.force_login(self.user)

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _sql(self, q):
        with psycopg.connect(**self.kw) as c:
            return c.execute(q).fetchall()

    def _sql_exec(self, q):
        with psycopg.connect(**self.kw) as c:
            c.execute(q)

    def test_tools(self):
        r = tools.run(self.db, "buffer", {"layer": "public.metro_stations", "distance": "۵۰۰", "output": "metro_500"})
        self.assertEqual(r["rows"], self._sql("SELECT count(*) FROM metro_stations")[0][0])
        area = self._sql("SELECT avg(ST_Area(geom::geography)) FROM metro_500")[0][0]
        self.assertAlmostEqual(area / 785398, 1, delta=0.03)  # π·500²
        owner = self._sql("SELECT tableowner FROM pg_tables WHERE tablename = 'metro_500'")[0][0]
        self.assertEqual(owner, self.db.role_name)

        r = tools.run(self.db, "buffer", {"layer": "public.metro_stations", "distance": "800", "dissolve": "on",
                                          "output": "metro_zone"})
        self.assertEqual(r["rows"], 1)

        r = tools.run(self.db, "nearest", {"layer": "public.schools", "other": "public.metro_stations", "label": "name",
                                           "output": "school_metro"})
        self.assertEqual(r["rows"], self._sql("SELECT count(*) FROM schools")[0][0])
        mn, mx = self._sql("SELECT min(distance_m), max(distance_m) FROM school_metro")[0]
        self.assertGreaterEqual(mn, 0)
        self.assertLess(mx, 20000)
        self.assertTrue(self._sql("SELECT bool_and(nearest_name IS NOT NULL) FROM school_metro")[0][0])

        r = tools.run(self.db, "count", {"layer": "public.districts", "other": "public.schools", "output": "d_count"})
        n = self._sql("SELECT point_count, ST_SRID(geom) FROM d_count")[0]
        self.assertGreater(n[0], 10)
        self.assertEqual(n[1], 4326)

        r = tools.run(self.db, "hexbin", {"layer": "public.schools", "size": "1000", "output": "school_hex"})
        self.assertEqual(self._sql("SELECT sum(count) FROM school_hex")[0][0],
                         self._sql("SELECT count(*) FROM schools")[0][0])
        # ستون هندسه هر خروجی نوع و SRID دارد؛ وگرنه نقشه و QGIS آن را بدون مختصات می‌بینند
        cols = dict(((t, (g, s)) for t, g, s in self._sql(
            "SELECT f_table_name, type, srid FROM geometry_columns WHERE f_table_name IN "
            "('metro_500', 'metro_zone', 'school_metro', 'd_count', 'school_hex')")))
        self.assertEqual(cols, {"metro_500": ("POLYGON", 4326), "metro_zone": ("MULTIPOLYGON", 4326),
                                "school_metro": ("POINT", 4326), "d_count": (cols["d_count"][0], 4326),
                                "school_hex": ("POLYGON", 4326)})
        self.assertIn(cols["d_count"][0], ("POLYGON", "MULTIPOLYGON"))

        with self.assertRaisesMessage(tools.ToolError, "وجود دارد"):
            tools.run(self.db, "hexbin", {"layer": "public.schools", "size": "1000", "output": "school_hex"})
        tools.run(self.db, "hexbin", {"layer": "public.schools", "size": "2000", "output": "school_hex",
                                      "replace": "on"})
        with self.assertRaisesMessage(tools.ToolError, "حروف کوچک"):
            tools.run(self.db, "buffer", {"layer": "public.schools", "distance": "5", "output": "Bad name"})
        with self.assertRaisesMessage(tools.ToolError, "بین"):
            tools.run(self.db, "buffer", {"layer": "public.schools", "distance": "0", "output": "x"})
        with self.assertRaisesMessage(tools.ToolError, "routing"):
            tools.run(self.db, "isochrone", {"lon": "51.4", "lat": "35.7", "distance": "500", "output": "iso"})
        with self.assertRaisesMessage(tools.ToolError, "POLYGON"):
            tools.run(self.db, "count", {"layer": "public.schools", "other": "public.parks", "output": "bad"})

    def _zones(self):
        self._sql_exec(
            "CREATE TABLE zones(id serial PRIMARY KEY, name text, geom geometry(Polygon, 4326));"
            "INSERT INTO zones(name, geom) VALUES ('اول', ST_MakeEnvelope(0, 0, 2, 2, 4326)),"
            " ('دوم', ST_MakeEnvelope(2, 0, 4, 2, 4326));"
            "CREATE TABLE landuse(id serial PRIMARY KEY, kind text, geom geometry(Polygon, 4326));"
            "INSERT INTO landuse(kind, geom) VALUES ('مسکونی', ST_MakeEnvelope(0, 0, 1, 2, 4326)),"
            " ('تجاری', ST_MakeEnvelope(1, 0, 3, 2, 4326)), ('مسکونی', ST_MakeEnvelope(3, 0, 4, 2, 4326));"
            "CREATE TABLE ads(id serial PRIMARY KEY, price int, note text, geom geometry(Point, 4326));"
            "INSERT INTO ads(price, note, geom) VALUES (10, 'a', ST_SetSRID(ST_MakePoint(0.5, 0.5), 4326)),"
            " (20, 'b', ST_SetSRID(ST_MakePoint(1.5, 1.5), 4326)), (5, 'c', ST_SetSRID(ST_MakePoint(2.5, 1), 4326))")

    def test_count_with_value_aggregate(self):
        self._zones()
        tools.run(self.db, "count", {"layer": "public.zones", "other": "public.ads", "value": "price", "agg": "sum",
                                     "output": "zone_ads"})
        rows = self._sql("SELECT name, point_count, sum_price FROM zone_ads ORDER BY name")
        self.assertEqual(rows, [("اول", 2, 30.0), ("دوم", 1, 5.0)])
        tools.run(self.db, "count", {"layer": "public.zones", "other": "public.ads", "value": "price", "agg": "avg",
                                     "output": "zone_avg"})
        self.assertEqual(self._sql("SELECT avg_price FROM zone_avg WHERE name = 'اول'")[0][0], 15.0)
        for bad in ({"value": "note"}, {"value": "missing"}):
            with self.assertRaisesMessage(tools.ToolError, "عددی"):
                tools.run(self.db, "count", {"layer": "public.zones", "other": "public.ads", "output": "bad_x", **bad})
        # بدون ستون مقدار مثل قبل فقط شمارش
        tools.run(self.db, "count", {"layer": "public.zones", "other": "public.ads", "output": "zone_only"})
        cols = {r[0] for r in self._sql("SELECT column_name FROM information_schema.columns WHERE table_name='zone_only'")}
        self.assertIn("point_count", cols)
        self.assertFalse({c for c in cols if c.startswith(("sum_", "avg_"))})

    def test_overlap_shares_per_zone(self):
        self._zones()
        r = tools.run(self.db, "overlap", {"layer": "public.zones", "other": "public.landuse", "zone": "name",
                                           "category": "kind", "output": "zone_landuse"})
        self.assertEqual(r["rows"], 4)  # دو محله × دو کاربری
        rows = self._sql("SELECT zone, category, share_pct, area_m2 FROM zone_landuse ORDER BY zone, category")
        self.assertEqual([(z, c) for z, c, *_ in rows],
                         [("اول", "تجاری"), ("اول", "مسکونی"), ("دوم", "تجاری"), ("دوم", "مسکونی")])
        for _, _, share, area in rows:
            self.assertAlmostEqual(float(share), 50, delta=0.2)
            self.assertGreater(float(area), 1e10)
        sums = self._sql("SELECT zone, sum(share_pct) FROM zone_landuse GROUP BY zone")
        for _, total in sums:
            self.assertAlmostEqual(float(total), 100, delta=0.3)
        geo = self._sql("SELECT type, srid FROM geometry_columns WHERE f_table_name = 'zone_landuse'")
        self.assertEqual(geo, [("MULTIPOLYGON", 4326)])
        for bad in ({"zone": "nope"}, {"category": "nope"}):
            with self.assertRaises(tools.ToolError):
                tools.run(self.db, "overlap", {"layer": "public.zones", "other": "public.landuse", "zone": "name",
                                               "category": "kind", "output": "bad_y", **bad})
        with self.assertRaisesMessage(tools.ToolError, "POLYGON"):
            tools.run(self.db, "overlap", {"layer": "public.ads", "other": "public.landuse", "zone": "note",
                                           "category": "kind", "output": "bad_z"})

    def test_change_between_two_versions(self):
        self._sql_exec(
            "CREATE TABLE lu_old(id serial PRIMARY KEY, kind text, geom geometry(Polygon, 4326));"
            "INSERT INTO lu_old(kind, geom) VALUES ('کشاورزی', ST_MakeEnvelope(0, 0, 2, 2, 4326)),"
            " ('مسکونی', ST_MakeEnvelope(2, 0, 4, 2, 4326));"
            "CREATE TABLE lu_new(id serial PRIMARY KEY, kind text, geom geometry(Polygon, 4326));"
            "INSERT INTO lu_new(kind, geom) VALUES ('مسکونی', ST_MakeEnvelope(0, 0, 1, 2, 4326)),"
            " ('کشاورزی', ST_MakeEnvelope(1, 0, 2, 2, 4326)), ('مسکونی', ST_MakeEnvelope(2, 0, 4, 2, 4326))")
        r = tools.run(self.db, "change", {"layer": "public.lu_old", "other": "public.lu_new", "category": "kind",
                                          "category2": "kind", "output": "lu_change"})
        area = {(a, b): float(x) for a, b, x in self._sql("SELECT from_category, to_category, area_m2 FROM lu_change")}
        self.assertEqual(r["rows"], 3)
        self.assertEqual(set(area), {("کشاورزی", "کشاورزی"), ("کشاورزی", "مسکونی"), ("مسکونی", "مسکونی")})
        # نیمی از کشاورزی مسکونی شد و مسکونی قدیم دست‌نخورده ماند (مساحت‌ها تقریباً ۱:۱:۲)
        self.assertAlmostEqual(area[("کشاورزی", "کشاورزی")] / area[("کشاورزی", "مسکونی")], 1, delta=0.01)
        self.assertAlmostEqual(area[("مسکونی", "مسکونی")] / area[("کشاورزی", "کشاورزی")], 2, delta=0.02)
        self.assertEqual(self._sql("SELECT type, srid FROM geometry_columns WHERE f_table_name = 'lu_change'"), [("MULTIPOLYGON", 4326)])
        with self.assertRaisesMessage(tools.ToolError, "نسخه"):
            tools.run(self.db, "change", {"layer": "public.lu_old", "other": "public.lu_new", "category": "kind",
                                          "category2": "nope", "output": "lu_bad"})

    def test_page_and_access(self):
        url = reverse("analysis:page", args=[self.db.pk])
        r = self.client.get(url)
        self.assertContains(r, "حریم (بافر)")
        self.assertContains(r, "تنظیم کلید مدل زبانی")
        r = self.client.post(url, {"action": "tool", "tool": "buffer", "layer": "public.parks", "distance": "100",
                                   "output": "park_100"})
        self.assertRedirects(r, url + "#history", fetch_redirect_response=False)
        self.assertEqual(self._sql("SELECT to_regclass('public.park_100') IS NULL")[0][0], True)  # هنوز ساخته نشده
        # کلید: فقط https، رمزنگاری‌شده، دوباره نمایش داده نمی‌شود
        self.client.post(url, {"action": "llm_save", "base_url": "http://evil.example/v1", "api_key": "sk-1"})
        self.assertFalse(LlmConfig.objects.exists())
        self.client.post(url, {"action": "llm_save", "base_url": "https://api.avalai.ir/v1/", "model": "gpt-4o-mini",
                               "api_key": "sk-secret-123456789"})
        cfg = LlmConfig.objects.get()
        self.assertNotIn("secret", cfg.api_key_encrypted)
        self.assertEqual(cfg.get_key(), "sk-secret-123456789")
        self.assertEqual(cfg.base_url, "https://api.avalai.ir/v1")
        r = self.client.get(url)
        self.assertNotContains(r, "sk-secret-123456789")
        self.assertContains(r, "…6789")
        self.client.post(url, {"action": "llm_save", "base_url": "https://api.openai.com/v1", "model": "gpt-4.1"})
        self.assertEqual(LlmConfig.objects.get().get_key(), "sk-secret-123456789")  # کلید خالی = بدون تغییر
        other = User.objects.create_user("09120000042")
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_tool_runs_in_background_with_progress_and_history(self):
        from jobs import services as jobs

        url = reverse("analysis:page", args=[self.db.pk])
        post = {"action": "tool", "tool": "buffer", "layer": "public.parks", "distance": "100", "output": "park_100"}
        # اعتبارسنجی همان لحظه: نام نامعتبر صف نمی‌شود
        self.client.post(url, {**post, "output": "Bad name"})
        self.assertEqual(ToolRun.objects.count(), 0)
        self.client.post(url, post)
        run = ToolRun.objects.get()
        self.assertEqual(run.job.status, "queued")
        self.assertIn("parks", run.summary)
        # تا تمام نشده، دومی پذیرفته نمی‌شود و صفحه نوار پیشرفت دارد
        self.client.post(url, {**post, "output": "park_200"})
        self.assertEqual(ToolRun.objects.count(), 1)
        page = self.client.get(url)
        self.assertContains(page, 'role="progressbar"')
        self.assertContains(page, "تاریخچه تحلیل‌ها")
        st = self.client.get(reverse("analysis:status", args=[self.db.pk])).json()
        self.assertTrue(st["active"])
        self.assertEqual(st["items"][0]["status"], "queued")
        job = jobs.claim_next()
        jobs.run(job)
        run.refresh_from_db()
        run.job.refresh_from_db()
        self.assertEqual(run.job.status, "done")
        self.assertEqual(run.job.progress, 100)
        self.assertGreater(run.rows, 0)
        self.assertEqual(self._sql("SELECT count(*) FROM park_100")[0][0], run.rows)
        st = self.client.get(reverse("analysis:status", args=[self.db.pk])).json()
        self.assertFalse(st["active"])
        page = self.client.get(url)
        self.assertContains(page, "park_100")
        self.assertNotContains(page, 'role="progressbar"')
        # نتیجه کنار لایه ورودی روی یک نقشه (نمایش با هم)
        together = reverse("maps:quick", args=[self.db.pk]) + "?t=public.park_100&amp;t=public.parks"
        self.assertContains(page, together)
        quick = self.client.get(together.replace("&amp;", "&"))
        self.assertEqual([x["table"] for x in quick.context["config"]["layers"]], ["park_100", "parks"])
        # خطا در کارگر: ردیف ناموفق با پیام فارسی در تاریخچه
        self.client.post(url, {**post, "output": "park_300"})
        run2 = ToolRun.objects.get(output_table="park_300")
        self._sql_exec("CREATE TABLE park_300(a int)")
        jobs.run(jobs.claim_next())
        run2.job.refresh_from_db()
        self.assertEqual(run2.job.status, "failed")
        self.assertIn("park_300", run2.job.message)
        self.assertContains(self.client.get(url), "park_300")

    @unittest.skipUnless(HAS_S3GEO, "s3geo نصب نیست")
    def test_persian_question_with_static_llm(self):
        from s3geo import StaticLLMClient

        LlmConfig.objects.create(user=self.user, api_key_encrypted="")
        with self.assertRaisesMessage(ask.AskError, "لایه"):
            ask.request(self.db, self.user, "حریم ۵۰۰ متری ایستگاه‌ها", ["public.nope"], "zones")
        q = ask.request(self.db, self.user, "دور هر ایستگاه مترو حریم ۵۰۰ متری بکش", ["public.metro_stations", "public.nope"],
                        "metro_zones")
        self.assertEqual(q.layers, ["public.metro_stations"])
        with self.assertRaisesMessage(ask.AskError, "در حال پردازش"):
            ask.request(self.db, self.user, "یک پرسش دیگر برای آزمون", ["public.schools"], "other_out")
        plan = {"goal": "حریم ۵۰۰ متری ایستگاه‌های مترو",
                "entities": [{"ref": "metro_stations", "kind": "layer"}],
                "operations": [
                    {"op": "crs_transform", "inputs": {"vector": "metro_stations"},
                     "params": {"source_crs": "EPSG:4326", "target_crs": "EPSG:32639"}, "output": "m_utm"},
                    {"op": "buffer", "inputs": {"vector": "m_utm"}, "params": {"distance": 500}, "output": "zones"}]}
        msg = ask.run(q.job, client=StaticLLMClient(json.dumps(plan, ensure_ascii=False)))
        q.refresh_from_db()
        self.assertEqual(q.operations, ["crs_transform", "buffer"])
        n = self._sql("SELECT count(*) FROM metro_stations")[0][0]
        self.assertEqual(q.rows, n)
        self.assertIn("metro_zones", msg)
        srid, area = self._sql("SELECT max(ST_SRID(geom)), avg(ST_Area(geom::geography)) FROM metro_zones")[0]
        self.assertEqual(srid, 4326)
        self.assertAlmostEqual(area / 785398, 1, delta=0.05)
        # خطای مدل زبانی پیام فارسی می‌دهد و job ناموفق می‌شود
        Job.objects.filter(pk=q.job.pk).update(status="done")
        q2 = ask.request(self.db, self.user, "پرسش با پاسخ خراب مدل زبانی", ["public.schools"], "broken")
        with self.assertRaisesMessage(ask.AskError, "مدل زبانی"):
            ask.run(q2.job, client=StaticLLMClient("not json"))
        self.assertEqual(Question.objects.count(), 2)

    @unittest.skipUnless(HAS_S3GEO, "s3geo نصب نیست")
    def test_layers_and_output_name_are_automatic(self):
        LlmConfig.objects.create(user=self.user, api_key_encrypted="")
        q = ask.request(self.db, self.user, "مدرسه‌های متوسطه اول را جدا کن و لایه را به نام my_result_1 بساز", [], "")
        self.assertEqual(q.output_table, "my_result_1")
        self.assertEqual(sorted(q.layers), ["public.metro_stations", "public.parks", "public.schools"])
        self.assertTrue(any("خودکار" in n for n in q.notes))

    @unittest.skipUnless(HAS_S3GEO, "s3geo نصب نیست")
    def test_group_summary_becomes_a_real_table(self):
        from s3geo import StaticLLMClient

        LlmConfig.objects.create(user=self.user, api_key_encrypted="")
        q = ask.request(self.db, self.user, "تعداد و مجموع دانش‌آموزان هر مقطع", ["public.schools"], "by_level")
        plan = {"goal": "مقطع", "entities": [{"ref": "schools", "kind": "layer"}],
                "operations": [{"op": "aggregate_table", "inputs": {"vector": "schools"}, "output": "t",
                                "params": {"group_by": ["level"], "aggregations": {"students": ["sum"]}}}]}
        msg = ask.run(q.job, client=StaticLLMClient(json.dumps(plan, ensure_ascii=False)))
        q.refresh_from_db()
        self.assertEqual(q.result_kind, "table")
        self.assertEqual(q.rows, 3)
        self.assertEqual(self._sql("SELECT count(*) FROM by_level")[0][0], 3)
        self.assertIn("by_level", msg)

    @unittest.skipUnless(HAS_S3GEO, "s3geo نصب نیست")
    def test_confirm_flow_and_follow_up_through_the_page(self):
        """پرسش با تأیید: برنامه می‌آید، با «اجرا» اجرا می‌شود؛ سپس «ادامه» نتیجه را لایهٔ ورودی پرسش بعدی می‌کند."""
        from s3geo import StaticLLMClient

        LlmConfig.objects.create(user=self.user, api_key_encrypted="")
        url = reverse("analysis:page", args=[self.db.pk])
        plan = {"goal": "متوسطه اول", "entities": [{"ref": "schools", "kind": "layer"}],
                "operations": [{"op": "filter_attribute", "inputs": {"vector": "schools"}, "output": "r",
                                "params": {"where": {"field": "level", "op": "eq", "value": "متوسطه اول"}}}]}
        client = StaticLLMClient(json.dumps(plan, ensure_ascii=False))
        q = ask.request(self.db, self.user, "مدرسه‌های متوسطه اول را جدا کن", ["public.schools"], "first_lvl",
                        confirm=True)
        ask.run(q.job, client=client)
        Job.objects.filter(pk=q.job.pk).update(status="done")
        q.refresh_from_db()
        self.assertEqual(q.result_kind, "plan")
        self.assertEqual(self._sql("SELECT to_regclass('public.first_lvl')")[0][0], None)
        page = self.client.get(url)
        self.assertContains(page, "برنامهٔ پیشنهادی")
        self.assertContains(page, "درست است؛ اجرا کن")
        # تأیید از صفحه: کار تازه در صف و برنامه ثابت
        self.client.post(url, {"action": "ask_run", "q": q.pk})
        q.refresh_from_db()
        self.assertEqual(q.result_kind, "")
        self.assertEqual(q.job.status, "queued")
        self.client.post(url, {"action": "ask_run", "q": q.pk})  # تأیید دوباره اثری ندارد
        ask.run(q.job, client=client)
        Job.objects.filter(pk=q.job.pk).update(status="done")
        q.refresh_from_db()
        self.assertEqual(q.result_kind, "layer")
        self.assertGreater(q.rows, 0)
        self.assertTrue(q.preview.startswith("<svg"))
        page = self.client.get(url)
        self.assertContains(page, "ادامه با این نتیجه")
        # ادامه: لایهٔ نتیجه از پیش انتخاب و پرسش جدید به پرسش قبلی وصل می‌شود
        page = self.client.get(url + f"?follow={q.pk}")
        self.assertContains(page, 'value="public.first_lvl" checked')
        q2 = ask.request(self.db, self.user, "از این‌ها فقط بیش از ۴۰۰ دانش‌آموز", ["public.first_lvl"], "",
                         parent_pk=q.pk)
        self.assertEqual(q2.parent_id, q.pk)
        self.assertTrue(any("ادامهٔ پرسش قبلی" in n for n in q2.notes))
        # لغو برنامهٔ در انتظار
        Job.objects.filter(pk=q2.job.pk).update(status="done")
        Question.objects.filter(pk=q2.pk).update(result_kind="plan")
        self.client.post(url, {"action": "ask_cancel", "q": q2.pk})
        self.assertFalse(Question.objects.filter(pk=q2.pk).exists())

    @unittest.skipUnless(HAS_S3GEO, "s3geo نصب نیست")
    def test_summary_last_still_saves_layer_and_answer(self):
        """برنامهٔ مدل به summarize_vector ختم می‌شود: لایهٔ مرحلهٔ قبل باید ذخیره شود و خلاصه کنارش بیاید."""
        from s3geo import StaticLLMClient

        LlmConfig.objects.create(user=self.user, api_key_encrypted="")
        q = ask.request(self.db, self.user, "ایستگاه‌هایی که نامشان دارد را فهرست کن", ["public.metro_stations"], "named")
        plan = {"goal": "ایستگاه‌های نام‌دار",
                "entities": [{"ref": "metro_stations", "kind": "layer"}],
                "operations": [
                    {"op": "filter_attribute", "inputs": {"vector": "metro_stations"}, "params": {"sort_by": "name", "limit": 2},
                     "output": "shown"},
                    {"op": "summarize_vector", "inputs": {"vector": "shown"}, "params": {}, "output": "summary"}]}
        msg = ask.run(q.job, client=StaticLLMClient(json.dumps(plan, ensure_ascii=False)))
        q.refresh_from_db()
        self.assertEqual(q.rows, min(2, self._sql("SELECT count(*) FROM metro_stations")[0][0]))
        self.assertIn("تعداد عارضه", q.answer)
        self.assertIn("named", msg)

    @unittest.skipUnless(HAS_S3GEO, "s3geo نصب نیست")
    def test_non_spatial_result_is_an_answer_not_an_error(self):
        from s3geo import StaticLLMClient

        LlmConfig.objects.create(user=self.user, api_key_encrypted="")
        q = ask.request(self.db, self.user, "خلاصهٔ لایه ایستگاه‌ها را بده", ["public.metro_stations"], "never_created")
        plan = {"goal": "خلاصهٔ ایستگاه‌ها",
                "entities": [{"ref": "metro_stations", "kind": "layer"}],
                "operations": [{"op": "summarize_vector", "inputs": {"vector": "metro_stations"}, "params": {},
                                "output": "summary"}]}
        msg = ask.run(q.job, client=StaticLLMClient(json.dumps(plan, ensure_ascii=False)))
        q.refresh_from_db()
        self.assertEqual(q.rows, 0)
        self.assertIn("تعداد عارضه", q.answer)
        self.assertNotIn("vector_summary", q.answer)
        self.assertNotIn("نتیجه مکانی نداشت", msg)
        self.assertEqual(self._sql("SELECT to_regclass('public.never_created')")[0][0], None)

    @unittest.skipUnless(HAS_S3GEO, "s3geo نصب نیست")
    def test_empty_filter_reports_reason_and_creates_no_table(self):
        """فیلتر با مقداری که در داده نیست: «۰ عارضه» با شرط و مقادیر واقعی ستون، نه پاسخ خالی یا لایهٔ میانی."""
        from s3geo import StaticLLMClient

        LlmConfig.objects.create(user=self.user, api_key_encrypted="")
        q = ask.request(self.db, self.user, "ایستگاه‌هایی که نامشان ناموجود است", ["public.metro_stations"], "nothing")
        plan = {"goal": "ایستگاه ناموجود",
                "entities": [{"ref": "metro_stations", "kind": "layer"}],
                "operations": [
                    {"op": "crs_transform", "inputs": {"vector": "metro_stations"},
                     "params": {"source_crs": "EPSG:4326", "target_crs": "EPSG:32639"}, "output": "m_utm"},
                    {"op": "filter_attribute", "inputs": {"vector": "m_utm"},
                     "params": {"where": {"field": "name", "op": "eq", "value": "__nope__"}}, "output": "picked"}]}
        msg = ask.run(q.job, client=StaticLLMClient(json.dumps(plan, ensure_ascii=False)))
        q.refresh_from_db()
        self.assertEqual(q.result_kind, "empty")
        self.assertEqual(q.rows, 0)
        self.assertIn("هیچ عارضه‌ای پیدا نشد", msg)
        self.assertIn("«__nope__»", q.answer)
        self.assertIn("مقادیر موجود ستون «name»", q.answer)
        self.assertEqual([s["op"] for s in q.steps], ["input", "crs_transform", "filter_attribute"])
        self.assertEqual(q.steps[-1]["count"], 0)
        self.assertEqual(self._sql("SELECT to_regclass('public.nothing')")[0][0], None)
