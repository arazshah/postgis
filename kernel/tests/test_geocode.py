"""ژئوکدر فارسی: نرمال‌سازی، شکستن نشانی، تطبیق، گازتیر روی PostGIS واقعی و آزمایشگاه پنل."""
import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

import psycopg
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from kernel import geocode, persian
from kernel.geocode import entry

PG_HOST = os.environ.get("TEST_PG_HOST", "")


def gaz():
    gz = geocode.Gazetteer(cities=[entry("تهران", 51.4, 35.7, kind="city", pop=9_000_000), entry("کرج", 50.99, 35.83, kind="city", pop=1_500_000)],
                           center=(51.4, 35.7), city_name="تهران")
    gz.streets = [e for e in (entry("خیابان دکتر شریعتی", 51.43, 35.76, n=40), entry("بلوار کشاورز", 51.40, 35.73, n=20),
                              entry("خیابان ولیعصر", 51.41, 35.72, n=90), entry("میدان آزادی", 51.34, 35.70, n=3),
                              entry("خیابان انقلاب", 51.39, 35.70, n=50), entry("خیابان آزادی", 51.37, 35.70, n=30),
                              entry("خیابان شهید بهشتی", 51.42, 35.74, n=25), entry("خیابان سی تیر", 51.40, 35.70, n=5)) if e]
    gz.pois = [entry("بیمارستان امام خمینی", 51.38, 35.70), entry("برج میلاد", 51.37, 35.74)]
    gz.hoods = [entry("تجریش", 51.43, 35.80, kind="suburb"), entry("پونک", 51.33, 35.76, kind="suburb")]
    return gz


class NormalizeTests(SimpleTestCase):
    def test_letters_digits_marks_and_spaces(self):
        n = persian.normalize
        self.assertEqual(n("  بلوار كشاورز  "), "بلوار کشاورز")
        self.assertEqual(n("خيابان آزادي"), n("خیابان ازادی"))
        self.assertEqual(n("پلاک ۱۲۳ و ٤٥٦"), "پلاک 123 و 456")
        self.assertEqual(n("ولی‌عصر"), "ولی عصر")  # نیم‌فاصله
        self.assertEqual(n("مُحَمَّد"), n("محمد"))
        self.assertEqual(n("کشیـــده"), n("کشیده"))
        self.assertEqual(n("خ. ولیعصر"), "خیابان ولیعصر")
        self.assertEqual(n("Valiasr St."), "valiasr st")
        self.assertEqual(n(None), "")

    def test_core_drops_types_and_titles(self):
        self.assertEqual(persian.core("خیابان دکتر شریعتی"), "شریعتی")
        self.assertEqual(persian.core("بلوار امام خمینی"), "خمینی")
        self.assertEqual(persian.core("میدان"), "میدان")  # چیزی نماند: خودش

    def test_parse_address(self):
        a = persian.parse_address("تهران، خ. ولیعصر، کوچه‌ی دوم، پلاک ۱۲")
        self.assertEqual((a["street"], a["number"], a["street_type"]), ("خیابان ولیعصر", "12", "خیابان"))
        self.assertEqual(a["parts"][0], "تهران")
        b = persian.parse_address("بلوار كشاورز نبش خيابان ۱۶ آذر")
        self.assertEqual(b["parts"], ["بلوار کشاورز", "خیابان 16 اذر"])
        self.assertEqual(persian.parse_address("")["parts"], [])
        self.assertEqual(persian.parse_address("ایران، استان تهران، شهر تهران")["parts"], ["تهران", "تهران"])


class MatchTests(SimpleTestCase):
    def setUp(self):
        self.gz = gaz()

    def g(self, t):
        return geocode.geocode(self.gz, t)

    def test_exact_variants_and_abbreviations(self):
        for t in ("خیابان ولیعصر", "خ. ولیعصر", "تهران، خيابان وليعصر", "ولیعصر"):
            r = self.g(t)
            self.assertEqual((r.level, r.matched), ("street", "خیابان ولیعصر"), t)
            self.assertGreaterEqual(r.score, 0.85, t)

    def test_spacing_titles_and_subset(self):
        self.assertEqual(self.g("خیابان ولی عصر").matched, "خیابان ولیعصر")
        r = self.g("خ. شریعتی")
        self.assertEqual(r.matched, "خیابان دکتر شریعتی")
        self.assertEqual(self.g("خیابان بهشتی").matched, "خیابان شهید بهشتی")

    def test_typo_is_fuzzy_and_lower_confidence(self):
        r = self.g("بلوار کشاورزی")
        self.assertEqual(r.matched, "بلوار کشاورز")
        self.assertLess(r.score, 0.85)
        self.assertGreaterEqual(r.score, 0.6)

    def test_house_number_is_noted_not_used(self):
        r = self.g("خیابان ولیعصر، پلاک ۱۲")
        self.assertIn("پلاک 12", r.note)
        self.assertEqual((r.lon, r.lat), (51.41, 35.72))

    def test_intersection_phrase_and_poi_neighbourhood_city(self):
        self.assertEqual(self.g("بلوار کشاورز نبش خیابان ۱۶ آذر").matched, "بلوار کشاورز")
        self.assertEqual((self.g("بیمارستان امام").level, self.g("برج میلاد").level), ("poi", "poi"))
        self.assertEqual(self.g("تجریش").level, "neighbourhood")
        c = self.g("تهران")
        self.assertEqual((c.level, c.score), ("city", 0.4))

    def test_other_city_is_not_matched_to_local_street(self):
        r = self.g("کرج، بلوار کشاورز")
        self.assertLessEqual(r.score, 0.5)  # شهر دیگر ذکر شده؛ اطمینان پایین
        r2 = self.g("کرج، خیابان ناشناس")
        self.assertEqual((r2.level, r2.matched), ("city", "کرج"))

    def test_unknown_and_empty(self):
        for t in ("خیابان ناشناس", "", "   ", "،،،"):
            r = self.g(t)
            self.assertEqual((r.level, r.score), ("none", 0.0), t)
            self.assertEqual(r.label, "—")

    def test_ambiguity_lowers_score(self):
        gz = gaz()
        gz.streets = [e for e in gz.streets if e.name != "خیابان انقلاب"] + [entry("خیابان انقلاب غربی", 51.30, 35.70), entry("خیابان انقلاب شرقی", 51.45, 35.70)]
        r = geocode.geocode(gz, "انقلاب")
        self.assertEqual(r.level, "street")
        self.assertTrue(r.ambiguous)
        self.assertIn("مشابه", r.note)
        self.assertLess(r.score, 0.8)
        self.assertFalse(geocode.geocode(gaz(), "خیابان انقلاب").ambiguous)

    def test_similar_names_are_not_confused(self):
        self.assertEqual(self.g("میدان آزادی").matched, "میدان آزادی")
        self.assertEqual(self.g("خیابان آزادی").matched, "خیابان آزادی")

    def test_stats(self):
        res = geocode.geocode_many(self.gz, ["خیابان ولیعصر", "تجریش", "تهران", "ناشناس", "بلوار کشاورزی"])
        st = geocode.stats(res)
        self.assertEqual((st["total"], st["none"]), (5, 1))
        self.assertEqual(st["levels"]["street"], 2)
        self.assertEqual(st["matched"], 3)  # شهر (۰٫۴) شمرده نمی‌شود
        self.assertEqual(geocode.stats([])["total"], 0)

    def test_large_gazetteer_pruning_still_finds_match(self):
        gz = gaz()
        gz.streets += [entry(f"خیابان نمونه {i}", 51 + i * 1e-4, 35) for i in range(4000)]
        self.assertEqual(geocode.geocode(gz, "خیابان ولیعصر").matched, "خیابان ولیعصر")
        self.assertEqual(geocode.geocode(gz, "خ. ولی عصر").matched, "خیابان ولیعصر")


@unittest.skipUnless(PG_HOST, "به PostgreSQL آزمون نیاز دارد (TEST_PG_HOST)")
class LoadRealTests(SimpleTestCase):
    def setUp(self):
        kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                  password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        self.kw = kw
        with psycopg.connect(dbname="postgres", **kw) as c:
            c.execute("DROP DATABASE IF EXISTS pagekit_geo")
            c.execute("CREATE DATABASE pagekit_geo")
        with psycopg.connect(dbname="pagekit_geo", **kw) as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            c.execute("CREATE TABLE osm_roads (osm_id bigint, name text, highway text, geom geometry(LineString,4326))")
            c.execute("CREATE TABLE osm_pois (osm_id bigint, name text, amenity text, geom geometry(Point,4326))")
            c.execute("CREATE TABLE osm_places (osm_id bigint, name text, place text, population text, geom geometry(Point,4326))")
            # تهران (مرکز ۵۱٫۴،۳۵٫۷) و کرج دور؛ «خیابان ولیعصر» در هر دو شهر
            c.execute("""INSERT INTO osm_places VALUES (1,'تهران','city','8 693 706',ST_SetSRID(ST_MakePoint(51.4,35.7),4326)),
              (2,'کرج','city','1592492',ST_SetSRID(ST_MakePoint(50.99,35.83),4326)), (3,'تجریش','suburb',NULL,ST_SetSRID(ST_MakePoint(51.43,35.8),4326)),
              (4,'دهکده','village',NULL,ST_SetSRID(ST_MakePoint(60,30),4326))""")
            c.execute("""INSERT INTO osm_roads VALUES
              (10,'خیابان ولیعصر','primary',ST_SetSRID(ST_GeomFromText('LINESTRING(51.40 35.70,51.41 35.74)'),4326)),
              (11,'خیابان ولیعصر','primary',ST_SetSRID(ST_GeomFromText('LINESTRING(51.41 35.74,51.42 35.78)'),4326)),
              (12,'خیابان ولیعصر','primary',ST_SetSRID(ST_GeomFromText('LINESTRING(50.99 35.83,50.98 35.84)'),4326)),
              (13,'بلوار کشاورز','primary',ST_SetSRID(ST_GeomFromText('LINESTRING(51.39 35.72,51.40 35.73)'),4326)),
              (14,NULL,'service',ST_SetSRID(ST_GeomFromText('LINESTRING(51.39 35.72,51.40 35.73)'),4326))""")
            c.execute("INSERT INTO osm_pois VALUES (20,'بیمارستان امام خمینی','hospital',ST_SetSRID(ST_MakePoint(51.38,35.70),4326))")
        self.ws = SimpleNamespace(pk=1)
        cat = mock.Mock()
        cat.tables.return_value = [SimpleNamespace(schema="public", name=n, kind="r", oid=i) for i, n in enumerate(("osm_roads", "osm_pois", "osm_places"))]

        @contextmanager
        def connect(ws, **k):
            conn = psycopg.connect(dbname="pagekit_geo", **kw)
            conn.autocommit = False
            try:
                yield conn
            finally:
                conn.close()

        for target, val in (("kernel.tenantdb.catalog", lambda ws: cat), ("kernel.tenantdb.connect", connect)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)
        self.cat = cat

    def test_cities_and_load_radius_limits_to_the_city(self):
        names = [c.name for c in geocode.cities(self.ws)]
        self.assertEqual(names, ["تهران", "کرج"])  # به ترتیب جمعیت؛ روستا و محله نیست
        gz = geocode.load(self.ws, "تهران", 15)
        self.assertEqual(sorted(e.name for e in gz.streets), ["بلوار کشاورز", "خیابان ولیعصر"])  # ولیعصرِ کرج دور است
        self.assertEqual(next(e for e in gz.streets if e.name == "خیابان ولیعصر").n, 2)
        self.assertEqual([e.name for e in gz.pois], ["بیمارستان امام خمینی"])
        self.assertEqual([e.name for e in gz.hoods], ["تجریش"])
        gz2 = geocode.load(self.ws, "کرج", 15)
        self.assertEqual([e.name for e in gz2.streets], ["خیابان ولیعصر"])

    def test_representative_point_is_on_the_street_and_in_the_right_city(self):
        r = geocode.geocode(geocode.load(self.ws, "تهران"), "خ. ولی عصر")
        self.assertEqual(r.level, "street")
        self.assertGreater(r.lon, 51.3)  # نه کرج (۵۰٫۹۹)
        r2 = geocode.geocode(geocode.load(self.ws, "کرج"), "خ. ولیعصر")
        self.assertLess(r2.lon, 51.0)

    def test_errors_are_persian_messages(self):
        with self.assertRaises(geocode.GeocodeError) as cm:
            geocode.load(self.ws, "شهر ناموجود")
        self.assertIn("پیدا نشد", str(cm.exception))
        self.cat.tables.return_value = []
        with self.assertRaises(geocode.GeocodeError) as cm:
            geocode.cities(self.ws)
        self.assertIn("داده آماده ایران", str(cm.exception))

    def test_name_with_sql_chars_is_just_data(self):
        with psycopg.connect(dbname="pagekit_geo", **self.kw) as c:
            c.execute("INSERT INTO osm_roads VALUES (99,'x''); DROP TABLE osm_roads;--','primary',ST_SetSRID(ST_GeomFromText('LINESTRING(51.40 35.70,51.41 35.74)'),4326))")
        geocode.load(self.ws, "تهران")
        with psycopg.connect(dbname="pagekit_geo", **self.kw) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM osm_roads").fetchone()[0], 6)


class LabViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.admin = get_user_model().objects.create_superuser(username="adm", phone="09120000400", password="x")
        self.client.force_login(self.admin)
        self.url = reverse("geocode_lab")

    def run_lab(self, text="خیابان ولیعصر\nتجریش\n=cmd|' /C calc'!A0", **over):
        gz = gaz()
        with mock.patch("kernel.workspace.peek", return_value=SimpleNamespace(pk=3, is_live=True)), mock.patch("kernel.geocode.load", return_value=gz):
            return self.client.post(self.url, {"ws": "3", "city": "تهران", "radius": "15", "text": text, **over}, follow=True)

    def test_get_and_results_with_stats_and_csv(self):
        self.assertContains(self.client.get(self.url), "آزمایشگاه ژئوکدر")
        r = self.run_lab()
        self.assertContains(r, "نرخ تطبیق")
        self.assertContains(r, "دانلود CSV")
        token = r.context["token"]
        csv_resp = self.client.get(self.url + f"?dl={token}")
        body = csv_resp.content.decode("utf-8-sig")
        self.assertEqual(csv_resp["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("خیابان ولیعصر", body)
        self.assertNotIn(",=cmd", body.replace("'=cmd", ""))  # فرمول خنثی شد
        self.assertIn("'=cmd", body)

    def test_validation_errors(self):
        for over in ({"ws": "x"}, {"city": ""}, {"text": ""}, {"text": "\n".join(["الف"] * 301)}, {"radius": "abc"}):
            r = self.run_lab(**over)
            self.assertNotContains(r, "نرخ تطبیق")

    def test_missing_workspace_and_geocode_error(self):
        with mock.patch("kernel.workspace.peek", return_value=None):
            r = self.client.post(self.url, {"ws": "3", "city": "تهران", "text": "الف"}, follow=True)
        self.assertContains(r, "پیدا نشد")
        with mock.patch("kernel.workspace.peek", return_value=SimpleNamespace(pk=3, is_live=True)), \
                mock.patch("kernel.geocode.load", side_effect=geocode.GeocodeError("شهر «x» در osm_places پیدا نشد.")):
            r = self.client.post(self.url, {"ws": "3", "city": "x", "text": "الف"}, follow=True)
        self.assertContains(r, "osm_places پیدا نشد")

    def test_non_superuser_denied_and_download_is_per_user(self):
        r = self.run_lab()
        token = r.context["token"]
        staff = get_user_model().objects.create_user(username="st", phone="09120000401", password="x", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(self.url + f"?dl={token}").status_code, 403)
        self.client.force_login(self.admin)
        other = get_user_model().objects.create_superuser(username="adm2", phone="09120000402", password="x")
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url + f"?dl={token}", follow=True).status_code, 200)
        self.assertNotIn("text/csv", self.client.get(self.url + f"?dl={token}")["Content-Type"] if self.client.get(self.url + f"?dl={token}").status_code == 200 else "")
