"""ورود/خروج داده با handler (ADR-0005): اعتبارسنجی، ساخت جدول امن، نماها، جعبه و بسته."""
import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

import psycopg
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse

from databases import services
from databases.tests.test_services import BaseCase
from kernel import entitlements, handlers, metering, pagekit, pluginio
from kernel.models import Entitlement, PluginState
from kernel.plugins import registry
from kernel.runner import sandbox

PG_HOST = os.environ.get("TEST_PG_HOST", "")
GOOD = {"columns": [{"name": "at", "type": "timestamptz"}, {"name": "lat", "type": "double"}, {"name": "lon", "type": "double"},
                    {"name": "note", "type": "text"}, {"name": "n", "type": "integer"}, {"name": "ok", "type": "boolean"}],
        "rows": [["2026-01-01T10:00:00Z", 35.7, 51.4, "x", 3, True], [None, None, None, None, None, None]],
        "geometry": {"lat": "lat", "lon": "lon"}}


class NormalizeImportTests(SimpleTestCase):
    def test_valid_result_is_typed(self):
        t = pluginio.normalize_import("Trk_1", GOOD)
        self.assertEqual((t.name, len(t.rows), t.geometry), ("trk_1", 2, ("lat", "lon")))
        self.assertEqual(t.rows[0][0].tzinfo is not None, True)
        self.assertEqual(t.rows[1], (None,) * 6)

    def test_bad_table_names(self):
        for bad in ("", "1abc", "a b", "a;drop", "pg_x", "Ä", "x" * 64, "a-b"):
            with self.subTest(bad=bad), self.assertRaises(pluginio.PluginIOError):
                pluginio.table_name(bad)

    def test_structure_rules(self):
        cases = [
            "not a dict", {"columns": [], "rows": []}, {"columns": "x", "rows": []},
            {"columns": [{"name": "a", "type": "money"}], "rows": []},  # نوع خارج از فهرست سفید
            {"columns": [{"name": "A b", "type": "text"}], "rows": []},  # نام ستون
            {"columns": [{"name": "geom", "type": "text"}], "rows": []},  # نام رزرو
            {"columns": [{"name": "a", "type": "text"}, {"name": "a", "type": "text"}], "rows": []},  # تکراری
            {"columns": [{"name": "a", "type": "text"}], "rows": [["x", "extra"]]},  # طول ردیف
            {"columns": [{"name": f"c{i}", "type": "text"} for i in range(51)], "rows": []},
            {"columns": [{"name": "a", "type": "text"}], "rows": [["x"]] * 20_001},
        ]
        for c in cases:
            with self.subTest(c=str(c)[:60]), self.assertRaises(pluginio.PluginIOError):
                pluginio.normalize_import("t", c)

    def test_value_rules(self):
        def one(ty, v):
            return pluginio.normalize_import("t", {"columns": [{"name": "a", "type": ty}], "rows": [[v]]}).rows[0][0]

        self.assertEqual(one("integer", 5.0), 5)
        for ty, v in [("integer", True), ("integer", 2**31), ("integer", 1.5), ("integer", "5"), ("bigint", 2**63), ("double", float("nan")),
                      ("double", float("inf")), ("double", True), ("boolean", 1), ("boolean", "true"), ("date", "x"), ("date", 5),
                      ("timestamptz", "نه"), ("text", "a" * 10_001), ("text", "a\x00b"), ("jsonb", "x" * 20_000)]:
            with self.subTest(ty=ty, v=str(v)[:20]), self.assertRaises(pluginio.PluginIOError):
                one(ty, v)

    def test_geometry_rules(self):
        base = {"columns": [{"name": "la", "type": "double"}, {"name": "lo", "type": "double"}, {"name": "s", "type": "text"}], "rows": [[1.0, 2.0, "x"]]}
        for geom in ({"lat": "la"}, {"lat": "la", "lon": "s"}, {"lat": "la", "lon": "missing"}, "x"):
            with self.subTest(geom=geom), self.assertRaises(pluginio.PluginIOError):
                pluginio.normalize_import("t", {**base, "geometry": geom})
        with self.assertRaises(pluginio.PluginIOError):
            pluginio.normalize_import("t", {**base, "rows": [[91.0, 2.0, "x"]], "geometry": {"lat": "la", "lon": "lo"}})
        with self.assertRaises(pluginio.PluginIOError):
            pluginio.normalize_import("t", {**base, "rows": [[1.0, 181.0, "x"]], "geometry": {"lat": "la", "lon": "lo"}})


class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, q, *a, **k):
        self.calls.append(("exec", q))

    @contextmanager
    def cursor(self):
        conn = self

        class Cur:
            def executemany(self, q, rows):
                conn.calls.append(("many", q, list(rows)))

        yield Cur()

    def commit(self):
        self.calls.append(("commit",))


class CreateTableTests(SimpleTestCase):
    def setUp(self):
        self.conn = FakeConn()
        self.cat = mock.Mock()
        self.cat.tables.return_value = []

        @contextmanager
        def connect(ws, **kw):
            self.kw = kw
            yield self.conn

        for target, val in (("kernel.tenantdb.catalog", lambda ws: self.cat), ("kernel.tenantdb.connect", connect)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)

    def test_owner_write_parametrised_and_values_never_in_sql(self):
        t = pluginio.normalize_import("trk", GOOD)
        self.assertEqual(pluginio.create_table(object(), t), 2)
        self.assertEqual(self.kw, {"write": True, "as_owner": True})
        many = next(c for c in self.conn.calls if c[0] == "many")
        self.assertEqual(many[2][0][-4:], (35.7, 51.4, 51.4, 35.7))  # lat, lon, lon, lat برای MakePoint(lon, lat)
        self.assertEqual(self.conn.calls[-1], ("commit",))

    def test_existing_table_is_refused_before_any_write(self):
        self.cat.tables.return_value = [SimpleNamespace(schema="public", name="trk")]
        with self.assertRaisesRegex(pluginio.PluginIOError, "از قبل هست"):
            pluginio.create_table(object(), pluginio.normalize_import("trk", GOOD))
        self.assertFalse(self.conn.calls)


class ExportTests(SimpleTestCase):
    def test_whitelisted_types_and_filename_sanitising(self):
        name, data, ctype = pluginio.normalize_export({"filename": "../../etc/pass wd.CSV", "text": "a,b\n"}, "csv")
        self.assertEqual((name, data, ctype), ("pass_wd.csv", b"a,b\n", "text/csv"))
        self.assertEqual(pluginio.normalize_export({"text": "{}"}, "geojson")[2], "application/geo+json")
        self.assertEqual(pluginio.normalize_export({"filename": "\x00\n", "text": "x"}, "txt")[0], "export.txt")

    def test_rejections(self):
        for out, fmt in [({"text": 5}, "csv"), ("x", "csv"), ({"text": "x"}, "html"), ({"text": "x" * (4 * 1024 * 1024 + 1)}, "txt"),
                         ({"text": "not json"}, "json")]:
            with self.subTest(fmt=fmt, out=str(out)[:20]), self.assertRaises(pluginio.PluginIOError):
                pluginio.normalize_export(out, fmt)


class SandboxFileTests(SimpleTestCase):
    def test_handler_sees_file_bytes_and_cap(self):
        src = "def handle(ctx, p):\n    d = ctx.file()\n    return {'n': len(d), 'first': d[0]}"
        self.assertEqual(sandbox.run({"code/h.py": src}, "h", {}, file=b"\x07abc"), {"n": 4, "first": 7})
        with self.assertRaisesRegex(sandbox.SandboxError, "فایلی ندارد"):
            sandbox.run({"code/h.py": src}, "h", {})
        with self.assertRaisesRegex(sandbox.SandboxError, "۳ مگابایت"):
            sandbox.run({"code/h.py": src}, "h", {}, file=b"x" * (3 * 1024 * 1024 + 1))

    def test_large_file_and_io_result_cap(self):
        src = "def handle(ctx, p):\n    return {'n': len(ctx.file()), 'pad': 'x' * (2 * 1024 * 1024)}"
        big = b"y" * (3 * 1024 * 1024)
        with self.assertRaisesRegex(sandbox.SandboxError, "بزرگ"):
            sandbox.run({"code/h.py": src}, "h", {}, file=big)  # سقف عادی ۱ مگابایت
        self.assertEqual(sandbox.run({"code/h.py": src}, "h", {}, file=big, max_result=sandbox.MAX_RESULT_IO)["n"], 3 * 1024 * 1024)


IMPORT_CODE = '''def handle(ctx, p):
    rows = []
    for line in ctx.file().decode("utf-8").splitlines():
        t, la, lo = line.split(",")
        rows.append([t, float(la), float(lo)])
    return {"columns": [{"name": "at", "type": "timestamptz"}, {"name": "lat", "type": "double"}, {"name": "lon", "type": "double"}],
            "rows": rows, "geometry": {"lat": "lat", "lon": "lon"}}
'''
EXPORT_CODE = '''def handle(ctx, p):
    r = ctx.sql("select 1")
    return {"filename": "report", "text": "n\\n" + str(r["rows"][0][0]) + "\\n"}
'''
PAGE = {"key": "io", "title": "ورود و خروج", "need": "editor", "blocks": [{"kind": "text", "text": "x"}],
        "imports": [{"key": "gps", "title": "ورود GPS", "handler": "parse", "extensions": [".trk"]}],
        "exports": [{"key": "rep", "title": "گزارش", "handler": "report", "format": "csv"}]}


class SpecTests(SimpleTestCase):
    def test_parse_and_rules(self):
        p = pagekit.parse_page("demo", PAGE)
        self.assertEqual((p.imports[0].handler, p.exports[0].format, p.imports[0].extensions), ("parse", "csv", (".trk",)))
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "need": "viewer"})  # ورود = نوشتن
        pagekit.parse_page("demo", {**PAGE, "need": "viewer", "imports": []})  # فقط خروجی خواندنی است
        for patch in ({"imports": [{**PAGE["imports"][0], "extensions": ["trk"]}]}, {"imports": [{**PAGE["imports"][0], "handler": "Bad Name"}]},
                      {"exports": [{**PAGE["exports"][0], "format": "html"}]}, {"exports": [PAGE["exports"][0]] * 2},
                      {"imports": [PAGE["imports"][0], {**PAGE["imports"][0], "key": "b"}, {**PAGE["imports"][0], "key": "c"}]}):
            with self.subTest(patch=str(patch)[:50]), self.assertRaises(pagekit.SpecError):
                pagekit.parse_page("demo", {**PAGE, **patch})


class ViewTests(BaseCase):
    def setUp(self):
        super().setUp()
        entitlements.invalidate()
        self.addCleanup(entitlements.invalidate)
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        handlers.register("demo", "parse", IMPORT_CODE)
        handlers.register("demo", "report", EXPORT_CODE)
        pagekit.register("demo", pagekit.parse_page("demo", PAGE))
        self.db = services.create_database(self.user, "iodb", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        self.imp = reverse("kernel:import", args=[self.db.pk, "demo", "io", "gps"])
        self.exp = reverse("kernel:export", args=[self.db.pk, "demo", "io", "rep"])
        self.page = reverse("kernel:page", args=[self.db.pk, "demo", "io"])
        for target, val in (("kernel.pluginio.create_table", mock.Mock(return_value=2)),
                            ("kernel.pagekit.read_select", mock.Mock(return_value={"columns": ["n"], "rows": [[7]]}))):
            p = mock.patch(target, val)
            self.mocks = getattr(self, "mocks", {})
            self.mocks[target.split(".")[-1]] = p.start()
            self.addCleanup(p.stop)

    def up(self, content=b"2026-01-01T10:00:00Z,35.7,51.4\n", name="a.trk", table="trk1"):
        return self.client.post(self.imp, {"file": SimpleUploadedFile(name, content), "table": table})

    def test_import_success_creates_table_via_core_and_meters(self):
        r = self.up()
        self.assertRedirects(r, self.page, fetch_redirect_response=False)
        table = self.mocks["create_table"].call_args[0][1]
        self.assertEqual((table.name, len(table.rows), table.geometry), ("trk1", 1, ("lat", "lon")))
        self.assertEqual(metering.used("demo", "io_runs", ws=self.db), 1)

    def test_import_input_rules(self):
        self.up(name="a.exe")
        self.up(table="Bad Name")
        self.up(content=b"")
        self.up(content=b"x" * (3 * 1024 * 1024 + 1))
        self.client.post(self.imp, {"table": "t1"})  # بدون فایل
        self.mocks["create_table"].assert_not_called()
        self.assertEqual(metering.used("demo", "io_runs", ws=self.db), 0)

    def test_handler_failure_and_bad_shape_do_not_write(self):
        handlers.register("demo", "parse", "def handle(c, p):\n    return 1/0")
        self.up()
        handlers.register("demo", "parse", "def handle(c, p):\n    return {'columns': [{'name': 'a', 'type': 'money'}], 'rows': []}")
        self.up()
        self.mocks["create_table"].assert_not_called()

    def test_database_error_is_short(self):
        self.mocks["create_table"].side_effect = psycopg.errors.InsufficientPrivilege("secret detail")
        r = self.up()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(metering.used("demo", "io_runs", ws=self.db), 0)

    def test_export_is_attachment_with_safe_headers(self):
        r = self.client.post(self.exp)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"n\n7\n")
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(r["Content-Disposition"], 'attachment; filename="report.csv"')
        self.assertEqual((r["X-Content-Type-Options"], r["Cache-Control"]), ("nosniff", "no-store"))

    def test_export_html_text_is_still_served_as_csv_attachment(self):
        handlers.register("demo", "report", "def handle(c, p):\n    return {'filename': 'x.html', 'text': '<script>alert(1)</script>'}")
        r = self.client.post(self.exp)
        self.assertEqual((r["Content-Type"], r["Content-Disposition"]), ("text/csv; charset=utf-8", 'attachment; filename="x.html.csv"'))

    def test_methods_access_and_cap(self):
        self.assertEqual(self.client.get(self.imp).status_code, 405)
        self.assertEqual(self.client.get(self.exp).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.exp).status_code, 302)
        from accounts.models import User

        self.client.force_login(User.objects.create_user("09120000088"))
        self.assertEqual(self.client.post(self.exp).status_code, 404)
        self.client.force_login(self.user)
        st = PluginState.objects.create(plugin_id="demo")
        Entitlement.objects.create(state=st, kind=Entitlement.Kind.ALL, limits={"io_runs_per_month": 1})
        entitlements.invalidate()
        self.assertEqual(self.client.post(self.exp).status_code, 200)
        self.assertEqual(self.client.post(self.exp).status_code, 302)  # سقف ماهانه پر شد
        PluginState.objects.filter(plugin_id="demo").update(enabled=False)
        entitlements.invalidate()
        self.assertEqual(self.client.post(self.exp).status_code, 404)

    def test_page_renders_forms(self):
        with mock.patch("kernel.tenantdb.catalog"):
            r = self.client.get(self.page)
        self.assertContains(r, "ورود GPS")
        self.assertContains(r, 'enctype="multipart/form-data"')
        self.assertContains(r, 'accept=".trk"')
        self.assertContains(r, "گزارش")


@unittest.skipUnless(PG_HOST, "به TEST_PG_HOST نیاز دارد")
class RealPostgresTests(SimpleTestCase):
    def test_real_create_and_hostile_values(self):
        kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                  password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        with psycopg.connect(dbname="postgres", **kw) as c:
            c.execute("DROP DATABASE IF EXISTS pluginio_t")
            c.execute("CREATE DATABASE pluginio_t")
        with psycopg.connect(dbname="pluginio_t", **kw) as c:
            try:
                c.execute("CREATE EXTENSION postgis")
                has_gis = True
            except psycopg.Error:
                has_gis = False
        cat = mock.Mock()
        cat.tables.return_value = []

        @contextmanager
        def connect(ws, **k):
            conn = psycopg.connect(dbname="pluginio_t", **kw)
            conn.autocommit = False
            try:
                yield conn
            finally:
                conn.close()

        out = {**GOOD, "rows": [["2026-01-01T10:00:00Z", 35.7, 51.4, "x'); DROP TABLE trk;--", 3, True], [None] * 6]}
        if not has_gis:
            out = {k: v for k, v in out.items() if k != "geometry"}
        with mock.patch("kernel.tenantdb.catalog", lambda ws: cat), mock.patch("kernel.tenantdb.connect", connect):
            self.assertEqual(pluginio.create_table(object(), pluginio.normalize_import("trk", out)), 2)
        with psycopg.connect(dbname="pluginio_t", **kw) as c:
            rows = c.execute("select note, n, ok from trk order by n nulls last").fetchall()
            self.assertEqual(rows, [("x'); DROP TABLE trk;--", 3, True), (None, None, None)])
            if has_gis:
                self.assertEqual(c.execute("select ST_X(geom), ST_Y(geom), geom is null from trk order by n nulls last").fetchall(),
                                 [(51.4, 35.7, False), (None, None, True)])
