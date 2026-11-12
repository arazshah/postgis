"""پذیرش ADR-0008 (مرحله‌ی ۷): «مانیتورینگ آنلاین» کاملاً با ویزارد ساخته، منتشر، از بازار آزمایشی‌گرفته و با داده‌ی دستگاه زنده می‌شود.

کل زنجیره روی PostgreSQL/PostGIS واقعی: ساخت در پنل ← انتشار ← بازار ← آزمایشی ← ساخت خودکار جدول ← توکن ← دریافت داده ← صفحه ← انقضا.
"""
import datetime
import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

import psycopg
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from billing import services
from billing.models import PluginAddon
from databases import services as db_services
from databases.tests.test_services import BaseCase
from kernel import entitlements, handlers, pkg
from kernel.models import Entitlement, PluginDraft, PluginRelease
from kernel.plugins import registry
from kernel.tests.test_pagekit import STORAGES

PG_HOST = os.environ.get("TEST_PG_HOST", "")


@unittest.skipUnless(PG_HOST, "به PostgreSQL آزمون نیاز دارد (TEST_PG_HOST)")
@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10, ADMIN_2FA_REQUIRED=False)
class MonitoringAcceptanceTests(BaseCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(lambda: [registry.remove_plugin(p) or pkg._loaded.pop(p, None) for p in list(pkg._loaded)])
        kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                  password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        self.kw = kw
        with psycopg.connect(dbname="postgres", **kw) as c:
            c.execute("DROP DATABASE IF EXISTS pagekit_acc")
            c.execute("CREATE DATABASE pagekit_acc")
        with psycopg.connect(dbname="pagekit_acc", **kw) as c:
            try:
                c.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            except psycopg.Error:
                self.skipTest("PostGIS در این PostgreSQL نیست")

        def conn():
            c = psycopg.connect(dbname="pagekit_acc", **kw)
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
                return [SimpleNamespace(schema=a, name=b, kind="r", oid=0) for a, b in rows if b != "spatial_ref_sys"]

            def columns(self_, t):
                with conn() as c:
                    rows = c.execute("select column_name from information_schema.columns where table_schema='public' and table_name=%s", [t.name]).fetchall()
                return [{"name": n, "generated": False, "identity": "", "spatial": False} for (n,) in rows]

        for target, val in (("kernel.tenantdb.catalog", lambda ws: Cat()), ("kernel.tenantdb.connect", connect)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)
        self.admin = get_user_model().objects.create_superuser("accroot", "Str0ng-Admin-Pass")
        from django.test import Client

        self.admin_client = Client()
        self.admin_client.force_login(self.admin)
        from core.models import SiteSettings

        conf = SiteSettings.get()
        conf.pay_enabled, conf.pay_manual_enabled = True, True
        conf.pay_card_number, conf.pay_card_holder = "6037991234567890", "آراز"
        conf.save()
        self.db = db_services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])
        self.customer = self.client
        self.customer.force_login(self.user)

    def rows(self, sql_text):
        with psycopg.connect(dbname="pagekit_acc", **self.kw) as c:
            return c.execute(sql_text).fetchall()

    def wiz(self, step, data, files=None):
        pk = PluginDraft.objects.get(plugin_id="monitoring").pk
        return self.admin_client.post(reverse("admin:kernel_plugindraft_wizard", args=[pk, step]), data)

    def build_with_wizard(self):
        a = self.admin_client
        r = a.post(reverse("admin:kernel_plugindraft_wizard_new"), {
            "name": "مانیتورینگ آنلاین", "plugin_id": "monitoring", "summary": "وضعیت زنده‌ی دستگاه‌ها روی نقشه", "description": "", "icon": "pulse"})
        self.assertEqual(r.status_code, 302)
        # ۲) داده
        self.wiz(2, {"op": "addtable", "suffix": "points", "indexes": "device,at", "c_name": ["device", "lat", "lon", "speed", "at"],
                     "c_type": ["text", "lat", "lon", "double", "timestamptz"], "c_req_0": "1", "c_req_1": "1", "c_req_2": "1", "c_auto_4": "1"})
        # ۳) کد: آمار سرعت
        self.wiz(3, {"op": "addhandler", "template": "block_stats", "name": "speedstats", "table": "monitoring_points", "num": "speed"})
        # ۴) صفحه
        self.wiz(4, {"op": "addpage", "title": "مانیتورینگ آنلاین", "group": "data", "need": "viewer", "refresh": "15", "icon": "pulse"})
        for b in ({"kind": "kpi", "title": "دستگاه فعال", "table": "monitoring_points", "agg": "count", "distinct": "device", "since_col": "at", "since_minutes": "5", "width": "third"},
                  {"kind": "kpi", "title": "میانگین سرعت", "table": "monitoring_points", "agg": "avg", "column": "speed", "width": "third"},
                  {"kind": "map", "title": "آخرین موقعیت", "table": "monitoring_points", "lat": "lat", "lon": "lon", "props": ["device", "speed"], "latest_by": "device", "time_col": "at"},
                  {"kind": "table", "title": "رکوردهای اخیر", "table": "monitoring_points", "columns": ["device", "speed", "at"], "order_by": "at", "limit": "20"},
                  {"kind": "handler", "title": "آمار سرعت", "handler": "speedstats", "display": "table"},
                  {"kind": "ingest", "title": "دریافت از دستگاه", "table": "monitoring_points", "fields": ["device", "lat", "lon", "speed"]}):
            self.wiz(4, {"op": "addblock:p1", **b})
        # ۵) دسترسی: عمومی پولی با ۷ روز آزمایشی
        self.wiz(5, {"mode": "public_paid", "price_toman": "90000", "duration_days": "30", "scope": "workspace", "trial_days": "7"})
        # ۶) انتشار
        r = self.wiz(6, {"op": "publish"})
        self.assertEqual(r.status_code, 302)

    def test_whole_chain(self):
        # --- مدیر: ساخت و انتشار با ویزارد، بدون امضای بیرونی
        self.build_with_wizard()
        rel = PluginRelease.objects.get(plugin_id="monitoring")
        self.assertEqual((rel.status, rel.publisher, rel.version), ("active", "panel", "1.0.0"))
        self.assertEqual(rel.manifest["tier"], 2)
        self.assertIn("monitoring", registry.plugins)
        self.assertIn("def handle", handlers.get("monitoring", "speedstats"))
        addon = PluginAddon.objects.get(plugin_id="monitoring")
        self.assertEqual((addon.price_toman, addon.trial_days, addon.description), (90000, 7, "وضعیت زنده‌ی دستگاه‌ها روی نقشه"))
        self.assertEqual(self.rows("select count(*) from pg_tables where tablename like 'monitoring_%'"), [(0,)])  # هنوز هیچ جدولی در پایگاه مشتری نیست

        # --- مشتری: بدون مجوز صفحه را نمی‌بیند؛ در بازار پلاگین را می‌بیند
        page_url = reverse("kernel:page", args=[self.db.pk, "monitoring", "p1"])
        self.assertEqual(self.customer.get(page_url).status_code, 404)
        market = self.customer.get(reverse("billing:market"))
        self.assertContains(market, "مانیتورینگ آنلاین")
        self.assertContains(market, "شروع آزمایشی")
        self.assertContains(market, "وضعیت زنده‌ی دستگاه‌ها روی نقشه")

        # --- آزمایشی رایگان ۷ روزه برای پایگاه خودش
        r = self.customer.post(reverse("billing:start_trial"), {"addon": addon.pk, "target": self.db.pk})
        self.assertEqual(r.status_code, 302)
        ent = Entitlement.objects.get(state__plugin_id="monitoring")
        self.assertEqual((ent.kind, ent.source), ("workspace", "trial"))
        entitlements.invalidate()
        self.assertEqual(services.addon_status(addon, self.user, self.db)["state"], "trial")
        self.assertContains(self.customer.get(reverse("billing:market")), "آزمایشی؛")

        # --- نخستین باز کردن صفحه: جدول خودکار ساخته می‌شود و بلوک‌ها رندر می‌شوند (هنوز داده‌ای نیست)
        r = self.customer.get(page_url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.rows("select column_name from information_schema.columns where table_name='monitoring_points' order by 1"),
                         [("at",), ("device",), ("id",), ("lat",), ("lon",), ("speed",)])
        self.assertContains(r, "دریافت از دستگاه")  # کارت دریافت داده

        # --- مالک پایگاه توکن می‌سازد و دستگاه داده می‌فرستد
        ingest_url = reverse("kernel:ingest_token", args=[self.db.pk, "monitoring", "p1", "ingest1"])
        self.assertEqual(self.customer.post(ingest_url, {"label": "ردیاب ۱"}).status_code, 302)
        token = self.customer.session["ingest_new"]["token"]
        self.assertTrue(token.startswith("gpi_"))
        import json

        def send(rows, tok=token):
            return self.customer.post(reverse("kernel:ingest"), data=json.dumps(rows), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {tok}")

        r = send([{"device": "d1", "lat": 35.70, "lon": 51.40, "speed": 40}, {"device": "d2", "lat": 35.80, "lon": 51.50, "speed": 60}])
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True, "inserted": 2}))
        self.assertEqual(send([{"device": "d1", "lat": 35.71, "lon": 51.41, "speed": 50}]).status_code, 200)
        self.assertEqual(send([{"device": "d3", "lat": 999, "lon": 51}]).status_code, 422)  # عرض نامعتبر: هیچ ردیفی نوشته نمی‌شود
        self.assertEqual(self.rows("select count(*) from monitoring_points"), [(3,)])
        self.assertEqual(send([{"device": "x", "lat": 1, "lon": 1}], tok="gpi_wrong").status_code, 404)

        # --- صفحه با داده‌ی زنده: شمارنده، میانگین، نقشه، جدول و آمار کد
        r = self.customer.get(page_url)
        html = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertIn("دستگاه فعال", html)
        self.assertIn("آخرین موقعیت", html)
        self.assertIn("d1", html)
        self.assertIn("آمار سرعت", html)
        self.assertIn("میانگین", html)  # خروجی کد (geo.stats) در جدول
        blocks = self.rows("select count(distinct device), round(avg(speed)::numeric, 1) from monitoring_points")
        self.assertEqual(blocks, [(2, 50.0)])
        self.assertNotIn("خواندن داده ممکن نشد", html)

        # --- پایان دوره: پلاگین برای او بسته می‌شود ولی داده می‌ماند
        Entitlement.objects.update(expires_at=timezone.now() - datetime.timedelta(minutes=1))
        entitlements.invalidate()
        self.assertEqual(self.customer.get(page_url).status_code, 404)
        self.assertEqual(self.rows("select count(*) from monitoring_points"), [(3,)])
        self.assertEqual(send([{"device": "d1", "lat": 35, "lon": 51}]).status_code, 404)  # دریافت هم بسته است
        self.assertEqual(services.addon_status(addon, self.user, self.db)["state"], "expired")
        # دوره‌ی آزمایشی دوباره ممکن نیست؛ خرید/تمدید می‌ماند
        with self.assertRaises(services.BillingError):
            services.start_trial(self.user, addon, self.db)
        inv = services.create_addon_invoice(self.user, addon, self.db)
        services.mark_paid(inv)
        entitlements.invalidate()
        self.assertEqual(self.customer.get(page_url).status_code, 200)  # تمدید: همه‌چیز برگشت
        self.assertEqual(self.rows("select count(*) from monitoring_points"), [(3,)])
