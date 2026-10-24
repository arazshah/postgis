from django.test import SimpleTestCase

from survey import crs, ddl, presets


class CrsTests(SimpleTestCase):
    def test_utm_zones_for_iran(self):
        self.assertEqual(crs.utm_srid(51.4, 35.7), 32639)
        self.assertEqual(crs.utm_srid(45.0, 38.0), 32638)
        self.assertEqual(crs.utm_srid(57.0, 30.0), 32640)
        self.assertEqual(crs.utm_srid(61.0, 28.0), 32641)

    def test_zone_boundary(self):
        self.assertEqual(crs.utm_zone(48.0), 39)
        self.assertEqual(crs.utm_zone(47.999), 38)

    def test_southern_hemisphere_and_range(self):
        self.assertEqual(crs.utm_srid(51.4, -10), 32739)
        with self.assertRaises(crs.CrsError):
            crs.utm_zone(200)

    def test_presets_validate_without_connection(self):
        for srid in (32638, 32639, 32640, 32641, 4326):
            self.assertEqual(crs.validate_srid(srid), srid)
        self.assertEqual(crs.validate_srid("32639"), 32639)

    def test_unknown_srid_needs_connection(self):
        for bad in (99999, 0, -1, "abc", None):
            with self.assertRaises(crs.CrsError):
                crs.validate_srid(bad)


class DdlTests(SimpleTestCase):
    def test_slug_shape(self):
        for _ in range(20):
            self.assertRegex(ddl.new_slug(), r"^s_[a-z0-9]{8}$")

    def test_bad_slugs_are_rejected(self):
        for bad in ("S_AB12CD34", "s_ab12cd3", "s_ab12cd34;drop", "public", "", None, "s_ab12cd345"):
            with self.assertRaises(ValueError):
                ddl.check_slug(bad)
        self.assertEqual(ddl.check_slug("s_ab12cd34"), "s_ab12cd34")

    def test_templates_are_consistent(self):
        for key, (_title, rows) in presets.TEMPLATES.items():
            codes = [r[0] for r in rows]
            self.assertEqual(len(codes), len(set(codes)), key)
            for _code, _name, gtype, _layer in rows:
                self.assertIn(gtype, ("point", "line", "polygon"))
