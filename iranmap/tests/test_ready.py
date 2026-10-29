"""داده آماده ایران از OSM: نواحی، برش و ورود به پایگاه داده کاربر، شبکه مسیریابی."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases import services as db_services
from databases.models import DatabaseServer
from databases.provisioner import Provisioner
from iranmap import osm, ready
from iranmap.models import Area
from jobs import services as jobs
from jobs.models import Job

PG_HOST = os.environ.get("TEST_PG_HOST", "")
HAS_TOOLS = all(shutil.which(t) for t in ("osmium", "ogr2ogr"))
HERE = Path(__file__).parent


def sample_pbf(dest_dir: Path) -> Path:
    xml = dest_dir / "sample.osm"
    subprocess.run([sys.executable, str(HERE / "fake_osm.py"), str(xml)], check=True, capture_output=True)
    pbf = dest_dir / "iran-latest.osm.pbf"
    subprocess.run(["osmium", "cat", "--overwrite", "-o", str(pbf), str(xml)], check=True, capture_output=True)
    return pbf


@unittest.skipUnless(PG_HOST and HAS_TOOLS, "TEST_PG_HOST, osmium or ogr2ogr missing")
@override_settings(ALLOWED_HOSTS=["testserver"])
class ReadyDataTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.osm_root = Path(tempfile.mkdtemp())
        sample_pbf(cls.osm_root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.osm_root, True)
        super().tearDownClass()

    def setUp(self):
        o = override_settings(OSM_ROOT=str(self.osm_root))
        o.enable()
        self.addCleanup(o.disable)
        osm.refresh_areas()
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000082")
        self.db = db_services.create_database(self.user, f"rd_{uuid.uuid4().hex[:8]}", "Ready-Pass-12", ["postgis"])
        self.addCleanup(self._drop)
        self.conn_kw = dict(host=server.host, port=server.port, user=self.db.role_name, password="Ready-Pass-12",
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

    def test_areas_from_file(self):
        levels = dict(Area.objects.values_list("level", "name"))
        self.assertEqual(levels, {"province": "نمونه", "county": "نمونه", "city": "شهر نمونه"})  # پیشوند استان/شهرستان برداشته می‌شود
        city = Area.objects.get(level="city")
        self.assertEqual(city.province, "نمونه")
        self.assertTrue(ready.routing_allowed(city))
        self.assertFalse(ready.routing_allowed(Area.objects.get(level="province")))
        r = self.client.get(reverse("iranmap:areas"), {"q": "نمونه"})
        labels = [a["label"] for a in r.json()["results"]]
        self.assertIn("شهرستان نمونه — استان نمونه", labels)
        self.assertIn("شهر نمونه — استان نمونه", labels)

    def test_import_flow(self):
        city = Area.objects.get(level="city")
        url = reverse("iranmap:ready", args=[self.db.pk])
        self.assertContains(self.client.get(url), "ODbL")
        r = self.client.post(url, {"area": city.pk, "datasets": ["roads", "pois", "buildings", "nope"]})
        self.assertRedirects(r, url)
        job = Job.objects.get(kind="osm_import")
        self.assertEqual(job.params["datasets"], ["roads", "pois", "buildings"])
        # یک درخواست در جریان کافی است
        r = self.client.post(url, {"area": city.pk, "datasets": ["roads"]})
        self.assertContains(r, "در حال انجام")
        jobs.run_inline(job)
        self.assertEqual(job.status, "done", job.message)
        rows = self._sql("SELECT count(*), count(*) FILTER (WHERE name LIKE 'خیابان%%') FROM osm_roads")[0]
        self.assertGreater(rows[0], 1000)
        self.assertGreater(rows[1], 0)
        self.assertGreater(self._sql("SELECT count(*) FROM osm_pois WHERE amenity = 'school'")[0][0], 10)
        owners = {r[0] for r in self._sql("SELECT tableowner FROM pg_tables WHERE tablename LIKE 'osm\\_%%'")}
        self.assertEqual(owners, {self.db.role_name})
        comment = self._sql("SELECT obj_description('osm_roads'::regclass)")[0][0]
        self.assertIn("ODbL", comment)
        self.assertEqual(self._sql("SELECT ST_SRID(geom) FROM osm_buildings LIMIT 1")[0][0], 4326)
        # ستون‌ها مقدار واقعی دارند، نه نام برچسب (SQLite نام ناشناخته در "" را رشته می‌گیرد)
        literal = self._sql("SELECT count(*) FROM osm_roads WHERE name IN ('name_fa', 'name:fa') OR "
                            "highway = 'highway'")[0][0]
        self.assertEqual(literal, 0)

    def test_validation(self):
        prov = Area.objects.get(level="province")
        with self.assertRaisesMessage(ready.ReadyError, "دست‌کم"):
            ready.request_import(self.db, self.user, prov, [], False)
        with self.assertRaisesMessage(ready.ReadyError, "استان کامل"):
            ready.request_import(self.db, self.user, prov, ["roads"], True)
        for _ in range(ready.DAILY_LIMIT):
            Job.objects.create(kind="osm_import", database=self.db, status="done")
        with self.assertRaisesMessage(ready.ReadyError, "در روز"):
            ready.request_import(self.db, self.user, prov, ["roads"], False)

    def test_routing_network(self):
        if not ready.pgrouting_available(self.db):
            self.skipTest("pgrouting روی سرور آزمون نصب نیست")
        if not shutil.which("osm2pgrouting"):
            self.skipTest("osm2pgrouting نصب نیست")
        city = Area.objects.get(level="city")
        job = ready.request_import(self.db, self.user, city, [], True)
        jobs.run_inline(job)
        self.assertEqual(job.status, "done", job.message)
        n = self._sql("""
            WITH a AS (SELECT id FROM routing.ways_vertices_pgr
                       ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(51.389, 35.70), 4326) LIMIT 1),
                 b AS (SELECT id FROM routing.ways_vertices_pgr
                       ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint(51.42, 35.76), 4326) LIMIT 1)
            SELECT count(*) FROM pgr_dijkstra('SELECT gid AS id, source, target, cost, reverse_cost FROM routing.ways',
                                              (SELECT id FROM a), (SELECT id FROM b))""")[0][0]
        self.assertGreater(n, 3)
        owners = {r[0] for r in self._sql("SELECT tableowner FROM pg_tables WHERE schemaname = 'routing'")}
        self.assertEqual(owners, {self.db.role_name})


@override_settings(ALLOWED_HOSTS=["testserver"])
class AreaSearchTests(TestCase):
    """جست‌وجوی محدوده بدون نیاز به ابزار OSM: ترتیب نتیجه و املای عربی/فارسی."""

    def setUp(self):
        box = [51.0, 35.0, 51.5, 35.4]
        big = [50.0, 34.0, 53.0, 36.5]
        mk = lambda name, level, bb: Area.objects.create(name=name, level=level, bbox=bb, geometry={})  # noqa: E731
        mk("تهران", "province", big)
        mk("تهران", "county", box)
        mk("تهران", "city", box)
        mk("شهر ری", "county", box)
        mk("کرمان", "province", big)
        self.user = User.objects.create_user("09120000083")
        self.client.force_login(self.user)

    def _search(self, q):
        return self.client.get(reverse("iranmap:areas"), {"q": q}).json()["results"]

    def test_city_before_county_before_province(self):
        rows = self._search("تهران")
        self.assertEqual([r["level"] for r in rows], ["city", "county", "province"])
        self.assertTrue(rows[0]["routing"])
        self.assertFalse(rows[-1]["routing"])

    def test_exact_name_first(self):
        Area.objects.create(name="تهران‌سر", level="city", bbox=[51, 35, 51.1, 35.1], geometry={})
        self.assertEqual(self._search("تهران")[0]["label"].split(" — ")[0], "شهر تهران")

    def test_arabic_letters_match(self):
        self.assertEqual(len(self._search("كرمان")), 1)
        Area.objects.create(name="يزد", level="city", bbox=[54, 31, 54.1, 31.1], geometry={})
        self.assertEqual(len(self._search("یزد")), 1)

    def test_county_level_six_is_mapped(self):
        self.assertEqual(osm.LEVELS["6"], "county")


def _sq(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


@override_settings(ALLOWED_HOSTS=["testserver"])
class HierarchyTests(TestCase):
    """استان ← شهرستان/شهر با هندسه واقعی، و فهرست دو مرحله‌ای صفحه."""

    def setUp(self):
        # البرز مثلثی کوچک است که جعبه‌اش مرکز شهرستان تهران را دربر می‌گیرد، ولی خودش آن را ندارد
        tri = {"type": "Polygon", "coordinates": [[[50.0, 36.0], [51.0, 36.0], [50.0, 35.0], [50.0, 36.0]]]}
        self.alborz = Area.objects.create(name="استان البرز", level="province", bbox=[50, 35, 51, 36], geometry=tri)
        self.tehran = Area.objects.create(name="استان تهران", level="province", bbox=[49, 34, 53, 37],
                                          geometry=_sq(49, 34, 53, 37))
        self.county = Area.objects.create(name="شهرستان تهران", level="county", bbox=[50.6, 35.2, 50.8, 35.4],
                                          geometry=_sq(50.6, 35.2, 50.8, 35.4))
        self.city = Area.objects.create(name="شهر ری", level="city", bbox=[50.65, 35.25, 50.7, 35.3],
                                        geometry=_sq(50.65, 35.25, 50.7, 35.3))
        osm._assign_parents()
        self.user = User.objects.create_user("09120000084")
        self.client.force_login(self.user)

    def test_clean_name(self):
        self.assertEqual(osm.clean_name("province", "استان تهران"), "تهران")
        self.assertEqual(osm.clean_name("county", "شهرستان تهران"), "تهران")
        self.assertEqual(osm.clean_name("city", "شهر ری"), "شهر ری")  # نام خود شهر است
        self.assertEqual(osm.clean_name("province", "استان"), "استان")

    def test_parent_uses_polygon_not_bbox(self):
        self.county.refresh_from_db()
        self.city.refresh_from_db()
        self.assertEqual(self.county.province, "استان تهران")
        self.assertEqual(self.city.province, "استان تهران")

    def test_label_has_no_double_prefix(self):
        self.county.refresh_from_db()
        self.city.refresh_from_db()
        self.assertEqual(self.county.label, "شهرستان تهران — استان تهران")
        self.assertEqual(self.city.label, "شهر ری — استان تهران")
        self.assertEqual(self.tehran.label, "استان تهران")

    def test_provinces_endpoint(self):
        r = self.client.get(reverse("iranmap:areas"), {"level": "province"}).json()["results"]
        self.assertEqual([a["name"] for a in r], ["استان البرز", "استان تهران"])

    def test_children_only_of_that_province(self):
        r = self.client.get(reverse("iranmap:areas"), {"province": self.tehran.pk}).json()["results"]
        self.assertEqual([(a["level"], a["name"]) for a in r], [("county", "شهرستان تهران"), ("city", "شهر ری")])
        self.assertTrue(all(a["routing"] for a in r))
        self.assertEqual(self.client.get(reverse("iranmap:areas"), {"province": self.alborz.pk}).json()["results"], [])
        self.assertEqual(self.client.get(reverse("iranmap:areas"), {"province": "x"}).json()["results"], [])

    def test_representative_point_inside_concave(self):
        # شکل C: مرکز ثقل بیرون از ناحیه است
        c = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 1], [1, 1], [1, 9], [10, 9], [10, 10], [0, 10], [0, 0]]]}
        x, y = osm.representative_point(c)
        self.assertTrue(osm._contains(c, x, y))


class NoSourceTests(TestCase):
    def test_no_source_file(self):
        with tempfile.TemporaryDirectory() as d, override_settings(OSM_ROOT=d):
            self.assertIsNone(osm.source_info())
            with self.assertRaises(osm.OsmError):
                osm.refresh_areas()


@unittest.skipUnless(HAS_TOOLS, "osmium or ogr2ogr missing")
class DownloadSourceTests(TestCase):
    def test_download_validates_part_file_with_osmium(self):
        """فایل موقت باید پسوند .osm.pbf داشته باشد، وگرنه osmium نوعش را نمی‌شناسد (خطای واقعی production)."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as root:
            pbf = sample_pbf(Path(src))
            with override_settings(OSM_ROOT=root, OSM_SOURCE_URL=pbf.as_uri()):
                dest = osm.download_source()
            self.assertTrue(dest.exists())
            self.assertGreater(dest.stat().st_size, 1024)
            self.assertEqual([p.name for p in Path(root).rglob("*.part*")], [])
