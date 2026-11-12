"""ورود فایل به جدول موجود با نگاشت ستون: واحد + یکپارچه (TEST_PG_HOST و ogr2ogr)."""
import json
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases import services as db_services
from databases.explorer import TableRef
from databases.models import DatabaseServer
from databases.provisioner import Provisioner
from dbimport import importinto
from jobs import services as jobs
from jobs.models import Job

PG_HOST = os.environ.get("TEST_PG_HOST", "")
HAS_GDAL = bool(shutil.which("ogr2ogr"))


def col(name, typ="text", base="text", not_null=False, default="", identity="", generated=False, spatial=False, pk=False):
    return {"name": name, "type": typ, "base": base, "not_null": not_null, "default": default, "identity": identity,
            "generated": generated, "spatial": spatial, "pk": pk}


COLS = [col("id", "bigint", "int8", True, identity="a", pk=True), col("name", not_null=True),
        col("qty", "integer", "int4"), col("Owner Name"), col("area", "double precision", "float8", generated=True),
        col("geom", "geometry(Point,32639)", "geometry", spatial=True)]


class UnitTests(SimpleTestCase):
    def test_target_columns_skip_identity_generated_geometry(self):
        self.assertEqual([c["name"] for c in importinto.target_columns(COLS)], ["name", "qty", "Owner Name"])

    def test_auto_map_exact_loose_and_missing(self):
        m = importinto.auto_map(COLS, ["QTY", "owner_name", "other", "Name"])
        self.assertEqual(m, {"name": 3, "qty": 0, "Owner Name": 1})
        self.assertEqual(importinto.auto_map(COLS, ["zzz"]), {})

    def test_required(self):
        self.assertTrue(importinto.is_required(col("a", not_null=True)))
        self.assertFalse(importinto.is_required(col("a", not_null=True, default="'x'")))
        self.assertFalse(importinto.is_required(col("a", not_null=True, identity="d")))

    def test_geom_compat(self):
        self.assertTrue(importinto.geom_compat("Point", "MULTIPOINT"))
        self.assertTrue(importinto.geom_compat("3D Polygon", "POLYGON"))
        self.assertFalse(importinto.geom_compat("Point", "POLYGON"))
        self.assertTrue(importinto.geom_compat("Point", "GEOMETRY"))
        self.assertTrue(importinto.geom_compat("", "POLYGON"))

    def test_merge_sql_shape_and_safety(self):
        t = TableRef("public", "shops", 1, "r")
        geo = {"column": "geom", "type": "POINT", "srid": 32639, "geography": False}
        stmts = importinto.merge_statements(t, COLS, {"name": "c1", "qty": "c2", "Owner Name": "c3"}, "_gp_imp_7",
                                            replace=True, geo=geo, dims=2, with_geom=True)
        text = [s.as_string(None) for s in stmts]
        self.assertTrue(text[0].startswith('TRUNCATE TABLE "public"."shops"'))
        self.assertIn('INSERT INTO "public"."shops" ("name", "qty", "Owner Name", "geom")', text[1])
        self.assertIn("NULLIF(btrim(CAST(s.\"c2\" AS text)), '')", text[1])  # عدد از متن خالی NULL می‌شود
        self.assertIn("ST_Transform", text[1])
        self.assertIn("ST_Force2D", text[1])
        self.assertNotIn("NULLIF(btrim(CAST(s.\"c1\"", text[1])  # متن خالی، متن می‌ماند
        self.assertEqual(len(importinto.merge_statements(t, COLS, {"name": "c1"}, "_gp_imp_7", replace=False, geo=None,
                                                         dims=None, with_geom=False)), 1)

    def test_merge_rejects_bad_targets_and_staging(self):
        t = TableRef("public", "shops", 1, "r")
        for m in ({"id": "c"}, {"area": "c"}, {"geom": "c"}, {"nope": "c"}, {}):
            with self.assertRaises(importinto.IntoError, msg=m):
                importinto.merge_statements(t, COLS, m, "_gp_imp_7", replace=False, geo=None, dims=None, with_geom=False)
        with self.assertRaises(importinto.IntoError):
            importinto.merge_statements(t, COLS, {"name": "c"}, 'x"; DROP TABLE y;--', replace=False, geo=None,
                                        dims=None, with_geom=False)


FEATURES = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"Name": f"فروشگاه {i}", "QTY": str(i * 10), "extra": "x"},
     "geometry": {"type": "Point", "coordinates": [51.40 + i * 0.001, 35.70]}} for i in range(1, 4)]}


@unittest.skipUnless(PG_HOST and HAS_GDAL, "TEST_PG_HOST یا ogr2ogr در دسترس نیست")
@override_settings(ALLOWED_HOSTS=["testserver"])
class IntoIntegrationTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        o = override_settings(IMPORT_ROOT=str(self.tmp / "imports"), BACKUP_ROOT=str(self.tmp / "bk"))
        o.enable()
        self.addCleanup(o.disable)
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000098")
        self.db = db_services.create_database(self.user, f"ii_{uuid.uuid4().hex[:8]}", "Into-Pass-123", ["postgis"])
        self.addCleanup(self._drop)
        self.conn_kw = dict(host=server.host, port=server.port, user=self.db.role_name, password="Into-Pass-123",
                            dbname=self.db.db_name, autocommit=True)
        self.sql("CREATE TABLE shops(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name text NOT NULL, "
                 "qty integer, geom geometry(Point, 32639))")
        self.sql("INSERT INTO shops(name, qty) VALUES ('قدیمی', 1)")
        self.client.force_login(self.user)

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def sql(self, q, *a):
        with psycopg.connect(**self.conn_kw) as c:
            cur = c.execute(q, a)
            return cur.fetchall() if cur.description else []

    def start(self, content: bytes, name="shops.geojson", into="public.shops"):
        r = self.client.post(reverse("databases:import", args=[self.db.pk]),
                             {"file": SimpleUploadedFile(name, content), "into": into})
        job = Job.objects.filter(kind="import").latest("pk")
        return r, job, reverse("databases:import_review", args=[self.db.pk, job.pk])

    def geojson(self, data=None):
        return json.dumps(data or FEATURES, ensure_ascii=False).encode()

    def test_append_with_auto_mapping_and_reprojection(self):
        r, job, url = self.start(self.geojson())
        self.assertRedirects(r, url)
        page = self.client.get(url)
        self.assertContains(page, "ورود به جدول موجود")
        self.assertContains(page, 'name="map_qty"')
        job.refresh_from_db()
        self.assertEqual(job.params["into"], {"schema": "public", "table": "shops"})
        self.assertEqual(set(job.params["into_map"]), {"name", "qty"})  # نام‌ها خودکار (بدون توجه به بزرگی حروف) جور شد
        self.client.post(url, {"layer_into": "0", "srid_0": "4326", "map_name": job.params["into_map"]["name"],
                               "map_qty": job.params["into_map"]["qty"], "into_mode": "append", "action": "go"})
        job.refresh_from_db()
        self.assertEqual(job.status, "queued")
        jobs.run_inline(job)
        self.assertEqual(job.status, "done", job.message)
        self.assertIn("۳ سطر", job.message)
        rows = self.sql("SELECT name, qty, ST_SRID(geom), ST_X(ST_Transform(geom, 4326)) FROM shops ORDER BY id")
        self.assertEqual(len(rows), 4)  # سطر قدیمی دست‌نخورده
        self.assertEqual(rows[0][:2], ("قدیمی", 1))
        self.assertEqual(rows[1][:3], ("فروشگاه 1", 10, 32639))
        self.assertAlmostEqual(rows[1][3], 51.401, places=4)  # از ۴۳۲۶ به UTM تبدیل شد
        self.assertEqual(self.sql("SELECT count(*) FROM pg_tables WHERE tablename LIKE '\\_gp\\_imp\\_%%'")[0][0], 0)
        self.assertFalse((self.tmp / "imports" / str(job.pk)).exists())

    def test_replace_needs_typed_confirmation_and_clears_old_rows(self):
        _, job, url = self.start(self.geojson())
        m = job.params["into_map"]
        data = {"layer_into": "0", "srid_0": "4326", "map_name": m["name"], "into_mode": "replace", "action": "go"}
        r = self.client.post(url, data)
        self.assertContains(r, "نام جدول را دقیقاً")
        self.client.post(url, {**data, "confirm": "shops"})
        job.refresh_from_db()
        jobs.run_inline(job)
        self.assertEqual(job.status, "done", job.message)
        self.assertEqual([r[0] for r in self.sql("SELECT name FROM shops ORDER BY id")],
                         ["فروشگاه 1", "فروشگاه 2", "فروشگاه 3"])

    def test_bad_value_rolls_everything_back(self):
        bad = json.loads(json.dumps(FEATURES))
        bad["features"][2]["properties"]["QTY"] = "abc"
        _, job, url = self.start(self.geojson(bad))
        m = job.params["into_map"]
        self.client.post(url, {"layer_into": "0", "srid_0": "4326", "map_name": m["name"], "map_qty": m["qty"],
                               "into_mode": "replace", "confirm": "shops", "action": "go"})
        job.refresh_from_db()
        jobs.run_inline(job)
        self.assertEqual(job.status, "failed")
        self.assertIn("جدول تغییری نکرد", job.message)
        self.assertEqual([r[0] for r in self.sql("SELECT name FROM shops")], ["قدیمی"])  # حتی TRUNCATE برگشت
        self.assertEqual(self.sql("SELECT count(*) FROM pg_tables WHERE tablename LIKE '\\_gp\\_imp\\_%%'")[0][0], 0)

    def test_required_column_and_geometry_checks(self):
        _, job, url = self.start(self.geojson())
        r = self.client.post(url, {"layer_into": "0", "srid_0": "4326", "map_qty": "1", "action": "go"})
        self.assertContains(r, "«name» الزامی است")
        job.refresh_from_db()
        self.assertEqual(job.status, "draft")
        # فایل چندضلعی در جدول نقطه‌ای
        poly = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": "a"}, "geometry": {
            "type": "Polygon", "coordinates": [[[51, 35], [51.1, 35], [51.1, 35.1], [51, 35]]]}}]}
        _, job2, url2 = self.start(self.geojson(poly), name="poly.geojson")
        r = self.client.post(url2, {"layer_into": "0", "srid_0": "4326", "map_name": "0", "action": "go"})
        self.assertContains(r, "نمی‌خواند")

    def test_csv_into_table_with_xy_and_empty_numbers(self):
        csv = "name,qty,lon,lat\nالف,5,51.40,35.70\nب,,51.41,35.71\n"
        r, job, url = self.start(csv.encode("utf-8"), name="data.csv")
        self.assertRedirects(r, url)
        job.refresh_from_db()
        m = job.params["into_map"]
        self.assertEqual(set(m), {"name", "qty"})
        self.client.post(url, {"layer_into": "0", "srid_0": "4326", "map_name": m["name"], "map_qty": m["qty"],
                               "into_mode": "append", "csv_mode": "xy", "csv_x": "lon", "csv_y": "lat", "action": "go"})
        job.refresh_from_db()
        jobs.run_inline(job)
        self.assertEqual(job.status, "done", job.message)
        rows = self.sql("SELECT name, qty, geom IS NOT NULL FROM shops WHERE name <> 'قدیمی' ORDER BY id")
        self.assertEqual(rows, [("الف", 5, True), ("ب", None, True)])

    def test_entry_points_and_permissions(self):
        page = self.client.get(reverse("databases:explore_table", args=[self.db.pk, "public", "shops"]))
        self.assertContains(page, "?into=public.shops")
        r = self.client.get(reverse("databases:import", args=[self.db.pk]) + "?into=public.shops")
        self.assertContains(r, "public.shops")
        r = self.client.get(reverse("databases:import", args=[self.db.pk]) + "?into=public.nope")
        self.assertEqual(r.status_code, 302)
        other = User.objects.create_user("09120000099")
        self.client.force_login(other)
        r = self.client.get(reverse("databases:import", args=[self.db.pk]) + "?into=public.shops")
        self.assertEqual(r.status_code, 404)
