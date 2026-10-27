"""ورود فایل، خروجی چندقالبی و پزشک داده؛ واحد + یکپارچه روی PostGIS واقعی (TEST_PG_HOST و ogr2ogr)."""
import json
import os
import shutil
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path

import psycopg
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases import gdal
from databases import services as db_services
from databases.explorer import Explorer
from databases.models import DatabaseServer
from databases.provisioner import Provisioner
from jobs import services as jobs
from jobs.models import Job

PG_HOST = os.environ.get("TEST_PG_HOST", "")
HAS_GDAL = bool(shutil.which("ogr2ogr"))


def _shapefile_zip(folder: Path, encoding: str, with_cpg: bool) -> Path:
    """Shapefile نقطه‌ای کوچک با نام‌های فارسی (بدون نیاز به کتابخانه؛ با ogr2ogr از GeoJSON)."""
    src = folder / "pts.geojson"
    src.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": f"مدرسه {i}", "n": i},
         "geometry": {"type": "Point", "coordinates": [535000 + i * 100, 3950000]}} for i in range(1, 6)]},
        ensure_ascii=False), encoding="utf-8")
    out = folder / "shp"
    out.mkdir()
    gdal._run(["ogr2ogr", "-f", "ESRI Shapefile", str(out / "pts.shp"), str(src), "-a_srs", "EPSG:32639",
               "-lco", f"ENCODING={encoding}"])
    z = folder / "pts.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in out.iterdir():
            if f.suffix == ".cpg" and not with_cpg:
                continue
            zf.write(f, f.name)
    return z


class UnitTests(TestCase):
    def test_table_names(self):
        self.assertEqual(gdal.default_table_name("Schools-2024"), "schools_2024")
        self.assertEqual(gdal.default_table_name("مدارس"), "layer")
        self.assertEqual(gdal.default_table_name("123abc"), "layer_123abc")
        self.assertTrue(gdal.TABLE_RE.match("parcels_1"))
        self.assertFalse(gdal.TABLE_RE.match("1parcels"))
        self.assertFalse(gdal.TABLE_RE.match('x"; drop'))

    def test_network_disabled_for_gdal(self):
        env = gdal._env()
        self.assertEqual(env["GDAL_HTTP_PROXY"], "127.0.0.1:9")

    @unittest.skipUnless(HAS_GDAL, "ogr2ogr not installed")
    def test_encoding_detection_and_inspect(self):
        with tempfile.TemporaryDirectory() as d:
            z = _shapefile_zip(Path(d), "CP1256", with_cpg=False)
            self.assertEqual(gdal.guess_encoding(z), "CP1256")
            info = gdal.inspect(z)
            lyr = info["layers"][0]
            self.assertEqual((lyr["name"], lyr["count"], lyr["geom_type"], lyr["srid"]), ("pts", 5, "Point", 32639))
            self.assertEqual(lyr["sample"][0]["name"], "مدرسه 1")
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(gdal.guess_encoding(_shapefile_zip(Path(d), "UTF-8", with_cpg=True)))

    @unittest.skipUnless(HAS_GDAL, "ogr2ogr not installed")
    def test_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.geojson"
            p.write_text("not json")
            with self.assertRaises(gdal.GdalError):
                gdal.inspect(p)


@unittest.skipUnless(PG_HOST and HAS_GDAL, "TEST_PG_HOST or ogr2ogr missing")
@override_settings(ALLOWED_HOSTS=["testserver"])
class ImportExportIntegrationTests(TestCase):
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
        self.user = User.objects.create_user("09120000097")
        self.db = db_services.create_database(self.user, f"im_{uuid.uuid4().hex[:8]}", "Import-Pass-12", ["postgis"])
        self.addCleanup(self._drop)
        self.conn_kw = dict(host=server.host, port=server.port, user=self.db.role_name, password="Import-Pass-12",
                            dbname=self.db.db_name, autocommit=True)
        self.client.force_login(self.user)

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _sql(self, q):
        with psycopg.connect(**self.conn_kw) as c:
            cur = c.execute(q)
            return cur.fetchall() if cur.description else []

    def test_upload_review_import_flow(self):
        z = _shapefile_zip(self.tmp, "CP1256", with_cpg=False)
        r = self.client.post(reverse("databases:import", args=[self.db.pk]),
                             {"file": SimpleUploadedFile("مدارس.zip", z.read_bytes())})
        job = Job.objects.get(kind="import")
        self.assertRedirects(r, reverse("databases:import_review", args=[self.db.pk, job.pk]))
        r = self.client.get(r.url)
        self.assertContains(r, "مدرسه 1")  # نمونه با انکودینگ درست
        url = reverse("databases:import_review", args=[self.db.pk, job.pk])
        r = self.client.post(url, {"sel_0": "on", "table_0": "Bad Name", "srid_0": "32639", "mode_0": "create"})
        self.assertContains(r, "مجاز نیست")
        self.client.post(url, {"sel_0": "on", "table_0": "schools", "srid_0": "32639", "mode_0": "create",
                               "to4326_0": "on", "action": "go"})
        job.refresh_from_db()
        self.assertEqual(job.status, "queued")
        jobs.run_inline(job)
        self.assertEqual(job.status, "done", job.message)
        self.assertFalse((self.tmp / "imports" / str(job.pk)).exists())  # فایل آپلودی پاک شد
        rows = self._sql("SELECT count(*), min(name), min(ST_SRID(geom)) FROM schools")
        self.assertEqual(rows[0], (5, "مدرسه 1", 4326))
        owner = self._sql("SELECT tableowner FROM pg_tables WHERE tablename='schools'")[0][0]
        self.assertEqual(owner, self.db.role_name)
        # بدون مشکل: کلید اصلی و نمایه مکانی ساخته شده‌اند
        issues = [i for i in Explorer(self.db).health() if i["table"] == "schools"]
        self.assertEqual([i["fix"] for i in issues if i["fix"] != "analyze"], [])

    def _upload_csv(self, text: str, name="شعبه‌ها.csv", encoding="utf-8"):
        self.client.post(reverse("databases:import", args=[self.db.pk]),
                         {"file": SimpleUploadedFile(name, text.encode(encoding))})
        job = Job.objects.filter(kind="import").latest("pk")
        return job, reverse("databases:import_review", args=[self.db.pk, job.pk])

    def test_csv_odd_column_names_get_geometry(self):
        """نام‌های غیرمعمول طول و عرض، رقم فارسی و جای برعکس: ستون geom نباید خالی بماند."""
        job, url = self._upload_csv("کد;مختصات شمالی (درجه);مختصات شرقی (درجه);نام\n"
                                    "1;۳۵٫۶۸۹۲;۵۱٫۳۸۹۰;شعبه مرکزی\n2;35.7012;51.4012;شعبه دو\n3;;;بی‌آدرس\n")
        r = self.client.get(url)
        self.assertContains(r, "مکان هر سطر کجای فایل است")
        self.assertContains(r, "مختصات قابل‌خواندن نداشت")  # سطر سوم
        self.client.post(url, {"sel_0": "on", "table_0": "branches", "srid_0": "4326", "mode_0": "create",
                               "csv_mode": "xy", "csv_x": "مختصات شرقی (درجه)", "csv_y": "مختصات شمالی (درجه)",
                               "action": "go"})
        job.refresh_from_db()
        self.assertEqual(job.status, "queued", job.params.get("layers"))
        jobs.run_inline(job)
        self.assertEqual(job.status, "done", job.message)
        self.assertIn("بدون هندسه", job.message)
        rows = self._sql("SELECT count(*), count(geom), min(ST_SRID(geom)), round(min(ST_X(ST_GeometryN(geom,1)))::numeric, 3),"
                         " round(min(ST_Y(ST_GeometryN(geom,1)))::numeric, 3) FROM branches")
        self.assertEqual(rows[0][:3], (3, 2, 4326))
        self.assertEqual([float(v) for v in rows[0][3:]], [51.389, 35.689])
        cols = {c for (c,) in self._sql("SELECT column_name FROM information_schema.columns WHERE table_name='branches'")}
        self.assertNotIn("gp_x", cols)
        self.assertIn("نام", cols)

    def test_csv_manual_mapping_and_utm(self):
        """کاربر ستون‌ها را دستی انتخاب می‌کند؛ مختصات UTM بدون زون خطا می‌دهد و با زون تبدیل می‌شود."""
        job, url = self._upload_csv("a,b,c\np1,535000.5,3950000.2\np2,535100.0,3950100.0\n", name="pts.csv")
        job.refresh_from_db()
        self.assertEqual(job.params["layers"][0]["srid"], None)
        # بدون انتخاب ستون‌ها: تشخیص خودکار از روی مقدار
        self.assertEqual((job.params["csv"]["spec"]["x"], job.params["csv"]["spec"]["y"]), ("b", "c"))
        r = self.client.post(url, {"sel_0": "on", "table_0": "pts", "srid_0": "", "mode_0": "create",
                                   "csv_mode": "xy", "csv_x": "b", "csv_y": "c", "action": "go"})
        self.assertContains(r, "سیستم مختصات لایه")
        # انتخاب اشتباه ستون‌ها با 4326 → خطای محدوده
        r = self.client.post(url, {"sel_0": "on", "table_0": "pts", "srid_0": "4326", "mode_0": "create",
                                   "csv_mode": "xy", "csv_x": "b", "csv_y": "c", "action": "go"})
        self.assertContains(r, "بیرون از محدوده")
        self.client.post(url, {"sel_0": "on", "table_0": "pts", "srid_0": "32639", "mode_0": "create",
                               "to4326_0": "on", "csv_mode": "xy", "csv_x": "b", "csv_y": "c", "action": "go"})
        job.refresh_from_db()
        jobs.run_inline(job)
        self.assertEqual(job.status, "done", job.message)
        lon, lat, srid = self._sql("SELECT ST_X(ST_GeometryN(geom,1)), ST_Y(ST_GeometryN(geom,1)), ST_SRID(geom) FROM pts LIMIT 1")[0]
        self.assertEqual(srid, 4326)
        self.assertAlmostEqual(lon, 51.38, places=1)
        self.assertAlmostEqual(lat, 35.69, places=1)

    def test_csv_remap_pair_column(self):
        job, url = self._upload_csv('name,where\nA,"35.69, 51.41"\nB,"35.70, 51.42"\n', name="pair.csv")
        job.refresh_from_db()
        self.assertEqual(job.params["csv"]["spec"]["mode"], "pair")
        # کاربر نوع مکان را «بدون مکان» می‌کند و دوباره بررسی می‌کند
        self.client.post(url, {"sel_0": "on", "table_0": "pair", "mode_0": "create", "csv_mode": "none",
                               "action": "resample"})
        job.refresh_from_db()
        self.assertEqual((job.params["layers"][0]["geom_type"], job.params["layers"][0]["csv_mode"]), ("", "none"))
        self.client.post(url, {"sel_0": "on", "table_0": "pair", "mode_0": "create", "csv_mode": "pair",
                               "csv_pair": "where", "csv_pair_order": "latlon", "action": "resample"})
        job.refresh_from_db()
        self.assertEqual(job.params["layers"][0]["srid"], 4326)
        self.client.post(url, {"sel_0": "on", "table_0": "pair", "mode_0": "create", "srid_0": "4326",
                               "csv_mode": "pair", "csv_pair": "where", "csv_pair_order": "latlon", "action": "go"})
        jobs.run_inline(Job.objects.get(pk=job.pk))
        self.assertEqual(self._sql("SELECT count(geom), round(min(ST_X(ST_GeometryN(geom,1)))::numeric,2) FROM pair")[0][0], 2)

    def test_assign_and_reproject(self):
        """SRID اعلام‌شده کاربر + تبدیل به 4326 باید مختصات را واقعاً تبدیل کند (نه فقط برچسب)."""
        src = self.tmp / "utm.geojson"
        src.write_text('{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"a":1},'
                       '"geometry":{"type":"Point","coordinates":[535000,3950000]}}]}')
        gdal.import_layer(self.db, src, {"name": "utm", "table": "utm_pts", "srid": 32639, "assign_srid": True,
                                         "to4326": True, "mode": "create", "geom_type": "Point"}, None)
        lon, lat, srid = self._sql("SELECT ST_X(ST_GeometryN(geom, 1)), ST_Y(ST_GeometryN(geom, 1)), ST_SRID(geom) FROM utm_pts")[0]
        self.assertEqual(srid, 4326)
        self.assertAlmostEqual(lon, 51.38, places=1)
        self.assertAlmostEqual(lat, 35.69, places=1)

    def test_existing_table_needs_mode(self):
        self._sql("CREATE TABLE pts(id int)")
        z = _shapefile_zip(self.tmp, "UTF-8", with_cpg=True)
        self.client.post(reverse("databases:import", args=[self.db.pk]),
                         {"file": SimpleUploadedFile("pts.zip", z.read_bytes())})
        job = Job.objects.get(kind="import")
        url = reverse("databases:import_review", args=[self.db.pk, job.pk])
        r = self.client.post(url, {"sel_0": "on", "table_0": "pts", "srid_0": "32639", "mode_0": "create"})
        self.assertContains(r, "از قبل وجود دارد")
        self.client.post(url, {"sel_0": "on", "table_0": "pts", "srid_0": "32639", "mode_0": "overwrite"})
        jobs.run_inline(Job.objects.get(pk=job.pk))
        self.assertEqual(self._sql("SELECT count(*) FROM pts")[0][0], 5)

    def test_rejects_unknown_extension_and_quota(self):
        r = self.client.post(reverse("databases:import", args=[self.db.pk]),
                             {"file": SimpleUploadedFile("x.exe", b"MZ")})
        self.assertContains(r, "پشتیبانی نمی‌شود")
        self.assertFalse(Job.objects.exists())

    def test_export_formats(self):
        self._sql("CREATE TABLE parcels(id serial PRIMARY KEY, name text, geom geometry(Point, 4326))")
        self._sql("INSERT INTO parcels(name, geom) VALUES ('قطعه ۱', ST_SetSRID(ST_MakePoint(51.4, 35.7), 4326))")
        for fmt, magic in (("gpkg", b"SQLite format 3"), ("shp", b"PK"), ("kml", b"<?xml"), ("xlsx", b"PK"),
                           ("dxf", b"  0")):
            r = self.client.get(reverse("databases:explore_export", args=[self.db.pk, "public", "parcels", fmt]))
            self.assertEqual(r.status_code, 200, fmt)
            body = b"".join(r.streaming_content)
            self.assertTrue(body.startswith(magic), (fmt, body[:20]))
        r = self.client.get(reverse("databases:explore_export", args=[self.db.pk, "public", "parcels", "exe"]))
        self.assertEqual(r.status_code, 404)

    def test_health_finds_and_fixes(self):
        self._sql("CREATE TABLE bad(name text, geom geometry(Polygon, 4326))")
        self._sql("INSERT INTO bad VALUES ('x', ST_GeomFromText('POLYGON((0 0,1 1,1 0,0 1,0 0))', 4326))")
        ex = Explorer(self.db)
        fixes = sorted(i["fix"] for i in ex.health() if i["table"] == "bad")
        self.assertEqual(fixes, ["add_index", "add_pk", "analyze", "make_valid"])
        done, failed = ex.fix_all()
        self.assertEqual(failed, [])
        self.assertEqual([i for i in ex.health() if i["table"] == "bad"], [])
        self.assertTrue(self._sql("SELECT bool_and(ST_IsValid(geom)) FROM bad")[0][0])
        self.assertEqual(self._sql("SELECT type FROM geometry_columns WHERE f_table_name='bad'")[0][0], "MULTIPOLYGON")

    def test_legacy_browser_owned_table_fixed(self):
        ex = Explorer(self.db)
        with ex.connect(read_only=False) as conn:  # مثل کنسول قدیمی: بدون SET ROLE
            conn.execute("CREATE TABLE legacy(id int primary key)")
            conn.commit()
        self.assertEqual([i["fix"] for i in ex.health() if i["table"] == "legacy"], ["fix_owner"])
        ex.fix_all()
        owner = self._sql("SELECT tableowner FROM pg_tables WHERE tablename='legacy'")[0][0]
        self.assertEqual(owner, self.db.role_name)
