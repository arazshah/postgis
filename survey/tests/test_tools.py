import json
import math

from django.test import SimpleTestCase

from survey import cogo, dxf, exports, importers, sync


class CogoTests(SimpleTestCase):
    def test_inverse_and_forward(self):
        r = cogo.inverse((0, 0), (3, 4))
        self.assertAlmostEqual(r["distance"], 5)
        self.assertAlmostEqual(r["azimuth"], math.degrees(math.atan2(3, 4)))
        self.assertAlmostEqual(cogo.inverse((0, 0), (0, -1))["azimuth"], 180)
        self.assertAlmostEqual(cogo.inverse((0, 0), (-1, 0))["azimuth"], 270)
        x, y = cogo.forward((10, 10), 90, 5)
        self.assertAlmostEqual(x, 15)
        self.assertAlmostEqual(y, 10)

    def test_area_perimeter(self):
        r = cogo.area_perimeter([(0, 0), (100, 0), (100, 50), (0, 50)])
        self.assertAlmostEqual(r["area"], 5000)
        self.assertAlmostEqual(r["perimeter"], 300)
        self.assertEqual(r["clockwise"], False)
        self.assertAlmostEqual(cogo.area_perimeter([(0, 0), (0, 50), (100, 50), (100, 0), (0, 0)])["area"], 5000)
        with self.assertRaises(ValueError):
            cogo.area_perimeter([(0, 0), (1, 1)])

    def test_intersections(self):
        p = cogo.intersect_bearings((0, 0), 45, (10, 0), 315)
        self.assertAlmostEqual(p[0], 5)
        self.assertAlmostEqual(p[1], 5)
        self.assertIsNone(cogo.intersect_bearings((0, 0), 0, (5, 0), 0))
        pts = cogo.intersect_distances((0, 0), 5, (6, 0), 5)
        self.assertEqual(sorted(round(y, 6) for _, y in pts), [-4.0, 4.0])
        self.assertEqual(cogo.intersect_distances((0, 0), 1, (10, 0), 1), [])

    def test_traverse_closure(self):
        legs = [(0, 100), (90, 100), (90, 100), (90, 100)]
        r = cogo.traverse((0, 0), 0, legs, closing_to=(0, 0))
        self.assertAlmostEqual(r["misclosure"], 0, places=6)
        self.assertEqual(r["precision"] > 1e6, True)
        r = cogo.traverse((0, 0), 0, [(0, 100), (90, 100), (90, 100), (90, 99)], closing_to=(0, 0))
        self.assertAlmostEqual(r["misclosure"], 1, places=6)
        self.assertAlmostEqual(r["precision"], 399, places=3)

    def test_stakeout(self):
        s = cogo.stakeout((100, 100), (103, 104))
        self.assertAlmostEqual(s["distance"], 5)
        self.assertEqual((s["dx"], s["dy"]), (3, 4))


class DxfTests(SimpleTestCase):
    def test_structure(self):
        d = dxf.Dxf()
        d.point(500000.5, 3950000.25, 1200, "GR", "P1")
        d.polyline([(0, 0), (10, 0), (10, 10)], "BL", closed=True)
        out = d.dumps()
        self.assertTrue(out.rstrip().endswith("EOF"))
        for token in ("SECTION", "ENTITIES", "POINT", "TEXT", "POLYLINE", "VERTEX", "SEQEND", "ENDSEC", "500000.5000"):
            self.assertIn(token, out)
        lines = out.split("\n")
        self.assertEqual(lines[0].strip(), "0")
        self.assertEqual(out.count("\nVERTEX\n"), 3)
        self.assertIn("\nGR\n", out)

    def test_layer_names_are_sanitised(self):
        self.assertEqual(dxf.layer_name('a<b>:c/d"'), "a_b__c_d_")
        self.assertEqual(dxf.layer_name(""), "0")
        self.assertEqual(len(dxf.layer_name("x" * 100)), 31)


class ImportTests(SimpleTestCase):
    def test_headerless_pen(self):
        raw = b"1,500000.5,3950000.25,1200.1,GR\n2,500010,3950010,1201,BL\n"
        items, errors = importers.parse_points(raw, "pen", "project", 32639)
        self.assertEqual(errors, [])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["geometry"]["coordinates"], [500000.5, 3950000.25])
        self.assertEqual(items[0]["srid"], 32639)
        self.assertEqual(items[0]["properties"]["h_ortho"], 1200.1)
        self.assertEqual(items[0]["properties"]["code"], "GR")

    def test_pne_swaps_axes(self):
        items, _ = importers.parse_points(b"A 3950000 500000 10 X", "pne", "project", 32639)
        self.assertEqual(items[0]["geometry"]["coordinates"], [500000.0, 3950000.0])

    def test_header_aliases_and_semicolon(self):
        raw = b"name;northing;easting;elev\nP1;3950000;500000;12\n"
        items, errors = importers.parse_points(raw, "pen", "project", 32639)
        self.assertEqual((len(items), errors), (1, []))
        self.assertEqual(items[0]["geometry"]["coordinates"], [500000.0, 3950000.0])
        self.assertEqual(items[0]["properties"]["pt_no"], "P1")

    def test_latlon_and_bad_rows(self):
        raw = b"51.4,35.7\nabc,35\n300,35\n"
        items, errors = importers.parse_points(raw, "en", "4326", 32639)
        self.assertEqual(len(items), 1)
        self.assertEqual(len(errors), 2)
        self.assertEqual(items[0]["srid"], 4326)

    def test_geojson(self):
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [51, 35]}, "properties": {"pt_no": "a"}},
            {"type": "Feature", "geometry": {"type": "MultiPoint", "coordinates": []}, "properties": {}}]}
        items, errors = importers.parse_geojson(json.dumps(fc).encode())
        self.assertEqual((len(items), len(errors)), (1, 1))
        with self.assertRaises(importers.ImportError_):
            importers.parse_geojson(b"{not json")

    def test_too_big_and_empty(self):
        with self.assertRaises(importers.ImportError_):
            importers.parse_points(b"x" * (importers.MAX_BYTES + 1), "pen", "project", 32639)
        with self.assertRaises(importers.ImportError_):
            importers.parse_points(b"\n\n", "pen", "project", 32639)
        with self.assertRaises(importers.ImportError_):
            importers.parse_points(b"1,2,3", "zzz", "project", 32639)


class SyncValidationTests(SimpleTestCase):
    def test_clean_properties_whitelists_and_ranges(self):
        p = sync.clean_properties("point", {"pt_no": 5, "fix_quality": 4, "hdop": 0.7, "evil": "x", "geom": "x",
                                            "qc_flags": ["lowsats"], "id": 9})
        self.assertEqual(p, {"pt_no": "5", "fix_quality": 4, "hdop": 0.7, "qc_flags": ["lowsats"]})
        for bad in ({"fix_quality": 12}, {"hdop": -1}, {"hdop": float("inf")}, {"hdop": True}, {"session_id": "x"},
                    {"captured_at": "yesterday"}, {"qc_flags": "x"}):
            with self.assertRaises(sync.ItemError, msg=bad):
                sync.clean_properties("point", bad)
        # ستون‌های نقطه روی خط مجاز نیست
        self.assertEqual(sync.clean_properties("line", {"hdop": 1, "code": "RD"}), {"code": "RD"})

    def test_geometry_check(self):
        sync.check_geometry("point", {"type": "Point", "coordinates": [1, 2]})
        for kind, g in (("point", {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}),
                        ("point", {"type": "Point", "coordinates": []}),
                        ("point", {"type": "Point", "coordinates": [float("nan"), 1]}),
                        ("line", None), ("polygon", {"type": "Polygon", "coordinates": "x"})):
            with self.assertRaises(sync.ItemError):
                sync.check_geometry(kind, g)


class ExportTests(SimpleTestCase):
    def test_csv_has_bom_and_header(self):
        class P:
            srid = 32639
        fc = {"features": [{"properties": {"id": 1, "pt_no": "A", "x": 500000.123456, "y": 3950000.0, "code": "GR"}}]}
        out = exports.points_csv(fc, P())
        self.assertTrue(out.startswith("﻿pt_no,easting,northing"))
        self.assertIn("A,500000.1235,3950000.0", out)

    def test_report_escapes_html(self):
        class P:
            srid = 32639
            name = "<script>x</script>"
        cols = {"points": {"features": [{"properties": {"id": 1, "pt_no": "<b>", "x": 1.0, "y": 2.0}}]}}
        html = exports.report_html(cols, P(), "db")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>", html)
