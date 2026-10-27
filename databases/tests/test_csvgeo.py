"""تشخیص ستون‌های مکانی CSV با نام‌های گوناگون، رقم فارسی، جابه‌جایی طول و عرض و آماده‌سازی برای GDAL."""
import shutil
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from databases import csvgeo, gdal

HAS_GDAL = bool(shutil.which("ogrinfo"))


def _csv(folder: Path, text: str, name="data.csv", encoding="utf-8") -> Path:
    p = folder / name
    p.write_bytes(text.encode(encoding))
    return p


class ParseTests(SimpleTestCase):
    def test_numbers(self):
        self.assertEqual(csvgeo.parse_number("51.4"), 51.4)
        self.assertEqual(csvgeo.parse_number("۵۱٫۴"), 51.4)
        self.assertEqual(csvgeo.parse_number("٥١.٤"), 51.4)
        self.assertEqual(csvgeo.parse_number("51,4"), 51.4)
        self.assertEqual(csvgeo.parse_number("−12.5"), -12.5)
        self.assertIsNone(csvgeo.parse_number(""))
        self.assertIsNone(csvgeo.parse_number("تهران"))
        self.assertIsNone(csvgeo.parse_number("nan"))

    def test_dms(self):
        self.assertAlmostEqual(csvgeo.parse_number("35°41'22\"N"), 35.689444, places=5)
        self.assertAlmostEqual(csvgeo.parse_number("51°23'E"), 51.383333, places=5)
        self.assertAlmostEqual(csvgeo.parse_number("33°52'S"), -33.866667, places=5)

    def test_pair_and_wkt(self):
        self.assertEqual(csvgeo.parse_pair("35.7, 51.4"), (35.7, 51.4))
        self.assertEqual(csvgeo.parse_pair("(35.7 ; 51.4)"), (35.7, 51.4))
        self.assertEqual(csvgeo.parse_pair("۳۵٫۷، ۵۱٫۴"), (35.7, 51.4))
        self.assertIsNone(csvgeo.parse_pair("51.4"))
        self.assertEqual(csvgeo.parse_wkt("SRID=32639;POINT(535000 3950000)"), ("POINT(535000 3950000)", 32639))
        self.assertEqual(csvgeo.parse_wkt("point (1 2)"), ("point (1 2)", None))
        self.assertIsNone(csvgeo.parse_wkt("نقطه"))

    def test_names(self):
        self.assertEqual(csvgeo.norm_name(" طول‌جغرافيايي "), "طولجغرافیایی")
        self.assertEqual(csvgeo._name_score("longitude", csvgeo.X_EXACT, csvgeo.X_PART), 3)
        self.assertEqual(csvgeo._name_score("gpslongdeg", csvgeo.X_EXACT, csvgeo.X_PART, "GPS_Long_deg"), 2)
        self.assertEqual(csvgeo._name_score("colony", csvgeo.X_EXACT, csvgeo.X_PART), 0)
        self.assertEqual(csvgeo._name_score("plate", csvgeo.Y_EXACT, csvgeo.Y_PART), 0)


class AnalyzeTests(SimpleTestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)

    def spec(self, text, **kw):
        return csvgeo.analyze(_csv(self.d, text, **kw))["spec"]

    def test_name_variants(self):
        for xh, yh in (("Longitude", "Latitude"), ("X_Coord", "Y_Coord"), ("طول جغرافیایی", "عرض جغرافیایی"),
                       ("Long_DD", "Lat_DD"), ("POINT_X", "POINT_Y"), ("gps_long", "gps_lat")):
            s = self.spec(f"name,{xh},{yh}\nA,51.41,35.69\nB,51.42,35.70\n")
            self.assertEqual((s["mode"], s["x"], s["y"], s["srid"]), ("xy", xh, yh, 4326), xh)

    def test_unknown_names_detected_from_values(self):
        s = self.spec("کد,ستون۱,ستون۲,جمعیت\n1,35.6892,51.3890,1200\n2,35.7012,51.4012,900\n")
        self.assertEqual((s["mode"], s["x"], s["y"], s["how"]), ("xy", "ستون۲", "ستون۱", "content"))

    def test_swapped_names(self):
        s = self.spec("x,y\n35.69,51.41\n35.70,51.42\n")  # کاربر عرض را در x نوشته
        self.assertEqual((s["x"], s["y"], s["swapped"]), ("y", "x", True))

    def test_persian_digits_semicolon(self):
        s = self.spec("نام;طول;عرض\nالف;۵۱٫۴۱;۳۵٫۶۹\nب;۵۱٫۴۲;۳۵٫۷۰\n")
        self.assertEqual((s["mode"], s["x"], s["y"]), ("xy", "طول", "عرض"))

    def test_utm(self):
        s = self.spec("id,Easting,Northing\n1,535000.5,3950000.2\n2,535100.1,3950100.9\n")
        self.assertEqual((s["mode"], s["x"], s["y"], s["srid"], s["kind"]), ("xy", "Easting", "Northing", None, "utm"))

    def test_pair_column(self):
        s = self.spec('name,location\nA,"35.69, 51.41"\nB,"35.70, 51.42"\n')
        self.assertEqual((s["mode"], s["pair"], s["pair_order"], s["srid"]), ("pair", "location", "latlon", 4326))

    def test_wkt_column(self):
        s = self.spec('name,shape_wkt\nA,"SRID=4326;POINT(51.4 35.7)"\nB,"POINT(51.5 35.8)"\n')
        self.assertEqual((s["mode"], s["geom"], s["srid"]), ("wkt", "shape_wkt", 4326))

    def test_no_location(self):
        s = self.spec("name,age,score\nA,30,12\nB,40,15\n")
        self.assertEqual(s["mode"], "none")

    def test_ids_are_not_coordinates(self):
        s = self.spec("id,code,name\n1,23,a\n2,45,b\n3,60,c\n")
        self.assertEqual(s["mode"], "none")

    def test_cp1256_and_bom(self):
        a = csvgeo.analyze(_csv(self.d, "نام,طول,عرض\nتهران,51.4,35.7\n", encoding="cp1256"))
        self.assertEqual((a["encoding"], a["columns"]), ("CP1256", ["نام", "طول", "عرض"]))
        a = csvgeo.analyze(_csv(self.d, "﻿Lon,Lat\n51.4,35.7\n", name="b.csv"))
        self.assertEqual((a["encoding"], a["columns"], a["spec"]["x"]), ("UTF-8", ["Lon", "Lat"], "Lon"))

    def test_clean_spec(self):
        cols = ["a", "b"]
        self.assertEqual(csvgeo.clean_spec(cols, {"mode": "xy", "x": "a", "y": "a"})[1][0][:4], "ستون")
        spec, errors = csvgeo.clean_spec(cols, {"mode": "xy", "x": "a", "y": "b"})
        self.assertEqual((errors, spec["x"], spec["y"]), ([], "a", "b"))
        self.assertTrue(csvgeo.clean_spec(cols, {"mode": "wkt", "geom": "zzz"})[1])
        self.assertEqual(csvgeo.clean_spec(cols, {"mode": "hack"})[0]["mode"], "none")


class PrepareTests(SimpleTestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_prepare_xy_with_bad_rows(self):
        src = _csv(self.d, "نام;Long;Lat\nالف;۵۱٫۴۱;۳۵٫۶۹\nب;;\nج;51°25'E;35°42'N\n")
        a = csvgeo.analyze(src)
        dst = csvgeo.prepared_path(self.d, "شعبه‌ها.csv")
        stats = csvgeo.prepare(src, dst, a["encoding"], a["delimiter"], a["spec"])
        self.assertEqual((stats["rows"], stats["bad"]), (3, 1))
        lines = dst.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "نام,gp_x,gp_y")
        self.assertEqual(lines[1], "الف,51.41,35.69")
        self.assertEqual(lines[2], "ب,,")
        self.assertEqual(dst.parent.name, csvgeo.PREPARED_DIR)
        self.assertEqual(csvgeo.range_check(stats, 4326), ("", ""))
        self.assertEqual(csvgeo.range_check({**stats, "xmax": 535000}, 4326)[0], "error")

    def test_prepare_pair_lonlat(self):
        src = _csv(self.d, 'n,c\na,"51.4 35.7"\n')
        dst = self.d / csvgeo.PREPARED_DIR / "x.csv"
        stats = csvgeo.prepare(src, dst, "UTF-8", ",", {"mode": "pair", "pair": "c", "pair_order": "lonlat"})
        self.assertEqual(dst.read_text().splitlines()[1], "a,51.4,35.7")
        self.assertEqual(stats["points"], [[51.4, 35.7]])

    @unittest.skipUnless(HAS_GDAL, "ogrinfo not installed")
    def test_gdal_reads_prepared_file(self):
        """ستون‌هایی با نام ناشناخته برای GDAL، بعد از آماده‌سازی هندسه نقطه می‌شوند."""
        src = _csv(self.d, "شعبه,ستون۱,ستون۲,Lat_old\nالف,51.41,35.69,x\nب,51.42,35.70,y\n")
        a = csvgeo.analyze(src)
        self.assertEqual((a["spec"]["x"], a["spec"]["y"]), ("ستون۱", "ستون۲"))
        dst = csvgeo.prepared_path(self.d, "branches.csv")
        csvgeo.prepare(src, dst, a["encoding"], a["delimiter"], a["spec"])
        lyr = gdal.inspect(dst)["layers"][0]
        self.assertEqual((lyr["name"], lyr["count"], lyr["geom_type"]), ("branches", 2, "Point"))
        self.assertEqual(lyr["fields"], ["شعبه", "Lat_old"])  # gp_x و gp_y ستون نمی‌شوند
