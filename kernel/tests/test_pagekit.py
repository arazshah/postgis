"""کیت صفحه: اعتبارسنجی مشخصات، اجرای امن SQL، نمای صفحه، منو و دسترسی."""
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
from kernel import entitlements, nav, pagekit
from kernel.models import Entitlement, PluginState
from kernel.plugins import registry

PG_HOST = os.environ.get("TEST_PG_HOST", "")
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}

GOOD = {
    "key": "monitor", "title": "پایش زنده", "subtitle": "آخرین وضعیت", "icon": "pulse", "group": "data", "refresh": 10,
    "params": [{"name": "hours", "kind": "int", "label": "ساعت", "default": "24", "min": 1, "max": 72},
               {"name": "t", "kind": "layer", "label": "لایه"}],
    "blocks": [
        {"kind": "text", "text": "بند یک\n\nبند دو"},
        {"kind": "kpi", "title": "تعداد", "sql": "select count(*) from {t} where n > %(hours)s", "unit": "عدد"},
        {"kind": "table", "title": "جدول", "sql": "select name, n from {t} order by n desc", "columns": [["name", "نام"]]},
        {"kind": "bars", "title": "میله", "sql": "select name as label, n as value from {t}"},
        {"kind": "map", "title": "نقشه", "sql": "select name, geom from {t}"},
    ],
}


class SpecTests(SimpleTestCase):
    def parse(self, **patch):
        d = {**GOOD, **patch}
        return pagekit.parse_page("demo", d)

    def test_good_spec_parses_fully(self):
        p = self.parse()
        self.assertEqual((p.plugin, p.key, p.group, p.refresh, len(p.blocks), len(p.params)), ("demo", "monitor", "data", 10, 5, 2))
        self.assertEqual(p.blocks[1].width, "third")
        self.assertEqual(p.blocks[2].columns, (("name", "نام"),))

    def test_rejections(self):
        bad = [
            ({"key": "Bad Key"}, "کلید صفحه"), ({"title": ""}, "«title» لازم"), ({"group": "x"}, "گروه منو"),
            ({"need": "root"}, "سطح دسترسی"), ({"refresh": 2}, "refresh"), ({"refresh": True}, "refresh"),
            ({"blocks": []}, "دست‌کم یک بلوک"), ({"blocks": [{"kind": "x"}]}, "نوع بلوک"),
            ({"blocks": [{"kind": "table"}]}, "باید «sql»"),
            ({"blocks": [{"kind": "table", "sql": "delete from t"}]}, "فقط می‌تواند SELECT"),
            ({"blocks": [{"kind": "table", "sql": "select 1 from {zz}"}]}, "فقط برای پارامتر نوع layer"),
            ({"blocks": [{"kind": "table", "sql": "select %(nope)s"}]}, "پارامتر اعلام‌نشده"),
            ({"blocks": [{"kind": "table", "sql": "select * from %(t)s"}]}, "با {نام} بیاورید"),
            ({"blocks": [{"kind": "table", "sql": "select '{'"}]}, "آکولاد"),
            ({"blocks": [{"kind": "text"}]}, "text"), ({"blocks": [{"kind": "kpi", "sql": "select 1", "width": "x"}]}, "عرض"),
            ({"params": [{"name": "a", "kind": "int", "label": "x"}, {"name": "a", "kind": "int", "label": "y"}]}, "یکتا"),
            ({"params": [{"name": "__x", "kind": "int", "label": "x"}]}, "نامعتبر"),
            ({"params": [{"name": "c", "kind": "choice", "label": "x"}]}, "گزینه"),
            ({"icon": "no-such-icon"}, "آیکون"),
        ]
        for patch, needle in bad:
            with self.subTest(patch=patch), mock.patch.object(pagekit, "_icon_known", lambda n: n != "no-such-icon"):
                with self.assertRaises(pagekit.SpecError) as cm:
                    self.parse(**patch)
                self.assertIn(needle, str(cm.exception))

    def test_size_limits(self):
        with self.assertRaises(pagekit.SpecError):
            self.parse(blocks=[{"kind": "text", "text": "x"}] * 25)
        with self.assertRaises(pagekit.SpecError):
            self.parse(blocks=[{"kind": "table", "sql": "select " + "1," * 3000 + "1"}])

    def test_values_are_validated_with_defaults_and_messages(self):
        p = self.parse()
        layers = {"public.pts": "pts"}
        v, errs = pagekit.read_values(p, {"hours": "5", "t": "public.pts"}, layers)
        self.assertEqual((v, errs), ({"hours": 5, "t": "public.pts"}, []))
        v, errs = pagekit.read_values(p, {"hours": "999", "t": "public.other"}, layers)
        self.assertEqual(v["hours"], 24)
        self.assertIsNone(v["t"])
        self.assertEqual(len(errs), 2)
        v, _ = pagekit.read_values(p, {"hours": "abc"}, layers)
        self.assertEqual(v["hours"], 24)


class FakeCursor:
    def __init__(self, cols, rows):
        self.description = [SimpleNamespace(name=c) for c in cols]
        self._rows = rows

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, result):
        self.result, self.calls = result, []

    def execute(self, query, args=None, **kw):
        text = query if isinstance(query, str) else query.as_string(None)
        self.calls.append((text, args, kw))
        if isinstance(self.result, Exception):
            if text.startswith("SELECT"):
                raise self.result
            return None
        return FakeCursor(*self.result) if text.startswith("SELECT") else None


def fake_connect(conn):
    @contextmanager
    def connect(ws, **kw):
        yield conn
    return connect


class BlockRenderTests(SimpleTestCase):
    def setUp(self):
        self.page = pagekit.parse_page("demo", GOOD)
        self.values = {"hours": 24, "t": "public.pts"}

    def render(self, idx, result):
        conn = FakeConn(result)
        with mock.patch("kernel.tenantdb.connect", fake_connect(conn)):
            return pagekit.render_block(object(), self.page, self.page.blocks[idx], self.values), conn

    def test_kpi_formats_numbers_and_sql_is_composed_safely(self):
        out, conn = self.render(1, (["count"], [(12345,)]))
        self.assertEqual((out["value"], out["unit"]), ("12,345", "عدد"))
        timeout, query = conn.calls
        self.assertIn("statement_timeout", timeout[0])
        self.assertIn('from "public"."pts"', query[0])
        self.assertEqual(query[1], {"hours": 24, "__limit": 1})
        self.assertEqual(query[2], {"prepare": True})

    def test_table_uses_labels_and_marks_truncation(self):
        out, _ = self.render(2, (["name", "n"], [("الف", 3)] * 200))
        self.assertEqual(out["headers"], ["نام"])
        self.assertEqual(out["rows"][0], ["الف"])
        self.assertTrue(out["truncated"])

    def test_bars_need_label_and_value_columns(self):
        out, _ = self.render(3, (["label", "value"], [("a", 10), ("b", 5)]))
        self.assertEqual([b["pct"] for b in out["bars"]], [100, 50])
        bad, _ = self.render(3, (["x", "y"], []))
        self.assertIn("label", bad["error"])

    def test_map_builds_a_feature_collection(self):
        out, _ = self.render(4, (["__geom", "__props"], [('{"type":"Point","coordinates":[51,35]}', {"name": "a"})]))
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["geojson"]["features"][0]["properties"], {"name": "a"})

    def test_database_errors_become_short_persian_messages(self):
        out, _ = self.render(1, psycopg.errors.QueryCanceled("canceling statement due to statement timeout"))
        self.assertIn("سنگین", out["error"])
        out, _ = self.render(1, RuntimeError("secret detail"))
        self.assertEqual(out["error"], "خواندن داده ممکن نشد.")
        self.assertEqual(out["detail"], "secret detail")

    def test_unavailable_layer_is_a_block_error_not_a_crash(self):
        self.values["t"] = None
        out, _ = self.render(1, (["c"], [(1,)]))
        self.assertIn("در دسترس نیست", out["error"])

    def test_text_block_needs_no_database(self):
        out = pagekit.render_block(object(), self.page, self.page.blocks[0], self.values)
        self.assertEqual(out["paras"], ["بند یک", "بند دو"])


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST تنظیم نشده")
class RealPostgresTests(SimpleTestCase):
    """رفتار واقعی PostgreSQL: SELECT تنها، فقط‌خواندنی، سقف ردیف، چند دستور رد می‌شود."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                  password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        cls.kw = kw
        with psycopg.connect(dbname="postgres", **kw) as c:
            c.execute("DROP DATABASE IF EXISTS pagekit_t")
            c.execute("CREATE DATABASE pagekit_t")
        with psycopg.connect(dbname="pagekit_t", **kw) as c:
            try:
                c.execute("CREATE EXTENSION postgis")
                cls.has_postgis = True
            except psycopg.Error:
                cls.has_postgis = False
            geom = "ST_SetSRID(ST_MakePoint(51+i*0.01, 35), 4326)" if cls.has_postgis else "NULL"
            c.execute(f"CREATE TABLE pts(name text, n int, geom {'geometry(Point,4326)' if cls.has_postgis else 'text'});"
                      f"INSERT INTO pts SELECT 'p'||i, i, {geom} FROM generate_series(1,300) i;")

    def run_page(self, block, **patch):
        page = pagekit.parse_page("demo", {**GOOD, "blocks": [block], **patch})

        @contextmanager
        def connect(ws, **kw):
            conn = psycopg.connect(dbname="pagekit_t", **self.kw)
            conn.autocommit = False
            conn.read_only = True
            try:
                yield conn
            finally:
                conn.close()

        with mock.patch("kernel.tenantdb.connect", connect):
            return pagekit.render_block(object(), page, page.blocks[0], {"hours": 5, "t": "public.pts"})

    def test_kpi_table_bars_map_work_and_limits_apply(self):
        self.assertEqual(self.run_page({"kind": "kpi", "sql": "select count(*) from {t} where n > %(hours)s"})["value"], "295")
        t = self.run_page({"kind": "table", "sql": "select name, n from {t} order by n"})
        self.assertEqual(len(t["rows"]), 200)
        self.assertEqual(t["rows"][0], ["p1", "1"])
        b = self.run_page({"kind": "bars", "sql": "select name as label, n as value from {t} order by n desc"})
        self.assertEqual((len(b["bars"]), b["bars"][0]["pct"]), (50, 100))
        if self.has_postgis:
            m = self.run_page({"kind": "map", "sql": "select name, geom from {t}"})
            self.assertEqual(m["count"], 300)
            self.assertEqual(m["geojson"]["features"][0]["geometry"]["type"], "Point")

    def test_multiple_statements_and_writes_are_refused(self):
        for q in ("select 1; select 2", "select 1) q; drop table pts; --", "select 1 as a) q; delete from pts; select * from (select 1"):
            with self.subTest(q=q):
                out = self.run_page({"kind": "table", "sql": q})
                self.assertTrue(out["error"], q)
        with self.assertRaises(pagekit.SpecError):
            self.run_page({"kind": "table", "sql": "insert into pts values ('x',1,null)"})
        out = self.run_page({"kind": "table", "sql": "with d as (delete from pts returning n) select * from d"})
        self.assertTrue(out["error"])  # تراکنش فقط‌خواندنی
        self.assertEqual(self.run_page({"kind": "kpi", "sql": "select count(*) from {t}"})["value"], "300")

    def test_timeout_is_reported_briefly(self):
        with mock.patch.object(pagekit, "TIMEOUT_S", 1):
            out = self.run_page({"kind": "kpi", "sql": "select pg_sleep(3)"})
        self.assertIn("سنگین", out["error"])


class PageViewTests(BaseCase):
    def setUp(self):
        super().setUp()
        entitlements.invalidate()
        self.addCleanup(entitlements.invalidate)
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        spec = {**GOOD, "refresh": 0}
        pagekit.register("demo", pagekit.parse_page("demo", spec))
        pagekit.register("demo", pagekit.parse_page("demo", {**spec, "key": "other", "title": "صفحه‌ی دوم", "order": 200}))
        self.db = services.create_database(self.user, "pkdb", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        self.url = reverse("kernel:page", args=[self.db.pk, "demo", "monitor"])
        conn = FakeConn((["count"], [(7,)]))
        for target, val in (("kernel.tenantdb.connect", fake_connect(conn)),):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)
        cat = mock.patch("kernel.tenantdb.catalog")
        self.catalog = cat.start().return_value
        self.catalog.tables.return_value = [SimpleNamespace(schema="public", name="pts")]
        self.addCleanup(cat.stop)

    @override_settings(STORAGES=STORAGES)
    def test_page_renders_blocks_filters_and_menu_entries(self):
        r = self.client.get(self.url, {"hours": "5"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "پایش زنده")
        self.assertContains(r, "بند دو")
        self.assertContains(r, 'name="hours"')
        self.assertContains(r, '<option value="public.pts"')
        self.assertContains(r, "pk-grid")
        self.assertContains(r, "page-kit.css")
        # هر دو صفحه در ریل هستند و فقط صفحه‌ی فعلی «on» است
        data = [i for g in nav.ws_groups() for i in g[1] if i.plugin == "demo"]
        self.assertEqual(sorted(i.extra[1] for i in data), ["monitor", "other"])
        self.assertContains(r, reverse("kernel:page", args=[self.db.pk, "demo", "other"]))
        self.assertContains(r, 'class="ws-item on"', count=1)

    @override_settings(STORAGES=STORAGES)
    def test_fragment_returns_only_the_body(self):
        r = self.client.get(self.url, {"fragment": "1"})
        self.assertContains(r, "pk-grid")
        self.assertNotContains(r, "<html")

    def test_access_rules(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)  # ورود لازم است
        stranger = self.make_user("09120000077") if hasattr(self, "make_user") else None
        if stranger is None:
            from accounts.models import User

            stranger = User.objects.create_user("09120000077")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)  # عضو این پایگاه نیست
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("kernel:page", args=[self.db.pk, "demo", "nope"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("kernel:page", args=[self.db.pk, "other_plugin", "monitor"])).status_code, 404)

    @override_settings(STORAGES=STORAGES)
    def test_plugin_state_controls_the_page_and_its_menu(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        st = PluginState.objects.create(plugin_id="demo", access="restricted")
        self.assertEqual(self.client.get(self.url).status_code, 404)
        dashboard = self.client.get(reverse("databases:detail", args=[self.db.pk]))
        self.assertNotContains(dashboard, self.url)
        Entitlement.objects.create(state=st, kind="user", subject=str(self.user.pk))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertContains(self.client.get(reverse("databases:detail", args=[self.db.pk])), self.url)
        st.enabled = False
        st.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    @override_settings(STORAGES=STORAGES)
    def test_inactive_workspace_redirects_to_overview(self):
        self.db.status = self.db.Status.SUSPENDED
        self.db.save()
        r = self.client.get(self.url)
        self.assertRedirects(r, reverse("databases:detail", args=[self.db.pk]), fetch_redirect_response=False)

    def test_other_users_cannot_see_the_page_in_their_database_menu(self):
        from accounts.models import User

        other = User.objects.create_user("09120000088")
        db2 = services.create_database(other, "pkdb2", "Abcdefgh123", ["postgis"])
        self.client.force_login(other)
        with override_settings(STORAGES=STORAGES):
            html = self.client.get(reverse("databases:detail", args=[db2.pk])).content.decode()
        self.assertIn(reverse("kernel:page", args=[db2.pk, "demo", "monitor"]), html)  # صفحه‌ی باز برای همه‌ی پایگاه‌هاست
        self.assertNotIn(reverse("kernel:page", args=[self.db.pk, "demo", "monitor"]), html)
