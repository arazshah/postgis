"""کتابخانه‌ی مکانی handler سطح ۲ (`import geo`): مقدارهای مرجع شناخته‌شده + اجرا در جعبه."""
import json
import math

from django.test import SimpleTestCase

from kernel.runner import geo, sandbox, scan


class DistanceTests(SimpleTestCase):
    def test_haversine_known_distances(self):
        self.assertAlmostEqual(geo.haversine_km(35.6892, 51.3890, 32.6546, 51.6680), 337.5, delta=3)  # تهران—اصفهان
        self.assertAlmostEqual(geo.haversine_km(0, 0, 0, 1), 111.195, delta=0.01)  # یک درجه‌ی استوا
        self.assertEqual(geo.haversine_km(10, 10, 10, 10), 0)
        self.assertAlmostEqual(geo.haversine_km(0, 0, 0, 180), math.pi * geo.R_KM, delta=0.001)

    def test_bearing_and_destination_roundtrip(self):
        self.assertAlmostEqual(geo.bearing_deg(0, 0, 1, 0), 0, places=6)
        self.assertAlmostEqual(geo.bearing_deg(0, 0, 0, 1), 90, places=6)
        self.assertAlmostEqual(geo.bearing_deg(0, 0, -1, 0), 180, places=6)
        lat, lon = geo.destination(35.7, 51.4, 45, 100)
        self.assertAlmostEqual(geo.haversine_km(35.7, 51.4, lat, lon), 100, delta=0.001)
        self.assertAlmostEqual(geo.bearing_deg(35.7, 51.4, lat, lon), 45, delta=0.05)

    def test_invalid_coordinates(self):
        for args in ((91, 0, 0, 0), (0, 181, 0, 0), (0, 0, -95, 0)):
            with self.assertRaises(ValueError):
                geo.haversine_km(*args)

    def test_path_length(self):
        self.assertAlmostEqual(geo.path_length_km([(0, 0), (0, 1), (0, 2)]), 2 * 111.195, delta=0.02)
        self.assertEqual(geo.path_length_km([(1, 1)]), 0)


class ShapeTests(SimpleTestCase):
    SQUARE = [(0, 0), (0, 1), (1, 1), (1, 0)]

    def test_bbox_centroid(self):
        self.assertEqual(geo.bbox(self.SQUARE), (0, 0, 1, 1))
        self.assertEqual(geo.centroid(self.SQUARE), (0.5, 0.5))
        with self.assertRaises(ValueError):
            geo.bbox([])

    def test_point_in_polygon(self):
        self.assertTrue(geo.point_in_polygon(0.5, 0.5, self.SQUARE))
        self.assertFalse(geo.point_in_polygon(1.5, 0.5, self.SQUARE))
        self.assertFalse(geo.point_in_polygon(0.5, -0.1, self.SQUARE))

    def test_polygon_area_one_degree_square_at_equator(self):
        self.assertAlmostEqual(geo.polygon_area_km2(self.SQUARE), 12364, delta=40)  # ≈ ۱۱۱٫۲ × ۱۱۱٫۲
        self.assertEqual(geo.polygon_area_km2([(0, 0), (1, 1)]), 0.0)


class ProjectionTests(SimpleTestCase):
    def test_utm_reference_points(self):
        e = geo.wgs84_to_utm(0, 3)  # نصف‌النهار مرکزی منطقه‌ی ۳۱ در استوا
        self.assertEqual((e["zone"], e["hemisphere"]), (31, "N"))
        self.assertAlmostEqual(e["easting"], 500000, delta=0.01)
        self.assertAlmostEqual(e["northing"], 0, delta=0.01)
        m = geo.wgs84_to_utm(45, 9)  # مقدار مرجع شناخته‌شده: N ≈ 4982950.4
        self.assertAlmostEqual(m["easting"], 500000, delta=0.01)
        self.assertAlmostEqual(m["northing"], 4982950.4, delta=0.5)
        s = geo.wgs84_to_utm(-33.8688, 151.2093)  # سیدنی، منطقه‌ی ۵۶ جنوبی
        self.assertEqual((s["zone"], s["hemisphere"]), (56, "S"))
        self.assertAlmostEqual(s["easting"], 334369, delta=2)
        self.assertAlmostEqual(s["northing"], 6250948, delta=2)
        k = geo.wgs84_to_utm(27.9881, 86.9250)  # اورست: ۴۵R، مقدار مرجع منتشرشده
        self.assertEqual(k["zone"], 45)
        self.assertAlmostEqual(k["easting"], 492625, delta=2)
        self.assertAlmostEqual(k["northing"], 3095886, delta=2)

    def test_utm_zone_for_iran(self):
        self.assertEqual([geo.utm_zone(x) for x in (45, 51.4, 57.5)], [38, 39, 40])
        t = geo.wgs84_to_utm(35.6892, 51.389)
        self.assertEqual(t["zone"], 39)
        self.assertTrue(300000 < t["easting"] < 700000 and 3.9e6 < t["northing"] < 4.0e6)

    def test_web_mercator(self):
        x0, y0 = geo.web_mercator(0, 0)
        self.assertAlmostEqual(x0, 0)
        self.assertAlmostEqual(y0, 0, places=6)
        x, y = geo.web_mercator(0, 180)
        self.assertAlmostEqual(x, 20037508.34, delta=0.01)
        with self.assertRaises(ValueError):
            geo.web_mercator(89, 0)


class FormatTests(SimpleTestCase):
    GJ = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [51.4, 35.7]}, "properties": {"name": "a"}},
        {"type": "Feature", "geometry": {"type": "MultiPoint", "coordinates": [[52, 36], [53, 37]]}, "properties": {"name": "b"}},
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "properties": {}}]})

    def test_parse_and_points(self):
        self.assertEqual([f["type"] for f in geo.parse_geojson(self.GJ)], ["Point", "MultiPoint", "LineString"])
        pts = geo.point_features(self.GJ)
        self.assertEqual([(p["lat"], p["lon"]) for p in pts], [(35.7, 51.4), (36.0, 52.0), (37.0, 53.0)])
        self.assertEqual(pts[0]["properties"], {"name": "a"})

    def test_bad_geojson(self):
        for bad in ("not json", "[]", '{"type": "Nope"}', json.dumps({"type": "Point", "coordinates": [200, 0]})):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                geo.point_features(bad)
        with self.assertRaises(ValueError):
            geo.parse_geojson(self.GJ, limit=1)

    def test_roundtrip_and_wkt(self):
        text = geo.to_geojson_points([{"lat": 35.7, "lon": 51.4, "name": "x"}])
        self.assertEqual(geo.point_features(text)[0]["properties"], {"name": "x"})
        self.assertEqual(geo.parse_wkt_point("POINT(51.4 35.7)"), (35.7, 51.4))
        for bad in ("LINESTRING(0 0, 1 1)", "POINT()", "POINT(1)", "POINT(500 0)"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                geo.parse_wkt_point(bad)


class SpectralTests(SimpleTestCase):
    def test_indices(self):
        self.assertAlmostEqual(geo.ndvi(0.5, 0.1), 0.6667, places=4)
        self.assertEqual(geo.ndvi(0.2, 0.2), 0)
        self.assertAlmostEqual(geo.ndwi(0.3, 0.1), 0.5, places=6)
        self.assertAlmostEqual(geo.savi(0.5, 0.1), (0.4 * 1.5) / (0.5 + 0.1 + 0.5), places=6)
        self.assertGreater(geo.evi(0.5, 0.1, 0.05), 0.3)
        with self.assertRaises(ValueError):
            geo.ndvi(0, 0)

    def test_classify(self):
        labels = ["آب", "خاک", "کم‌پشت", "پرپشت"]
        breaks = [0.0, 0.2, 0.5]
        self.assertEqual([geo.classify(v, breaks, labels) for v in (-0.3, 0.0, 0.1, 0.2, 0.49, 0.9)],
                         ["آب", "خاک", "خاک", "کم‌پشت", "کم‌پشت", "پرپشت"])
        for bad in (([0.5, 0.1], ["a", "b", "c"]), ([0.1], ["a"])):
            with self.assertRaises(ValueError):
                geo.classify(0, *bad)

    def test_stats_percentile(self):
        s = geo.stats([1, 2, 3, 4, None])
        self.assertEqual((s["count"], s["min"], s["max"], s["mean"], s["median"]), (4, 1, 4, 2.5, 2.5))
        self.assertAlmostEqual(s["stdev"], math.sqrt(1.25))
        self.assertEqual(geo.stats([])["count"], 0)
        self.assertEqual(geo.percentile([1, 2, 3, 4, 5], 50), 3)
        self.assertEqual(geo.percentile([1, 2, 3, 4, 5], 100), 5)
        self.assertAlmostEqual(geo.percentile([10, 20], 25), 12.5)
        with self.assertRaises(ValueError):
            geo.percentile([], 50)


class ClimateTests(SimpleTestCase):
    def test_extraterrestrial_radiation_fao56_example(self):
        self.assertAlmostEqual(geo.extraterrestrial_radiation(-20, geo.day_of_year(2020, 9, 3) - 1), 32.2, delta=0.15)  # J=246
        self.assertAlmostEqual(geo.extraterrestrial_radiation(-20, 246), 32.2, delta=0.15)

    def test_hargreaves_reasonable_and_monotonic(self):
        summer = geo.et0_hargreaves(20, 38, 35.7, 200)
        winter = geo.et0_hargreaves(0, 10, 35.7, 15)
        self.assertTrue(5 < summer < 12, summer)
        self.assertTrue(0 < winter < 2, winter)
        self.assertGreater(geo.et0_hargreaves(15, 38, 35.7, 200), geo.et0_hargreaves(25, 38, 35.7, 200))  # دامنه‌ی بزرگ‌تر ← بیشتر
        with self.assertRaises(ValueError):
            geo.et0_hargreaves(30, 20, 35, 100)

    def test_gdd_and_day_of_year(self):
        self.assertEqual(geo.gdd(5, 9), 0)
        self.assertAlmostEqual(geo.gdd(10, 30), 10.0)
        self.assertAlmostEqual(geo.gdd(10, 40), 10.0)  # سقف ۳۰
        self.assertEqual((geo.day_of_year(2023, 1, 1), geo.day_of_year(2023, 12, 31), geo.day_of_year(2024, 12, 31)), (1, 365, 366))
        self.assertEqual(geo.day_of_year(2024, 3, 1), 61)


class SandboxTests(SimpleTestCase):
    SRC = ("import geo\n\ndef handle(ctx, p):\n    rows = ctx.sql('select lat, lon, nir, red from pixels')['rows']\n"
           "    out = []\n    for lat, lon, nir, red in rows:\n        v = geo.ndvi(nir, red)\n"
           "        out.append([round(geo.haversine_km(35.7, 51.4, lat, lon), 1), round(v, 3), geo.classify(v, [0.2, 0.5], ['کم', 'متوسط', 'زیاد'])])\n"
           "    return {'columns': ['فاصله', 'ndvi', 'طبقه'], 'rows': out}\n")

    def test_geo_is_importable_in_the_sandbox(self):
        self.assertEqual(scan.scan(self.SRC), [])
        sql = lambda q, a: {"columns": [], "rows": [[35.7, 51.4, 0.5, 0.1], [36.7, 51.4, 0.3, 0.25]]}  # noqa: E731
        out = sandbox.run({"code/h.py": self.SRC}, "h", {}, sql=sql)
        self.assertEqual(out["rows"][0], [0.0, 0.667, "زیاد"])
        self.assertEqual(out["rows"][1][2], "کم")

    def test_geo_internals_stay_blocked(self):
        for src in ("import geo\nx = geo.__dict__\n", "import geo\nx = geo.__builtins__\n", "import geo.os\n", "from geo import __doc__\n"):
            with self.subTest(src=src):
                self.assertTrue(scan.scan(src), src)

    def test_geo_has_no_dangerous_imports(self):
        import ast
        import inspect

        mods = {n.names[0].name for n in ast.walk(ast.parse(inspect.getsource(geo))) if isinstance(n, ast.Import)}
        self.assertEqual(mods, {"json", "math", "statistics"})
