"""کاتالوگ منبع‌ها: هر منبع مدخل کامل دارد و هدف‌ها فقط به منبع موجود اشاره می‌کنند."""
from django.test import SimpleTestCase

from satellite import catalog
from satgate import spec


class CatalogTests(SimpleTestCase):
    def test_every_mission_has_complete_entry(self):
        self.assertEqual(set(catalog.CATALOG), set(spec.MISSIONS))
        for key, c in catalog.CATALOG.items():
            with self.subTest(key):
                self.assertTrue(c["tag"] and c["one"])
                self.assertGreaterEqual(len(c["uses"]), 1)
                self.assertGreaterEqual(len(c["avoid"]), 1)
                self.assertTrue(c["bands"] or c.get("derived"), "نوار طیف یا توضیح لایه‌ی محاسبه‌شده لازم است")
                for ico, text in c["uses"]:
                    self.assertTrue(ico and text)
                for other, why in c.get("compare", ()):
                    self.assertIn(other, spec.MISSIONS)
                    self.assertNotEqual(other, key)
                    self.assertTrue(why)

    def test_goals_point_at_real_missions(self):
        for g, d in catalog.GOALS.items():
            with self.subTest(g):
                self.assertTrue(d["pick"])
                self.assertEqual(len(set(d["pick"])), len(d["pick"]))
                self.assertLessEqual(set(d["pick"]), set(spec.MISSIONS))

    def test_bands_are_known(self):
        known = {k for k, _ in catalog.BANDS}
        for key, c in catalog.CATALOG.items():
            self.assertLessEqual(set(c["bands"]), known, key)

    def test_public_is_json_friendly(self):
        import json
        json.dumps(catalog.public())
