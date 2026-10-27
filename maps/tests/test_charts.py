"""نمودار نقشه: پاک‌سازی تنظیمات، تجمیع در PostGIS واقعی، ذخیره در طراح، آدرس عمومی و کپی نقشه."""
import json
import os
import unittest
import uuid

import psycopg
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases import services as db_services
from databases.models import DatabaseServer
from databases.provisioner import Provisioner
from maps import charts, services
from maps.models import MapChart, WebMap

PG_HOST = os.environ.get("TEST_PG_HOST", "")
TYPES = {"kind": "text", "sales": "int4", "opened": "date", "id": "int4"}


class CleanTests(SimpleTestCase):
    def test_bar_defaults_and_limits(self):
        cfg = charts.clean("bar", {"field": "kind", "limit": 999, "order": "x", "junk": 1}, TYPES)
        self.assertEqual(cfg, {"agg": "count", "limit": 20, "order": "value", "field": "kind"})
        self.assertEqual(charts.clean("pie", {"field": "kind", "limit": 99}, TYPES)["limit"], charts.PIE_MAX)

    def test_agg_needs_numeric_value(self):
        self.assertEqual(charts.clean("bar", {"field": "kind", "agg": "sum", "value": "sales"}, TYPES)["value"], "sales")
        for bad in ("kind", "missing", ""):
            with self.assertRaises(charts.ChartError):
                charts.clean("bar", {"field": "kind", "agg": "avg", "value": bad}, TYPES)

    def test_field_type_matches_kind(self):
        with self.assertRaises(charts.ChartError):
            charts.clean("hist", {"field": "kind"}, TYPES)
        with self.assertRaises(charts.ChartError):
            charts.clean("time", {"field": "sales"}, TYPES)
        with self.assertRaises(charts.ChartError):
            charts.clean("bar", {"field": "geom"}, TYPES)
        with self.assertRaises(charts.ChartError):
            charts.clean("radar", {}, TYPES)
        self.assertEqual(charts.clean("time", {"field": "opened", "unit": "x"}, TYPES)["unit"], "month")
        self.assertEqual(charts.clean("hist", {"field": "sales", "bins": 1}, TYPES)["bins"], 3)

    def test_kpi_has_no_field(self):
        self.assertEqual(charts.clean("kpi", {"field": "kind"}, TYPES), {"agg": "count"})

    def test_titles(self):
        self.assertEqual(charts.title_for("bar", {"field": "kind", "agg": "sum", "value": "sales"}), "جمع sales بر اساس kind")
        self.assertEqual(charts.title_for("kpi", {"agg": "count"}), "تعداد عارضه‌ها")


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"])
class ChartsIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000082")
        self.db = db_services.create_database(self.user, f"ch_{uuid.uuid4().hex[:8]}", "Charts-Pass-1", ["postgis"])
        self.addCleanup(self._drop)
        with self._pg() as c:
            c.execute("CREATE TABLE shops(id serial PRIMARY KEY, kind text, sales int, opened date,"
                      " geom geometry(Point, 4326))")
            # ۳۰ ردیف: نوع a تا f به‌نوبت، فروش ۱ تا ۳۰، تاریخ در سه ماه، طول از ۵۱٫۰۱ تا ۵۱٫۳۰
            c.execute("INSERT INTO shops(kind, sales, opened, geom) SELECT chr(96 + 1 + (g - 1) % 6), g,"
                      " DATE '2025-01-15' + (g - 1) * 3, ST_SetSRID(ST_MakePoint(51 + g * 0.01, 35.7), 4326)"
                      " FROM generate_series(1, 30) g")
            c.execute("INSERT INTO shops(kind, sales, opened, geom) VALUES (NULL, NULL, NULL,"
                      " ST_SetSRID(ST_MakePoint(51.5, 35.7), 4326))")
        self.client.force_login(self.user)
        self.webmap = services.create_map(self.db, self.user, "فروشگاه‌ها", ["public.shops"])
        self.layer = self.webmap.layers.get()

    def _pg(self):
        return psycopg.connect(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=self.db.role_name,
                               password="Charts-Pass-1", dbname=self.db.db_name, autocommit=True)

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _save(self, webmap=None, **data):
        webmap = webmap or self.webmap
        return self.client.post(reverse("maps:composer", args=[self.db.pk, webmap.pk]), json.dumps(data),
                                content_type="application/json")

    def _item(self, kind="bar", **config):
        return {"layer": f"ml{self.layer.pk}", "kind": kind, "config": config}

    # ------------------------------------------------------------------ تجمیع
    def test_kpi(self):
        self.assertEqual(charts.data(self.layer, "kpi", {}), {"value": 31.0, "count": 31})
        got = charts.data(self.layer, "kpi", {"agg": "sum", "value": "sales"})
        self.assertEqual((got["value"], got["count"]), (465.0, 31))
        self.assertEqual(charts.data(self.layer, "kpi", {"agg": "avg", "value": "sales"})["value"], 15.5)

    def test_bar_counts_other_and_order(self):
        got = charts.data(self.layer, "bar", {"field": "kind", "limit": 3})
        self.assertEqual(got["labels"], ["a", "b", "c"])  # برابر بودن تعداد: ترتیب الفبایی
        self.assertEqual((got["values"], got["other"]), ([5, 5, 5], 15))  # NULL شمرده نمی‌شود
        got = charts.data(self.layer, "bar", {"field": "kind", "limit": 20})
        self.assertEqual((len(got["labels"]), got["other"]), (6, None))
        got = charts.data(self.layer, "bar", {"field": "kind", "agg": "sum", "value": "sales", "limit": 3})
        self.assertEqual(got["labels"], ["f", "e", "d"])  # بیشترین جمع فروش
        self.assertEqual(got["values"], [90, 85, 80])
        got = charts.data(self.layer, "bar", {"field": "kind", "agg": "avg", "value": "sales", "limit": 3})
        self.assertIsNone(got["other"])  # میانگین باقی‌مانده معنا ندارد
        got = charts.data(self.layer, "bar", {"field": "kind", "limit": 3, "order": "label"})
        self.assertEqual(got["labels"], ["a", "b", "c"])

    def test_bbox_limits_features(self):
        box = [51.0, 35.0, 51.105, 36.0]  # فقط ردیف‌های g = 1 تا 10
        self.assertEqual(charts.data(self.layer, "kpi", {}, box)["count"], 10)
        got = charts.data(self.layer, "bar", {"field": "kind", "limit": 20}, box)
        self.assertEqual(sum(got["values"]), 10)
        got = charts.data(self.layer, "hist", {"field": "sales", "bins": 5}, box)
        self.assertEqual(sum(got["counts"]), 10)
        got = charts.data(self.layer, "time", {"field": "opened", "unit": "month"}, box)
        self.assertEqual(sum(got["values"]), 10)

    def test_histogram_equal_width_and_class_breaks(self):
        got = charts.data(self.layer, "hist", {"field": "sales", "bins": 5})
        self.assertEqual((got["edges"][0], got["edges"][-1], got["classes"]), (1.0, 30.0, False))
        self.assertEqual((len(got["counts"]), sum(got["counts"])), (5, 30))
        self.layer.style = {**self.layer.style, "mode": "graduated", "field": "sales", "breaks": [10, 20]}
        got = charts.data(self.layer, "hist", {"field": "sales", "bins": 5})
        self.assertEqual((got["edges"], got["counts"], got["classes"]), ([1.0, 10.0, 20.0, 30.0], [9, 10, 11], True))
        got = charts.data(self.layer, "hist", {"field": "sales", "bins": 5, "classes": False})
        self.assertFalse(got["classes"])  # کاربر مرزهای مساوی خواسته است
        self.layer.style = {**self.layer.style, "field": "kind"}  # طبقه‌بندی روی ستون دیگر است
        self.assertFalse(charts.data(self.layer, "hist", {"field": "sales"})["classes"])

    def test_class_histogram_edges_stay_ordered_inside_bbox(self):
        self.layer.style = {**self.layer.style, "mode": "graduated", "field": "sales", "breaks": [10, 20]}
        box = [51.0, 35.0, 51.185, 36.0]  # g = 12 تا 18 هم داخل است؛ ولی لبه‌های محدوده از مرزها بیرون نمی‌زنند
        got = charts.data(self.layer, "hist", {"field": "sales"}, [51.115, 35.0, 51.185, 36.0])
        self.assertEqual(got["edges"], sorted(got["edges"]))
        self.assertEqual(len(got["edges"]), len(got["counts"]) + 1)
        got = charts.data(self.layer, "hist", {"field": "sales"}, box)
        self.assertEqual(got["edges"], sorted(got["edges"]))

    def test_other_keeps_negative_sums(self):
        with self._pg() as c:
            c.execute("UPDATE shops SET sales = -sales WHERE kind IN ('d', 'e', 'f')")
        got = charts.data(self.layer, "bar", {"field": "kind", "agg": "sum", "value": "sales", "limit": 3})
        total = charts.data(self.layer, "kpi", {"agg": "sum", "value": "sales"})["value"]
        self.assertAlmostEqual(sum(got["values"]) + got["other"], total)
        self.assertLess(got["other"], 0)

    def test_histogram_single_value_and_empty(self):
        with self._pg() as c:
            c.execute("DELETE FROM shops WHERE sales <> 7 OR sales IS NULL")
        got = charts.data(self.layer, "hist", {"field": "sales"})
        self.assertEqual((got["edges"], got["counts"]), ([7.0, 7.0], [1]))
        with self._pg() as c:
            c.execute("DELETE FROM shops")
        self.assertEqual(charts.data(self.layer, "hist", {"field": "sales"}), {"edges": [], "counts": [], "classes": False})
        self.assertEqual(charts.data(self.layer, "bar", {"field": "kind"})["labels"], [])

    def test_time_series(self):
        got = charts.data(self.layer, "time", {"field": "opened", "unit": "month"})
        self.assertEqual(got["labels"], sorted(got["labels"]))
        self.assertEqual(got["labels"][0], "2025-01-01")
        self.assertEqual(sum(got["values"]), 30)  # NULL شمرده نمی‌شود
        got = charts.data(self.layer, "time", {"field": "opened", "unit": "year", "agg": "sum", "value": "sales"})
        self.assertEqual((got["labels"], got["values"]), (["2025-01-01"], [465]))

    def test_data_rejects_bad_config(self):
        with self.assertRaises(charts.ChartError):
            charts.data(self.layer, "bar", {"field": "nope"})

    # ------------------------------------------------------------------ ذخیره در طراح
    def test_save_charts_roundtrip(self):
        r = self._save(charts=[self._item("bar", field="kind", agg="sum", value="sales"),
                               {**self._item("kpi"), "title": "همه"}])
        self.assertEqual(r.status_code, 200)
        first, second = list(self.webmap.charts.all())
        self.assertEqual((first.kind, first.config["value"], second.title, second.config), ("bar", "sales", "همه", {"agg": "count"}))
        # با شناسه: به‌روزرسانی در جا؛ بدون شناسه: تازه؛ جاافتاده: حذف
        r = self._save(charts=[{**self._item("pie", field="kind"), "id": first.pk, "title": "سهم"}, self._item("kpi")])
        self.assertEqual(r.status_code, 200)
        rows = list(self.webmap.charts.all())
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0].pk, rows[0].kind, rows[0].title), (first.pk, "pie", "سهم"))
        self.assertFalse(MapChart.objects.filter(pk=second.pk).exists())
        # ذخیره‌ای که فهرست نمودار ندارد، نمودارها را نگه می‌دارد
        self._save(title="نام تازه")
        self.assertEqual(self.webmap.charts.count(), 2)
        self._save(charts=[])
        self.assertEqual(self.webmap.charts.count(), 0)

    def test_invalid_chart_blocks_the_whole_save(self):
        r = self._save(title="باید ذخیره نشود", charts=[self._item("hist", field="kind")])
        self.assertEqual(r.status_code, 400)
        self.assertIn("عددی", r.json()["error"])
        self.webmap.refresh_from_db()
        self.assertEqual(self.webmap.title, "فروشگاه‌ها")
        r = self._save(charts=[{"layer": "ml0", "kind": "kpi"}])
        self.assertEqual(r.status_code, 400)
        other = WebMap.objects.create(database=self.db, title="x")
        foreign = other.layers.create(table="shops", geom_column="geom")
        self.assertEqual(self._save(charts=[{"layer": foreign.pk, "kind": "kpi"}]).status_code, 400)

    def test_plan_cap(self):
        plan = self.db.plan
        plan.map_charts = 2
        plan.save()
        three = [self._item("kpi")] * 3
        r = self._save(charts=three)
        self.assertEqual(r.status_code, 400)
        self.assertIn("حداکثر ۲", r.json()["error"].replace("2", "۲"))
        self.assertEqual(self._save(charts=three[:2]).status_code, 200)

    def test_chart_field_travels_in_tiles(self):
        self.layer.style = {**self.layer.style, "popup": ["sales"]}
        self.layer.save()
        self.assertEqual(self.layer.columns, ["sales"])
        self._save(charts=[self._item("bar", field="kind")])
        before = self.layer.updated_at
        self.layer.refresh_from_db()
        self.assertEqual(self.layer.columns, ["sales", "kind"])
        self.assertGreater(self.layer.updated_at, before)  # کلید کش کاشی عوض شد

    def test_preview_endpoint(self):
        url = reverse("maps:chart_preview", args=[self.db.pk, self.webmap.pk])
        body = {"layer": f"ml{self.layer.pk}", "kind": "bar", "config": {"field": "kind", "limit": 3},
                "bbox": [51.0, 35.0, 51.105, 36.0]}
        r = self.client.post(url, json.dumps(body), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sum(r.json()["data"]["values"]) + (r.json()["data"]["other"] or 0), 10)
        self.assertEqual(r.json()["autoTitle"], "تعداد عارضه‌ها بر اساس kind")
        body["config"] = {"field": "nope"}
        self.assertEqual(self.client.post(url, json.dumps(body), content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(url, "nope", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(Client().post(url, "{}", content_type="application/json").status_code, 302)  # ورود لازم

    # ------------------------------------------------------------------ آدرس عمومی
    def test_public_chart_data_and_access(self):
        self._save(charts=[self._item("bar", field="kind", limit=3)])
        chart = self.webmap.charts.get()
        url = reverse("maps:chart_data", args=[self.webmap.slug, chart.pk])
        anon = Client()
        self.assertIn(anon.get(url).status_code, (401, 403))  # نقشه خصوصی
        r = self.client.get(url)  # صاحب پایگاه داده
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["kind"], r.json()["data"]["labels"]), ("bar", ["a", "b", "c"]))
        self.assertIn("no-store", r["Cache-Control"])
        self._save(is_public=True)
        r = anon.get(url + "?bbox=51.0,35.0,51.105,36.0")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["values"], [2, 2, 2])
        self.assertIn("public", r["Cache-Control"])
        self.assertEqual(anon.get(url + "?bbox=junk").json()["data"]["values"], [5, 5, 5])  # محدوده نامعتبر: نادیده
        self.assertEqual(anon.get(reverse("maps:chart_data", args=[self.webmap.slug, chart.pk + 99])).status_code, 404)
        other = WebMap.objects.create(database=self.db, title="x", is_public=True)
        self.assertEqual(anon.get(reverse("maps:chart_data", args=[other.slug, chart.pk])).status_code, 404)

    def test_map_config_lists_charts(self):
        self._save(charts=[{**self._item("kpi"), "title": "تعداد"}])
        page = self.client.get(reverse("maps:composer", args=[self.db.pk, self.webmap.pk]))
        conf = page.context["config"]
        self.assertEqual(conf["charts"][0]["layer"], f"ml{self.layer.pk}")
        self.assertEqual((conf["charts"][0]["title"], conf["chartsUrl"], conf["chartCap"]),
                         ("تعداد", f"/maps/{self.webmap.slug}/c/", 4))

    # ------------------------------------------------------------------ کپی
    def test_duplicate_copies_charts(self):
        self._save(charts=[self._item("bar", field="kind"), self._item("kpi")])
        copy = services.duplicate(self.webmap, self.user)
        mine, theirs = list(self.webmap.charts.all()), list(copy.charts.all())
        self.assertEqual([(c.kind, c.config) for c in mine], [(c.kind, c.config) for c in theirs])
        self.assertEqual({c.layer.webmap_id for c in theirs}, {copy.pk})
        self.assertEqual(self.webmap.charts.count(), 2)

    def test_copy_to_drops_charts_without_matching_columns(self):
        self._save(charts=[self._item("bar", field="kind"), self._item("hist", field="sales")])
        other = db_services.create_database(User.objects.create_user("09120000083"), f"ch_{uuid.uuid4().hex[:8]}", "Charts-Pass-2", ["postgis"])
        self.addCleanup(db_services.delete_database, other)
        with psycopg.connect(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=other.role_name,
                             password="Charts-Pass-2", dbname=other.db_name, autocommit=True) as c:
            c.execute("CREATE TABLE shops(id serial PRIMARY KEY, kind text, geom geometry(Point, 4326))")
        copy, skipped = services.copy_to(self.webmap, other, self.user)
        self.assertEqual([c.kind for c in copy.charts.all()], ["bar"])
        self.assertEqual(skipped, ["نمودار «توزیع sales»"])
