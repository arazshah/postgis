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


def _pt(**props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [51.4, 35.7]}, "properties": props}


HOUSES = {"type": "FeatureCollection", "features": [_pt(id=i, deal=("اجاره" if i % 3 else "فروش"), title=f"خانه {i}")
                                                    for i in range(12)]}
EMPTY = NS(features=[], metadata={"output_feature_count": 0})


class EmptyResultTests(SimpleTestCase):
    def test_empty_last_vector_step_does_not_fall_back_to_intermediate_layer(self):
        # «خانه‌های ۵۰۰ متری مدرسه»: تبدیل مختصات همهٔ خانه‌ها را دارد ولی فیلتر فاصله خالی است؛ نباید همه ذخیره شوند
        result = NS(outputs={"h": NS(features=HOUSES["features"]), "near": EMPTY})
        self.assertEqual(ask._spatial_output(result, _spec("h", "near")), ("near", []))

    def test_why_empty_shows_condition_and_real_values(self):
        spec = NS(operations=[NS(op="filter_attribute", inputs={"vector": "houses"}, output="rent",
                                 params={"where": {"field": "deal", "op": "eq", "value": "rent"}})])
        text = "\n".join(ask._why_empty(NS(outputs={"rent": EMPTY}), spec, {"houses": HOUSES}))
        self.assertIn("«rent»", text)
        self.assertIn("«اجاره» (۸)", text)
        self.assertIn("«فروش» (۴)", text)

    def test_why_empty_missing_column_and_shortcut_where(self):
        spec = NS(operations=[NS(op="filter_attribute", inputs={"vector": "houses"}, output="rent",
                                 params={"where": {"usage": "rent"}})])
        text = "\n".join(ask._why_empty(NS(outputs={"rent": EMPTY}), spec, {"houses": HOUSES}))
        self.assertIn("ستون «usage» در داده نیست", text)
        self.assertIn("deal", text)

    def test_why_empty_point_on_line_suggests_distance(self):
        line = {"type": "FeatureCollection", "features": [_line("اصلی", 1)]}
        spec = NS(operations=[NS(op="spatial_join", inputs={"source": "houses", "target": "streets"}, output="j",
                                 params={"predicate": "intersects"})])
        text = "\n".join(ask._why_empty(NS(outputs={"j": EMPTY}), spec, {"houses": HOUSES, "streets": line}))
        self.assertIn("فاصله", text)

    def test_steps_show_counts_and_failed_step(self):
        spec = NS(operations=[NS(op="crs_transform", inputs={"vector": "houses"}, output="h", params={}),
                              NS(op="filter_attribute", inputs={"vector": "h"}, output="f", params={}),
                              NS(op="summarize_vector", inputs={"vector": "f"}, output="s", params={})])
        result = NS(success=False, outputs={"h": NS(features=HOUSES["features"])})
        steps = ask._steps(result, spec, {"houses": HOUSES, "unused": HOUSES})
        self.assertEqual([(s["op"], s["count"], s["status"]) for s in steps],
                         [("input", 12, "done"), ("crs_transform", 12, "done"), ("filter_attribute", None, "failed"),
                          ("summarize_vector", None, "skipped")])


class SpecPatchTests(SimpleTestCase):
    def test_max_distance_drops_unmatched(self):
        from dataclasses import dataclass, field

        @dataclass(frozen=True)
        class Op:
            op: str
            params: dict = field(default_factory=dict)

        @dataclass(frozen=True)
        class Spec:
            operations: list

        spec = ask._patch_spec(Spec([Op("spatial_nearest", {"k": 1, "max_distance": 500}),
                                     Op("spatial_nearest", {"k": 1}),
                                     Op("filter_by_distance", {"max_distance_m": 30, "drop_unmatched": False})]))
        self.assertTrue(spec.operations[0].params["drop_unmatched"])
        self.assertNotIn("drop_unmatched", spec.operations[1].params)
        self.assertFalse(spec.operations[2].params["drop_unmatched"])  # انتخاب صریح مدل دست نمی‌خورد


class ValueHintTests(SimpleTestCase):
    def test_categories_are_listed_but_unique_names_are_not(self):
        h = ask._value_hints({"houses": HOUSES})
        self.assertIn("houses.deal", h)
        self.assertIn("«اجاره»", h)
        self.assertNotIn("خانه 3", h)

    def test_no_text_columns(self):
        self.assertEqual(ask._value_hints({"x": {"features": [_pt(n=1)]}}), "")


class FriendlyErrorTests(SimpleTestCase):
    def test_none_comparison(self):
        msg = ask._friendly_error("Node filtered_houses failed: '<=' not supported between instances of 'NoneType' "
                                  "and 'int'")
        self.assertIn("filtered_houses", msg)
        self.assertIn("مقدار خالی", msg)
        self.assertIn("جزئیات فنی", msg)


class SeqClient:
    """مدل زبانی ساختگی: هر بار پاسخ بعدی؛ پیام‌ها را برای بررسی نگه می‌دارد."""

    def __init__(self, *plans):
        self.plans, self.calls = list(plans), []

    def complete(self, messages, **kw):
        import json
        self.calls.append(messages)
        return json.dumps(self.plans[min(len(self.calls), len(self.plans)) - 1], ensure_ascii=False)


def _plan(*ops):
    return {"goal": "g", "entities": [], "outputs": [], "operations": list(ops)}


def _filter(value, field="deal", src="houses", out="rent"):
    return {"op": "filter_attribute", "inputs": {"vector": src}, "output": out,
            "params": {"where": {"field": field, "op": "eq", "value": value}}}


def _hs(n=12):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [51.4 + i * 0.001, 35.7]},
         "properties": {"id": i, "deal": "اجاره" if i % 3 else "فروش", "price": 100 + i}} for i in range(n)]}


class AnalyzeTests(SimpleTestCase):
    def setUp(self):
        try:
            import s3geo  # noqa: F401
        except ImportError:
            self.skipTest("s3geo نصب نیست")

    def test_wrong_value_is_repaired_before_running(self):
        client = SeqClient(_plan(_filter("rent")), _plan(_filter("اجاره")))
        out = ask.analyze("خانه‌های اجاره‌ای", {"houses": _hs()}, client)
        self.assertEqual(out.kind, "layer")
        self.assertEqual(len(out.feats), 8)
        self.assertEqual(out.attempts, 2)
        self.assertIn("اجاره", client.calls[1][-1]["content"])  # مقادیر واقعی به مدل برگشت

    def test_missing_column_is_repaired(self):
        client = SeqClient(_plan(_filter("اجاره", field="usage")), _plan(_filter("اجاره")))
        out = ask.analyze("خانه‌های اجاره‌ای", {"houses": _hs()}, client)
        self.assertEqual((out.kind, out.attempts), ("layer", 2))
        self.assertIn("usage", client.calls[1][-1]["content"])

    def test_empty_after_run_gets_one_retry_then_reports_empty(self):
        # ستون‌های متنی کم‌تنوع بررسی می‌شوند؛ شرط عددی از بررسی قبل از اجرا رد می‌شود و فقط پس از اجرا خالی می‌شود
        empty = _plan({"op": "filter_attribute", "inputs": {"vector": "houses"}, "output": "x",
                       "params": {"where": {"field": "price", "op": "gt", "value": 99999}}})
        client = SeqClient(empty)
        out = ask.analyze("خانه‌های گران", {"houses": _hs()}, client)
        self.assertEqual(out.kind, "empty")
        self.assertEqual(len(client.calls), 2)
        self.assertIn("ZERO", client.calls[1][-1]["content"])

    def test_good_plan_costs_one_call(self):
        client = SeqClient(_plan(_filter("اجاره")))
        out = ask.analyze("خانه‌های اجاره‌ای", {"houses": _hs()}, client)
        self.assertEqual((out.kind, out.attempts, len(client.calls)), ("layer", 1, 1))

    def test_group_by_summary_is_a_table(self):
        plan = _plan({"op": "aggregate_table", "inputs": {"vector": "houses"}, "output": "t",
                      "params": {"group_by": ["deal"], "aggregations": {"price": ["sum"]}}})
        out = ask.analyze("جمع قیمت به تفکیک نوع معامله", {"houses": _hs()}, SeqClient(plan))
        self.assertEqual(out.kind, "table")
        self.assertEqual(len(out.rows), 2)
        self.assertEqual({r["deal"] for r in out.rows}, {"اجاره", "فروش"})

    def test_llm_failure_on_first_attempt_is_an_error(self):
        class Boom:
            def complete(self, *a, **k):
                raise RuntimeError("request failed: 401")

        with self.assertRaisesMessage(ask.AskError, "کلید"):
            ask.analyze("هر پرسشی", {"houses": _hs()}, Boom())


class CheckPlanTests(SimpleTestCase):
    def _spec(self, *ops):
        return NS(operations=[NS(op=o["op"], inputs=o["inputs"], params=o["params"], output=o["output"]) for o in ops])

    def test_columns_flow_through_preserving_ops(self):
        hs = {"houses": _hs()}
        crs = {"op": "crs_transform", "inputs": {"vector": "houses"}, "params": {}, "output": "h"}
        ok = {"op": "filter_attribute", "inputs": {"vector": "h"}, "output": "r",
              "params": {"where": {"field": "deal", "op": "eq", "value": "اجاره"}}}
        self.assertEqual(ask._check_plan(self._spec(crs, ok), hs), [])
        bad = {**ok, "params": {"where": {"field": "deal", "op": "in", "value": ["rent", "اجاره"]}}}
        self.assertIn("'rent'", ask._check_plan(self._spec(crs, bad), hs)[0])

    def test_underscore_columns_and_open_outputs_are_not_checked(self):
        hs = {"houses": _hs()}
        near = {"op": "spatial_nearest", "inputs": {"source": "houses", "target": "houses"}, "params": {}, "output": "n"}
        dist = {"op": "filter_attribute", "inputs": {"vector": "n"}, "output": "r",
                "params": {"where": {"field": "_nearest_distance", "op": "lte", "value": 5}}}
        agg = {"op": "aggregate_table", "inputs": {"vector": "houses"}, "params": {}, "output": "a"}
        later = {"op": "filter_attribute", "inputs": {"vector": "a"}, "output": "r2",
                 "params": {"where": {"field": "anything_new", "op": "gt", "value": 1}}}
        self.assertEqual(ask._check_plan(self._spec(near, dist, agg, later), hs), [])

    def test_case_hint_and_high_cardinality_value_not_checked(self):
        hs = {"houses": _hs(80)}
        wrong_case = {"op": "filter_attribute", "inputs": {"vector": "houses"}, "output": "r",
                      "params": {"where": {"field": "Deal", "op": "eq", "value": "اجاره"}}}
        self.assertIn("Did you mean 'deal'", ask._check_plan(self._spec(wrong_case), hs)[0])
        ids = {"houses": {"features": [{"geometry": None, "properties": {"name": f"n{i}"}} for i in range(80)]}}
        by_name = {"op": "filter_attribute", "inputs": {"vector": "houses"}, "output": "r",
                   "params": {"where": {"field": "name", "op": "eq", "value": "نامی که نیست"}}}
        self.assertEqual(ask._check_plan(self._spec(by_name), ids), [])


class AutoNamesTests(SimpleTestCase):
    def test_output_name_from_question(self):
        self.assertEqual(ask._auto_output("یک لایه جدید به نام rent_cases ایجاد کن"), "rent_cases")
        self.assertEqual(ask._auto_output("لایه‌ای با نام «Rent_Cases» بساز"), "rent_cases")
        self.assertTrue(ask._auto_output("بدون نام").startswith("ask_"))


class BenchmarkTests(SimpleTestCase):
    def test_questions_are_well_formed_and_runner_scores_with_scripted_model(self):
        try:
            import s3geo  # noqa: F401
        except ImportError:
            self.skipTest("s3geo نصب نیست")
        from analysis import benchmark

        qs = benchmark.load_questions()
        self.assertGreaterEqual(len(qs), 15)
        self.assertTrue(all({"q", "kind", "expected"} <= set(q) for q in qs))
        plan = _plan({"op": "filter_attribute", "inputs": {"vector": "schools"}, "output": "r",
                      "params": {"where": {"field": "level", "op": "eq", "value": "متوسطه اول"}}})
        rows = benchmark.run(SeqClient(plan), qs[:1])
        self.assertTrue(rows[0]["ok"], rows[0])  # ۵۷ مدرسهٔ متوسطه اول
        self.assertEqual(benchmark.summary(rows)["accuracy"], 100)
