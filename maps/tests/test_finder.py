"""پیدا کردن لایه در نقشه چندلایه: نقطه‌ای شدن عارضه ریز در زوم دور (بدون نیاز به PostGIS)."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from publish import engine, styles


class FarDotsStyleTests(SimpleTestCase):
    def test_style_flag_defaults_on_and_survives_off(self):
        self.assertIs(styles.clean({}, set())["far_dots"], True)
        self.assertIs(styles.clean({"far_dots": False}, set())["far_dots"], False)
        self.assertIs(styles.clean({"far_dots": "no"}, set())["far_dots"], True)  # فقط False واقعی خاموش می‌کند

    def test_far_dots_rules(self):
        poly = SimpleNamespace(geom_type="POLYGON", style={})
        self.assertTrue(engine._far_dots(poly, 6))
        self.assertFalse(engine._far_dots(poly, engine.FAR_DOT_MAX_ZOOM + 1))
        self.assertFalse(engine._far_dots(SimpleNamespace(geom_type="POINT", style={}), 6))
        self.assertFalse(engine._far_dots(SimpleNamespace(geom_type="MULTIPOINT", style={}), 6))
        self.assertFalse(engine._far_dots(SimpleNamespace(geom_type="POLYGON", style={"far_dots": False}), 6))
        self.assertTrue(engine._far_dots(SimpleNamespace(geom_type="", style=None), 6))  # نوع نامشخص: امن است


class TileQueryTests(SimpleTestCase):
    def _sql(self, layer, z):
        seen = []

        class Conn:
            def execute(self, query):
                seen.append(query)
                return SimpleNamespace(fetchone=lambda: (b"",))

        @contextmanager
        def fake(_layer):
            yield Conn()

        with mock.patch.object(engine, "_connect", fake), mock.patch.object(
                engine, "table_meta", return_value={"columns": [("name", "text")], "pk": ""}):
            engine.tile(layer, z, 0, 0)
        return seen[-1].as_string(None)

    def _layer(self, **kw):
        base = dict(schema="public", table="parks", geom_column="geom", srid=4326, geom_type="POLYGON", style={},
                    columns=[], collection_id="parks")
        return SimpleNamespace(**{**base, **kw})

    def test_tiny_features_become_points_at_far_zoom(self):
        sql = self._sql(self._layer(), 6)
        self.assertIn("ST_PointOnSurface(__g)", sql)
        self.assertIn("LATERAL", sql)

    def test_near_zoom_and_points_untouched(self):
        self.assertNotIn("ST_PointOnSurface", self._sql(self._layer(), 15))
        self.assertNotIn("ST_PointOnSurface", self._sql(self._layer(geom_type="POINT"), 6))
        self.assertNotIn("ST_PointOnSurface", self._sql(self._layer(style={"far_dots": False}), 6))

    def test_threshold_shrinks_with_zoom(self):
        import re

        def thr(z):
            return float(re.search(r"< ([0-9.e+-]+) AND", self._sql(self._layer(), z)).group(1))

        self.assertAlmostEqual(thr(6) / thr(7), 2, places=3)
