"""برداشت نتیجهٔ پرسش فارسی: آخرین مرحلهٔ مکانی، پاسخ متنی و راهنمای مدل (بدون نیاز به پایگاه داده)."""
from types import SimpleNamespace as NS

from django.test import SimpleTestCase

from analysis import ask


def _spec(*outputs):
    return NS(operations=[NS(op=f"op{i}", output=o) for i, o in enumerate(outputs)])


def _line(name, length):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[51, 35], [51.1, 35.1]]},
            "properties": {"name": name, "length_m": length}}


SUMMARY = {"type": "vector_summary", "status": "succeeded", "feature_count": 1,
           "geometry_counts": {"LineString": 1}, "property_keys": ["name", "length_m"], "bbox": [0, 0, 1, 1],
           "created_at": "2026-10-24T00:00:00Z"}


class SpatialOutputTests(SimpleTestCase):
    def test_summary_as_last_step_does_not_hide_the_layer(self):
        # همان حالت واقعی «طولانی‌ترین رود»: filter_attribute لایه می‌دهد و summarize_vector آخر است
        result = NS(outputs={"stats": {"count": 3}, "longest": {"type": "FeatureCollection",
                                                                "features": [_line("کرج", 180000.0)]},
                             "summary": SUMMARY})
        step, feats = ask._spatial_output(result, _spec("stats", "longest", "summary"))
        self.assertEqual(step, "longest")
        self.assertEqual(feats[0]["properties"]["name"], "کرج")

    def test_last_spatial_step_wins(self):
        a = {"features": [_line("a", 1)]}
        b = {"features": [_line("b", 2)]}
        step, feats = ask._spatial_output(NS(outputs={"a": a, "b": b}), _spec("a", "b"))
        self.assertEqual((step, feats[0]["properties"]["name"]), ("b", "b"))

    def test_features_without_geometry_are_not_spatial(self):
        out = {"features": [{"type": "Feature", "geometry": None, "properties": {"x": 1}}]}
        self.assertEqual(ask._spatial_output(NS(outputs={"t": out}), _spec("t")), (None, []))

    def test_map_layers_output(self):
        out = NS(map_layers=[{"features": [_line("m", 5)]}])
        step, feats = ask._spatial_output(NS(outputs={"m": out}), _spec("m"))
        self.assertEqual(step, "m")
        self.assertEqual(len(feats), 1)


class AnswerTextTests(SimpleTestCase):
    def test_vector_summary_is_readable_not_raw_dict(self):
        text = ask._answer_text(NS(outputs={"s": SUMMARY}), _spec("s"))
        self.assertIn("تعداد عارضه: 1", text)
        self.assertIn("LineString", text)
        self.assertNotIn("vector_summary", text)
        self.assertNotIn("{", text)

    def test_stats_dict(self):
        out = {"type": "attribute_statistics", "count": 12, "sum": 1234.5678, "fields": {"length": {"max": 99.5}}}
        text = ask._answer_text(NS(outputs={"s": out}), _spec("s"))
        self.assertIn("count: 12", text)
        self.assertIn("sum: 1,234.57", text)
        self.assertIn("max: 99.5", text)

    def test_plain_string_and_number(self):
        self.assertEqual(ask._answer_text(NS(outputs={"t": "حدود ۱۲ کیلومتر"}), _spec("t")), "حدود ۱۲ کیلومتر")
        self.assertEqual(ask._answer_text(NS(outputs={"n": 42}), _spec("n")), "42")

    def test_falls_back_to_earlier_step_and_empty(self):
        self.assertEqual(ask._answer_text(NS(outputs={"a": "x", "b": {}}), _spec("a", "b")), "x")
        self.assertEqual(ask._answer_text(NS(outputs={}), _spec("a")), "")

    def test_length_is_capped(self):
        self.assertLessEqual(len(ask._answer_text(NS(outputs={"t": "ی" * 5000}), _spec("t"))), ask.MAX_ANSWER_CHARS)


class HintsTests(SimpleTestCase):
    OLD = {k: None for k in ("crs_transform", "area_perimeter", "top_n", "summarize_vector", "filter_attribute")}
    NEW = {**OLD, "dissolve": None, "calculate_field": None}

    def test_new_catalog_gets_full_pattern(self):
        h = ask._hints(self.NEW)
        for word in ("dissolve", "area_perimeter", "top_n", "_length", "summarize_vector", "calculate_field"):
            self.assertIn(word, h)

    def test_old_catalog_never_mentions_missing_ops(self):
        # s3geo پیش از ۰٫۶٫۰ عملیات dissolve و calculate_field را ندارد؛ نباید پیشنهاد شوند
        h = ask._hints(self.OLD)
        self.assertNotIn("dissolve", h)
        self.assertNotIn("calculate_field", h)
        self.assertIn("top_n", h)

    def test_tiny_catalog_has_only_base_hint(self):
        h = ask._hints({"buffer": None})
        self.assertNotIn("top_n", h)
        self.assertIn("summarize_vector", h)

    def test_every_mentioned_op_exists_in_installed_catalog(self):
        try:
            from orchestrator.planning.op_catalog import OP_CATALOG
        except ImportError:
            self.skipTest("s3geo نصب نیست")
        import re
        for op in set(re.findall(r"\b(dissolve|crs_transform|area_perimeter|top_n|calculate_field|summarize_vector|"
                                 r"attribute_statistics)\b", ask._hints())):
            self.assertIn(op, OP_CATALOG)
