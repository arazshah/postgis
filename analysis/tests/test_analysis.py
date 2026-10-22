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
            ask.request(self.db, self.user, "حریم ۵۰۰ متری ایستگاه‌ها", [], "zones")
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
