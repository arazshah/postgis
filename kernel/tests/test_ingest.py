"""دریافت داده‌ی دستگاه `[[ingest]]`: مشخصات، توکن، نشانی عمومی، سقف‌ها و نوشتن همه‌یا‌هیچ (با PostGIS واقعی برای مسیر کامل)."""
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
from kernel import entitlements, ingest, metering, pagekit
from kernel.models import Entitlement, IngestToken, PluginState, PluginUsage
from kernel.plugins import registry
from kernel.tests.test_pagekit import STORAGES

PG_HOST = os.environ.get("TEST_PG_HOST", "")
SPEC = {"key": "track", "title": "دریافت موقعیت", "table": "points", "max_rows": 3, "rate": 4, "fields": [
    {"name": "device", "kind": "text", "label": "دستگاه", "required": True, "max": 20},
    {"name": "speed", "kind": "number", "label": "سرعت", "min": 0, "max": 300},
    {"name": "moving", "kind": "bool", "label": "در حرکت"}]}
PAGE = {"key": "gps", "title": "ردیابی", "need": "editor", "blocks": [{"kind": "text", "text": "x"}], "ingest": [SPEC]}


class SpecTests(SimpleTestCase):
    def test_valid_and_defaults(self):
        p = pagekit.parse_page("demo", PAGE)
        i = p.ingests[0]
        self.assertEqual((i.table, i.max_rows, i.rate, i.handler), ("points", 3, 4, ""))
        d = {k: v for k, v in SPEC.items() if k not in ("max_rows", "rate")}
        i = pagekit.parse_page("demo", {**PAGE, "ingest": [d]}).ingests[0]
        self.assertEqual((i.max_rows, i.rate), (100, 60))

    def test_handler_optional_and_validated(self):
        self.assertEqual(pagekit.parse_page("demo", {**PAGE, "ingest": [{**SPEC, "handler": "parse_gps"}]}).ingests[0].handler, "parse_gps")
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "ingest": [{**SPEC, "handler": "Bad Name"}]})

    def test_rejections(self):
        bad = [{**SPEC, "table": "x; drop"}, {**SPEC, "fields": []}, {**SPEC, "key": "Bad Key"}, {**SPEC, "max_rows": 0},
               {**SPEC, "max_rows": 5000}, {**SPEC, "rate": 0}, {**SPEC, "rate": True},
               {**SPEC, "fields": [{"name": "a", "label": "x"}, {"name": "a", "label": "y"}]}]
        for s in bad:
            with self.subTest(s=s), self.assertRaises(pagekit.SpecError):
                pagekit.parse_page("demo", {**PAGE, "ingest": [s]})
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "need": "viewer"})
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "ingest": [{**SPEC, "key": f"k{i}"} for i in range(3)]})
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "ingest": [SPEC, SPEC]})

    def test_row_conversion(self):
        spec = pagekit.parse_page("demo", PAGE).ingests[0]
        self.assertEqual(pagekit.read_ingest_row(spec, {"device": "d1", "speed": 12.5, "moving": True, "extra": 1}),
                         {"device": "d1", "speed": 12.5, "moving": True})
        self.assertEqual(pagekit.read_ingest_row(spec, {"device": "d1"})["speed"], None)
        for bad in ({"speed": 1}, {"device": "d" * 40}, {"device": "d", "speed": 999}, {"device": "d", "speed": "x"},
                    {"device": {"a": 1}}, {"device": ["a"]}, "not a dict"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pagekit.read_ingest_row(spec, bad)


@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class TokenAndEndpointTests(BaseCase):
    """بدون PostgreSQL مشتری: توکن، احراز هویت، سقف‌ها و پاسخ‌ها (نوشتن در جدول با mock)."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        pagekit.register_pages("demo", [pagekit.parse_page("demo", PAGE)]) if hasattr(pagekit, "register_pages") else None
        self.page = pagekit.parse_page("demo", PAGE)
        self._patch_get = unittest.mock.patch("kernel.pagekit.get", lambda p, k: self.page if (p, k) == ("demo", "gps") else None)
        self._patch_get.start()
        self.addCleanup(self._patch_get.stop)
        self.addCleanup(entitlements.invalidate)
        self.db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])
        self.url = reverse("kernel:ingest")

    def token(self):
        _row, raw = ingest.create_token(self.db, "demo", "gps", "track", self.user, "دستگاه ۱")
        return raw

    def post(self, body, token=None, **extra):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        data = body if isinstance(body, (bytes, str)) else json.dumps(body)
        return self.client.post(self.url, data=data, content_type="application/json", **headers, **extra)

    def test_token_is_hashed_and_shown_once(self):
        raw = self.token()
        row = IngestToken.objects.get()
        self.assertTrue(raw.startswith("gpi_") and len(raw) > 40)
        self.assertNotIn(raw, row.token_hash)
        self.assertEqual(len(row.token_hash), 64)
        self.assertEqual(row.prefix, raw[:8])

    def test_max_active_tokens(self):
        for _ in range(ingest.MAX_ACTIVE_TOKENS):
            self.token()
        with self.assertRaises(ingest.IngestError):
            self.token()
        ingest.revoke_token(self.db, IngestToken.objects.first().pk)
        self.token()

    def test_auth_failures_are_uniform_404(self):
        raw = self.token()
        for hdr in (None, "garbage", "gpi_wrong", raw + "x"):
            r = self.post({"device": "a"}, token=hdr)
            self.assertEqual(r.status_code, 404, hdr)
            self.assertEqual(r.json(), {"ok": False, "error": "یافت نشد."})

    def test_revoked_token_is_404(self):
        raw = self.token()
        ingest.revoke_token(self.db, IngestToken.objects.get().pk)
        self.assertEqual(self.post({"device": "a"}, token=raw).status_code, 404)

    def test_get_not_allowed_and_no_csrf_needed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        c = self.client_class(enforce_csrf_checks=True)
        self.assertEqual(c.post(self.url, data="{}", content_type="application/json").status_code, 404)  # نه ۴۰۳ CSRF

    def test_failed_attempts_are_rate_limited(self):
        for _ in range(ingest.FAIL_PER_MIN):
            self.assertEqual(self.post({}, token="gpi_x").status_code, 404)
        self.assertEqual(self.post({}, token="gpi_x").status_code, 429)

    def test_plugin_off_or_unlicensed_is_404(self):
        raw = self.token()
        PluginState.objects.create(plugin_id="demo", enabled=False)
        entitlements.invalidate()
        self.assertEqual(self.post({"device": "a"}, token=raw).status_code, 404)
        PluginState.objects.filter(plugin_id="demo").update(enabled=True, access="restricted")
        entitlements.invalidate()
        self.assertEqual(self.post({"device": "a"}, token=raw).status_code, 404)
        st = PluginState.objects.get(plugin_id="demo")
        Entitlement.objects.create(state=st, kind="workspace", subject=str(self.db.pk))
        entitlements.invalidate()
        with unittest.mock.patch("kernel.pagekit.insert_rows"):
            self.assertEqual(self.post({"device": "a"}, token=raw).status_code, 200)

    def test_validation_errors_write_nothing(self):
        raw = self.token()
        with unittest.mock.patch("kernel.pagekit.insert_rows") as ins:
            r = self.post([{"device": "ok"}, {"speed": 1}], token=raw)
            self.assertEqual(r.status_code, 422)
            self.assertIn("ردیف 2", r.json()["error"])
            self.assertFalse(ins.called)

    def test_limits(self):
        self.page = pagekit.parse_page("demo", {**PAGE, "ingest": [{**SPEC, "rate": 100}]})
        raw = self.token()
        with unittest.mock.patch("kernel.pagekit.insert_rows") as ins:
            self.assertEqual(self.post([{"device": "a"}] * 4, token=raw).status_code, 413)  # max_rows=3
            self.assertEqual(self.post("   ", token=raw).status_code, 400)
            self.assertEqual(self.post("not json", token=raw).status_code, 415)
            self.assertEqual(self.post([], token=raw).status_code, 400)
            big = b"[" + b'{"device":"a"},' * 30000 + b'{"device":"a"}]'
            self.assertEqual(self.post(big, token=raw).status_code, 413)
            self.assertFalse(ins.called)

    def test_rate_per_token(self):
        raw = self.token()
        with unittest.mock.patch("kernel.pagekit.insert_rows"):
            codes = [self.post({"device": "a"}, token=raw).status_code for _ in range(6)]
        self.assertEqual(codes, [200, 200, 200, 200, 429, 429])  # rate=4

    def test_metering_and_monthly_cap(self):
        raw = self.token()
        with unittest.mock.patch("kernel.pagekit.insert_rows"):
            self.post([{"device": "a"}, {"device": "b"}], token=raw)
        self.assertEqual(metering.used("demo", "ingest_rows", ws=self.db), 2)
        with unittest.mock.patch("kernel.metering.limit", return_value=2), unittest.mock.patch("kernel.pagekit.insert_rows") as ins:
            self.assertEqual(self.post({"device": "a"}, token=raw).status_code, 429)
            self.assertFalse(ins.called)
        self.assertEqual(PluginUsage.objects.get(metric="ingest_rows").count, 2)

    def test_database_errors_are_short_and_do_not_leak(self):
        raw = self.token()
        with unittest.mock.patch("kernel.pagekit.insert_rows", side_effect=RuntimeError("secret internals\nmore")):
            r = self.post({"device": "a"}, token=raw)
        self.assertEqual(r.status_code, 422)
        self.assertNotIn("secret", json.dumps(r.json(), ensure_ascii=False))
        with unittest.mock.patch("kernel.pagekit.insert_rows", side_effect=pagekit.SpecError("جدول نیست")):
            self.assertEqual(self.post({"device": "a"}, token=raw).status_code, 503)

    def test_handler_converts_body(self):
        spec = pagekit.parse_page("demo", {**PAGE, "ingest": [{**SPEC, "handler": "parse_gps"}]})
        self.page = spec
        raw = self.token()
        with unittest.mock.patch("kernel.runner.client.execute", return_value={"rows": [{"device": "x", "speed": 3}]}) as ex, \
                unittest.mock.patch("kernel.pagekit.insert_rows") as ins:
            r = self.post(b"RAW,x,3", token=raw)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ex.call_args.kwargs["file"], b"RAW,x,3")
        self.assertEqual(ins.call_args.args[2], [{"device": "x", "speed": 3.0, "moving": False}])
        with unittest.mock.patch("kernel.runner.client.execute", return_value={"nope": 1}):
            self.assertEqual(self.post(b"x", token=raw).status_code, 422)

    def test_owner_only_token_management_and_one_time_display(self):
        self.client.force_login(self.user)
        url = reverse("kernel:ingest_token", args=[self.db.pk, "demo", "gps", "track"])
        r = self.client.post(url, {"label": "برچسب"})
        self.assertEqual(r.status_code, 302)
        row = IngestToken.objects.get()
        page = self.client.get(reverse("kernel:page", args=[self.db.pk, "demo", "gps"]))
        self.assertContains(page, "gpi_")
        self.assertContains(page, "دیگر نمایش داده نمی‌شود")
        again = self.client.get(reverse("kernel:page", args=[self.db.pk, "demo", "gps"]))
        self.assertNotContains(again, "دیگر نمایش داده نمی‌شود")
        self.assertContains(again, row.prefix)
        self.client.post(reverse("kernel:ingest_revoke", args=[self.db.pk, "demo", "gps", "track", row.pk]))
        self.assertTrue(IngestToken.objects.get().revoked_at)


@unittest.skipUnless(PG_HOST, "به PostgreSQL آزمون نیاز دارد (TEST_PG_HOST)")
@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class RealInsertTests(BaseCase):
    """مسیر کامل روی PostgreSQL واقعی: ردیف‌ها همه‌یا‌هیچ در جدول مشتری نوشته می‌شوند."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        self.page = pagekit.parse_page("demo", PAGE)
        self.kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                       password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        with psycopg.connect(dbname="postgres", **self.kw) as c:
            c.execute("DROP DATABASE IF EXISTS pagekit_ing")
            c.execute("CREATE DATABASE pagekit_ing")
        with psycopg.connect(dbname="pagekit_ing", **self.kw) as c:
            c.execute("CREATE TABLE points (id serial primary key, device text not null, speed double precision, moving boolean)")
        cat = mock.Mock()
        cat.tables.return_value = [SimpleNamespace(schema="public", name="points", kind="r", oid=0)]
        cat.columns.return_value = [{"name": n, "generated": False, "identity": "", "spatial": False} for n in ("device", "speed", "moving")]
        kw = self.kw

        @contextmanager
        def connect(ws, **kw2):
            conn = psycopg.connect(dbname="pagekit_ing", **kw)
            conn.autocommit = False
            try:
                yield conn
            finally:
                conn.close()

        for target, val in (("kernel.pagekit.get", lambda a, b: self.page if (a, b) == ("demo", "gps") else None),
                            ("kernel.tenantdb.catalog", lambda ws: cat), ("kernel.tenantdb.connect", connect)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(entitlements.invalidate)
        self.db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])
        _row, self.raw = ingest.create_token(self.db, "demo", "gps", "track", self.user)

    def rows(self):
        with psycopg.connect(dbname="pagekit_ing", **self.kw) as c:
            return c.execute("SELECT device, speed, moving FROM points ORDER BY id").fetchall()

    def post(self, body):
        return self.client.post(reverse("kernel:ingest"), data=json.dumps(body), content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {self.raw}")

    def test_rows_land_in_the_table_all_or_nothing(self):
        r = self.post([{"device": "a", "speed": 10, "moving": True}, {"device": "b"}])
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True, "inserted": 2}))
        self.assertEqual(self.rows(), [("a", 10.0, True), ("b", None, False)])
        self.assertEqual(self.post([{"device": "c"}, {"speed": 1}]).status_code, 422)  # ردیف دوم نامعتبر
        self.assertEqual(len(self.rows()), 2)  # هیچ‌کدام نوشته نشد

    def test_database_constraint_failure_rolls_back_whole_batch(self):
        with psycopg.connect(dbname="pagekit_ing", **self.kw) as c:
            c.execute("ALTER TABLE points ADD CONSTRAINT dev_len CHECK (length(device) < 3)")
        r = self.post([{"device": "ok"}, {"device": "toolong"}])
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.rows(), [])

    def test_sql_injection_attempt_is_just_data(self):
        self.post({"device": "x';DROP TABLE p;--"})
        self.assertEqual(self.rows(), [("x';DROP TABLE p;--", None, False)])


class HandlerRoleTests(SimpleTestCase):
    """handler دریافت در آزمون بسته و استودیو: نقش «ingest» و اعتبارسنجی خروجی با فیلدهای هسته."""

    def setUp(self):
        self.page = pagekit.parse_page("demo", {**PAGE, "ingest": [{**SPEC, "handler": "parse_gps"}]})
        self.spec = self.page.ingests[0]

    def test_role_is_registered(self):
        from kernel import pkgtest

        self.assertEqual(pkgtest.roles_of([self.page])["parse_gps"], ("ingest", self.spec))

    def test_check_accepts_valid_rows_and_rejects_bad(self):
        from kernel import pkgtest, pluginio

        self.assertEqual(pkgtest._check_ingest(self.spec, {"rows": [{"device": "a"}, {"device": "b", "speed": 5}]}), 2)
        for bad in ({"rows": []}, {"rows": [{"speed": 1}]}, {"rows": [{"device": "x"}] * 4}, {"nope": 1}, [], None):
            with self.subTest(bad=bad), self.assertRaises(pluginio.PluginIOError):
                pkgtest._check_ingest(self.spec, bad)

    def test_package_requires_handler_in_bundle(self):
        from kernel import pkg

        toml = (b'key = "gps"\ntitle = "x"\nneed = "editor"\n[[blocks]]\nkind = "text"\ntext = "x"\n[[ingest]]\nkey = "track"\n'
                b'title = "t"\ntable = "points"\nhandler = "parse_gps"\n[[ingest.fields]]\nname = "device"\nlabel = "d"\n')
        manifest = {"id": "demo", "contributes": {"pages": ["pages/gps.toml"]}}
        files = {"pages/gps.toml": toml}
        with self.assertRaisesMessage(pkg.PackageError, "parse_gps"):
            pkg._pages(manifest, files, set())
        pages = pkg._pages(manifest, files, {"parse_gps"})
        self.assertEqual(pages[0].ingests[0].handler, "parse_gps")
