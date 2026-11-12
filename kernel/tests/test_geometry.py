"""فیلد `geometry` و ستون‌های چندضلعی/خط (ADR-0009 مرحله‌ی ۳): اعتبارسنجی ساختار، نوشتن در PostGIS و ساخت جدول."""
import json
import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

import psycopg
from django.test import SimpleTestCase

from kernel import geomval, pagekit, tables

PG_HOST = os.environ.get("TEST_PG_HOST", "")
SQUARE = {"type": "Polygon", "coordinates": [[[51, 35], [52, 35], [52, 36], [51, 36], [51, 35]]]}
BOWTIE = {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]}  # خودتقاطع


class ValidateTests(SimpleTestCase):
    def ok(self, g, kind):
        return geomval.validate(json.dumps(g), kind)

    def test_valid_kinds_and_feature_wrapper(self):
        self.assertIsInstance(self.ok(SQUARE, "polygon"), geomval.GeomValue)
        self.ok({"type": "Feature", "properties": {}, "geometry": SQUARE}, "polygon")
        self.ok({"type": "LineString", "coordinates": [[1, 2], [3, 4]]}, "line")
        self.ok({"type": "Point", "coordinates": [51.4, 35.7]}, "point")
        self.ok({"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"], SQUARE["coordinates"]]}, "multipolygon")

    def test_output_is_normalized_geometry_only(self):
        out = json.loads(self.ok({"type": "Feature", "geometry": SQUARE, "properties": {"evil": "<script>"}}, "polygon"))
        self.assertEqual(set(out), {"type", "coordinates"})

    def test_rejections(self):
        cases = [("polygon", {"type": "Point", "coordinates": [1, 2]}), ("polygon", {"type": "Polygon", "coordinates": []}),
                 ("polygon", {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]}),  # کم‌نقطه
                 ("polygon", {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}),  # باز
                 ("polygon", {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 91], [0, 0]]]}),  # عرض خارج
                 ("polygon", {"type": "Polygon", "coordinates": [[[0, 0], [181, 0], [1, 1], [0, 0]]]}),
                 ("polygon", {"type": "Polygon", "coordinates": [[["a", 0], [1, 0], [1, 1], [0, 0]]]}),
                 ("polygon", {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]], ] * 60}),
                 ("line", {"type": "LineString", "coordinates": [[1, 2]]}), ("point", {"type": "Point", "coordinates": [1]}),
                 ("point", {"type": "Point", "coordinates": [True, 2]}), ("point", {"type": "Point", "coordinates": [float("nan"), 2]}),
                 ("multipolygon", {"type": "MultiPolygon", "coordinates": []}), ("polygon", {"type": "GeometryCollection"})]
        for kind, g in cases:
            with self.subTest(kind=kind, g=str(g)[:60]), self.assertRaises(ValueError):
                geomval.validate(json.dumps(g, allow_nan=True), kind)
        for bad in ("not json", "", "{", "[]", "null"):
            with self.assertRaises(ValueError):
                geomval.validate(bad, "polygon")

    def test_vertex_and_size_caps(self):
        ring = [[51 + i * 1e-5, 35] for i in range(geomval.MAX_VERTICES + 5)]
        ring += [[51, 36], ring[0]]
        with self.assertRaises(ValueError):
            geomval.validate(json.dumps({"type": "Polygon", "coordinates": [ring]}), "polygon")
        with self.assertRaises(ValueError):
            geomval.validate(" " * (geomval.MAX_BYTES + 1), "polygon")


class SpecTests(SimpleTestCase):
    def test_geometry_field_and_columns(self):
        f = pagekit.parse_field({"name": "area", "kind": "geometry", "label": "محدوده", "geom": "polygon", "required": True})
        self.assertEqual((f.kind, f.geom), ("geometry", "polygon"))
        self.assertEqual(pagekit.parse_field({"name": "a", "kind": "geometry", "label": "x"}).geom, "polygon")
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_field({"name": "a", "kind": "geometry", "label": "x", "geom": "circle"})
        t = pagekit.parse_table("demo", {"name": "demo_fields", "columns": [{"name": "boundary", "type": "polygon"}, {"name": "path", "type": "line"},
                                                                          {"name": "parts", "type": "multipolygon"}, {"name": "geom", "type": "polygon"}]})
        self.assertEqual([c.type for c in t.columns], ["polygon", "line", "multipolygon", "polygon"])
        for bad in ("id", "geom"):
            with self.assertRaises(pagekit.SpecError):
                pagekit.parse_table("demo", {"name": "demo_x", "columns": [{"name": bad, "type": "text"}]})

    def test_create_sql_uses_geometry_types_and_gist(self):
        t = pagekit.parse_table("demo", {"name": "demo_f", "columns": [{"name": "b", "type": "polygon", "required": True}, {"name": "p", "type": "line"}]})
        self.assertIn("geometry(Polygon, 4326)", tables.TYPES["polygon"])
        self.assertEqual(len(tables.index_statements(t)), 2)  # برای هر ستون هندسی gist

    def test_source_rejects_geometry(self):
        src = {"key": "s", "title": "x", "url": "https://x.org/a", "table": "t", "fields": [{"name": "g", "kind": "geometry", "label": "g"}]}
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_source(src)

    def test_convert_field(self):
        f = pagekit.Field("a", "geometry", "محدوده", True, (), None, None, "polygon")
        self.assertIsInstance(pagekit.convert_field(f, json.dumps(SQUARE)), geomval.GeomValue)
        with self.assertRaises(ValueError):
            pagekit.convert_field(f, "")  # اجباری
        self.assertIsNone(pagekit.convert_field(pagekit.Field("a", "geometry", "x", False, (), None, None, "polygon"), ""))


@unittest.skipUnless(PG_HOST, "به PostgreSQL آزمون نیاز دارد (TEST_PG_HOST)")
class RealPostgisTests(SimpleTestCase):
    def setUp(self):
        kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                  password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        self.kw = kw
        with psycopg.connect(dbname="postgres", **kw) as c:
            c.execute("DROP DATABASE IF EXISTS pagekit_geom")
            c.execute("CREATE DATABASE pagekit_geom")
        with psycopg.connect(dbname="pagekit_geom", **kw) as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            c.execute("CREATE TABLE demo_fields (id bigserial primary key, name text, boundary geometry(Polygon,4326), "
                      "path geometry(LineString,4326), anyg geometry, planar geometry(Polygon,3857))")
        cols = [{"name": n, "type": t, "generated": False, "identity": "", "spatial": s} for n, t, s in (
            ("name", "text", False), ("boundary", "geometry(Polygon,4326)", True), ("path", "geometry(LineString,4326)", True),
            ("anyg", "geometry", True), ("planar", "geometry(Polygon,3857)", True))]
        cat = mock.Mock()
        cat.tables.return_value = [SimpleNamespace(schema="public", name="demo_fields", kind="r", oid=0)]
        cat.columns.return_value = cols

        @contextmanager
        def connect(ws, **k):
            conn = psycopg.connect(dbname="pagekit_geom", **kw)
            conn.autocommit = False
            try:
                yield conn
            finally:
                conn.close()

        for target, val in (("kernel.tenantdb.catalog", lambda ws: cat), ("kernel.tenantdb.connect", connect)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)

    def form(self, *fields):
        return SimpleNamespace(table="demo_fields", fields=tuple(fields))

    def poly_field(self, name="boundary"):
        return pagekit.Field(name, "geometry", "محدوده", False, (), None, None, "polygon")

    def rows(self, q):
        with psycopg.connect(dbname="pagekit_geom", **self.kw) as c:
            return c.execute(q).fetchall()

    def test_polygon_is_stored_with_srid_and_area(self):
        g = geomval.validate(json.dumps(SQUARE), "polygon")
        pagekit.insert_rows(None, self.form(pagekit.Field("name", "text", "n"), self.poly_field()), [{"name": "مزرعه", "boundary": g}])
        self.assertEqual(self.rows("SELECT name, ST_SRID(boundary), ST_GeometryType(boundary), round(ST_Area(boundary)::numeric, 1) FROM demo_fields"),
                         [("مزرعه", 4326, "ST_Polygon", 1.0)])
        self.assertEqual(self.rows("SELECT ST_Contains(boundary, ST_SetSRID(ST_MakePoint(51.5, 35.5), 4326)) FROM demo_fields"), [(True,)])

    def test_self_intersecting_rejected_nothing_written(self):
        g = geomval.validate(json.dumps(BOWTIE), "polygon")
        with self.assertRaises(pagekit.SpecError) as cm:
            pagekit.insert_rows(None, self.form(self.poly_field()), [{"boundary": g}])
        self.assertIn("معتبر نیست", str(cm.exception))
        self.assertEqual(self.rows("SELECT count(*) FROM demo_fields"), [(0,)])

    def test_batch_is_all_or_nothing(self):
        good, bad = (geomval.validate(json.dumps(x), "polygon") for x in (SQUARE, BOWTIE))
        with self.assertRaises(pagekit.SpecError):
            pagekit.insert_rows(None, self.form(self.poly_field()), [{"boundary": good}, {"boundary": bad}])
        self.assertEqual(self.rows("SELECT count(*) FROM demo_fields"), [(0,)])

    def test_null_geometry_allowed(self):
        pagekit.insert_rows(None, self.form(self.poly_field()), [{"boundary": None}])
        self.assertEqual(self.rows("SELECT boundary IS NULL FROM demo_fields"), [(True,)])

    def test_type_and_srid_mismatch_rejected(self):
        g = geomval.validate(json.dumps({"type": "LineString", "coordinates": [[1, 2], [3, 4]]}), "line")
        line_into_poly = pagekit.Field("boundary", "geometry", "x", False, (), None, None, "line")
        with self.assertRaises(pagekit.SpecError):
            pagekit.insert_rows(None, self.form(line_into_poly), [{"boundary": g}])
        with self.assertRaises(pagekit.SpecError):
            pagekit.insert_rows(None, self.form(self.poly_field("planar")), [{"planar": None}])  # SRID ۳۸۵۷
        pagekit.insert_rows(None, self.form(pagekit.Field("path", "geometry", "x", False, (), None, None, "line")), [{"path": g}])
        self.assertEqual(self.rows("SELECT ST_AsText(path) FROM demo_fields"), [("LINESTRING(1 2,3 4)",)])

    def test_plain_field_cannot_write_spatial_column(self):
        with self.assertRaises(pagekit.SpecError):
            pagekit.insert_rows(None, self.form(pagekit.Field("boundary", "text", "x")), [{"boundary": "POINT(1 1)"}])

    def test_injection_text_is_not_geometry(self):
        with self.assertRaises(ValueError):
            geomval.validate("'); DROP TABLE demo_fields;--", "polygon")


# ---------------------------------------------------------------------- ویرایش و حذف ردیف
REC = {"key": "farms", "title": "مزرعه‌ها", "table": "demo_farms", "limit": 5,
       "fields": [{"name": "name", "kind": "text", "label": "نام", "required": True, "max": 40},
                  {"name": "crop", "kind": "choice", "label": "محصول", "choices": [["wheat", "گندم"], ["corn", "ذرت"]]},
                  {"name": "area", "kind": "geometry", "label": "محدوده", "geom": "polygon"}]}
TBL = {"name": "demo_farms", "columns": [{"name": "name", "type": "text"}, {"name": "crop", "type": "text"}, {"name": "area", "type": "polygon"}]}
PAGE = {"key": "farms", "title": "مزرعه‌ها", "need": "editor", "blocks": [{"kind": "text", "text": "x"}], "tables": [TBL], "records": [REC]}


class RecordSpecTests(SimpleTestCase):
    def test_valid_and_defaults(self):
        r = pagekit.parse_page("demo", PAGE).records[0]
        self.assertEqual((r.table, r.columns, r.can_delete, r.limit), ("demo_farms", ("name", "crop"), True, 5))  # هندسه در ستون‌های نمایشی نیست

    def test_rejections(self):
        bad = [{"table": "demo_other"}, {"table": "public.demo_farms"}, {"fields": []}, {"columns": ["area"]}, {"columns": []},
               {"columns": ["ghost"]}, {"limit": 0}, {"limit": 500}, {"limit": True}, {"key": "Bad Key"}]
        for over in bad:
            with self.subTest(over=over), self.assertRaises(pagekit.SpecError):
                pagekit.parse_page("demo", {**PAGE, "records": [{**REC, **over}]})
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "need": "viewer"})
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "records": [REC, REC]})  # کلید تکراری
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "tables": []})  # جدول اعلام نشده


@unittest.skipUnless(PG_HOST, "به PostgreSQL آزمون نیاز دارد (TEST_PG_HOST)")
class RecordRealTests(SimpleTestCase):
    def setUp(self):
        kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                  password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        self.kw = kw
        with psycopg.connect(dbname="postgres", **kw) as c:
            c.execute("DROP DATABASE IF EXISTS pagekit_rec")
            c.execute("CREATE DATABASE pagekit_rec")
        with psycopg.connect(dbname="pagekit_rec", **kw) as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            c.execute("CREATE TABLE demo_farms (id bigserial primary key, name text, crop text, area geometry(Polygon,4326), secret text)")
            c.execute("CREATE TABLE demo_noid (name text)")
            c.execute("INSERT INTO demo_farms (name, crop, secret) VALUES ('الف','wheat','S1'),('ب','corn','S2')")
        cat = mock.Mock()
        cat.tables.return_value = [SimpleNamespace(schema="public", name=n, kind="r", oid=i) for i, n in enumerate(("demo_farms", "demo_noid"))]

        def columns(table):
            if table.name == "demo_noid":
                return [{"name": "name", "type": "text", "generated": False, "identity": "", "spatial": False, "pk": False}]
            return [{"name": n, "type": t, "generated": False, "identity": "", "spatial": sp, "pk": n == "id"} for n, t, sp in (
                ("id", "bigint", False), ("name", "text", False), ("crop", "text", False), ("area", "geometry(Polygon,4326)", True), ("secret", "text", False))]
        cat.columns.side_effect = columns

        @contextmanager
        def connect(ws, **k):
            conn = psycopg.connect(dbname="pagekit_rec", **kw)
            conn.autocommit = False
            try:
                yield conn
            finally:
                conn.close()

        for target, val in (("kernel.tenantdb.catalog", lambda ws: cat), ("kernel.tenantdb.connect", connect)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)
        self.rec = pagekit.parse_page("demo", PAGE).records[0]

    def rows(self, q="SELECT id, name, crop, secret, ST_AsText(area) FROM demo_farms ORDER BY id"):
        with psycopg.connect(dbname="pagekit_rec", **self.kw) as c:
            return c.execute(q).fetchall()

    def vals(self, **kw):
        base = {"name": "جدید", "crop": "corn", "area": None}
        return {**base, **kw}

    def test_list_newest_first_without_secret_columns(self):
        heads, rows = pagekit.fetch_records(None, self.rec)
        self.assertEqual(heads, ["id", "name", "crop"])
        self.assertEqual([r[1] for r in rows], ["ب", "الف"])

    def test_update_changes_only_declared_columns_of_that_row(self):
        g = geomval.validate(json.dumps(SQUARE), "polygon")
        pagekit.update_record(None, self.rec, 1, self.vals(name="مزرعه‌ی نو", area=g))
        r1, r2 = self.rows()
        self.assertEqual((r1[1], r1[2], r1[3]), ("مزرعه‌ی نو", "corn", "S1"))  # secret دست‌نخورده
        self.assertTrue(r1[4].startswith("POLYGON"))
        self.assertEqual((r2[1], r2[3]), ("ب", "S2"))

    def test_fetch_record_returns_geojson_for_editing(self):
        pagekit.update_record(None, self.rec, 1, self.vals(area=geomval.validate(json.dumps(SQUARE), "polygon")))
        cur = pagekit.fetch_record(None, self.rec, 1)
        self.assertEqual(json.loads(cur["area"])["type"], "Polygon")
        self.assertNotIn("secret", cur)
        self.assertIsNone(pagekit.fetch_record(None, self.rec, 999))

    def test_invalid_geometry_and_missing_row_change_nothing(self):
        with self.assertRaises(pagekit.SpecError):
            pagekit.update_record(None, self.rec, 1, self.vals(area=geomval.validate(json.dumps(BOWTIE), "polygon")))
        with self.assertRaises(pagekit.SpecError):
            pagekit.update_record(None, self.rec, 999, self.vals())
        self.assertEqual([r[1] for r in self.rows()], ["الف", "ب"])

    def test_delete_only_that_row_and_missing_is_error(self):
        pagekit.delete_record(None, self.rec, 1)
        self.assertEqual([r[0] for r in self.rows()], [2])
        with self.assertRaises(pagekit.SpecError):
            pagekit.delete_record(None, self.rec, 1)

    def test_table_without_id_is_refused(self):
        bad = pagekit.RecordSpec("k", "t", "demo_noid", (pagekit.Field("name", "text", "n"),), ("name",))
        for fn in (lambda: pagekit.update_record(None, bad, 1, {"name": "x"}), lambda: pagekit.delete_record(None, bad, 1),
                   lambda: pagekit.fetch_records(None, bad)):
            with self.assertRaises(pagekit.SpecError):
                fn()

    def test_injection_in_values_is_just_data(self):
        pagekit.update_record(None, self.rec, 1, self.vals(name="x'; DELETE FROM demo_farms;--"))
        self.assertEqual(len(self.rows()), 2)
