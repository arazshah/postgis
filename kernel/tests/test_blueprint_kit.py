"""پوشش کامل کیت صفحه در نقشه‌ی پلاگین: فیلتر صفحه، ویرایش ردیف، گزارش PDF، منبع بیرونی، فیلد هندسی و انتخابی (ADR-0010 مرحله‌ی ۳)."""
import copy
import tomllib

from django.test import SimpleTestCase

from kernel import blueprint, pagekit, sampledata, wizard

PID = "farm"
TABLE = {"name": "farm_plots", "columns": [
    {"name": "owner", "type": "text", "required": True, "label": "مالک"},
    {"name": "crop", "type": "text", "label": "محصول", "choices": [["wheat", "گندم"], ["rice", "برنج"]]},
    {"name": "area", "type": "double", "label": "مساحت", "min": 0, "max": 10000},
    {"name": "boundary", "type": "polygon", "label": "مرز"},
    {"name": "at", "type": "timestamptz", "auto_now": True}]}
WEATHER = {"name": "farm_weather", "columns": [
    {"name": "day", "type": "date"}, {"name": "tmax", "type": "double"}, {"name": "tmin", "type": "double"}]}
RANGE = {"name": "hours", "kind": "choice", "label": "بازه", "default": "60", "choices": [["60", "یک ساعت"], ["360", "شش ساعت"]]}
CROP = {"name": "crop", "kind": "text", "label": "محصول"}


def spec():
    s = {"intro": {}, "tables": [copy.deepcopy(TABLE), copy.deepcopy(WEATHER)], "pages": []}
    return blueprint.apply(s, PID, {"op": "page.add", "title": "مزرعه", "need": "editor", "blocks": [{"kind": "text", "text": "راهنما"}]})


def add(s, blk, key="p1"):
    return blueprint.apply(s, PID, {"op": "block.add", "page": key, "block": blk})


def compiled(s):
    return {k: tomllib.loads(v) for k, v in wizard.compile_pages(PID, s).items()}


class ParamsTests(SimpleTestCase):
    def test_since_param_and_where_sql(self):
        s = blueprint.apply(spec(), PID, {"op": "page.set", "key": "p1", "params": [RANGE, CROP]})
        s = add(s, {"kind": "kpi", "table": "farm_plots", "agg": "count", "since_col": "at", "since_param": "hours", "where": [{"param": "crop", "col": "crop"}]})
        page = compiled(s)["p1"]
        sql = page["blocks"][1]["sql"]
        self.assertIn("make_interval(mins => %(hours)s::int)", sql)
        self.assertIn('("crop"::text = %(crop)s or %(crop)s = \'\')', sql)
        self.assertEqual([p["name"] for p in page["params"]], ["hours", "crop"])
        self.assertTrue(blueprint.analyze(s, PID)["ok"])

    def test_param_binding_errors(self):
        s = add(blueprint.apply(spec(), PID, {"op": "page.set", "key": "p1", "params": [RANGE]}), {"kind": "kpi", "table": "farm_plots", "since_col": "at", "since_param": "nope"})
        self.assertTrue(any("فیلتر" in i["message"] for i in blueprint.analyze(s, PID)["issues"]))
        bad = {**RANGE, "choices": [["x", "بد"]]}
        s2 = add(blueprint.apply(spec(), PID, {"op": "page.set", "key": "p1", "params": [bad]}), {"kind": "kpi", "table": "farm_plots", "since_col": "at", "since_param": "hours"})
        self.assertFalse(blueprint.analyze(s2, PID)["ok"])
        for params in ([RANGE, RANGE], [{"name": "n", "kind": "int", "label": "ن"}], [{"name": "BAD", "kind": "text", "label": "ب"}], [CROP] * 7):
            with self.assertRaises(blueprint.BlueprintError):
                blueprint.apply(spec(), PID, {"op": "page.set", "key": "p1", "params": params})

    def test_sample_preview_uses_param_default(self):
        s = blueprint.apply(spec(), PID, {"op": "page.set", "key": "p1", "params": [{**RANGE, "default": "360"}]})
        s = add(s, {"kind": "kpi", "table": "farm_plots", "agg": "count", "since_col": "at", "since_param": "hours"})
        v = sampledata.preview(s, "p1")["all_blocks"][1]["value"]
        self.assertTrue(v.replace(",", "").isdigit() or v == "0")


class FieldTests(SimpleTestCase):
    def test_form_with_geometry_choice_and_labels(self):
        s = add(spec(), {"kind": "form", "table": "farm_plots", "title": "قطعه", "submit": "ثبت قطعه", "hint": "مرز را بکشید"})
        form = compiled(s)["p1"]["forms"][0]
        by = {f["name"]: f for f in form["fields"]}
        self.assertEqual((by["crop"]["kind"], by["crop"]["choices"]), ("choice", [["wheat", "گندم"], ["rice", "برنج"]]))
        self.assertEqual((by["boundary"]["kind"], by["boundary"]["geom"]), ("geometry", "polygon"))
        self.assertEqual((by["owner"]["label"], by["area"]["max"]), ("مالک", 10000))
        self.assertEqual((form["submit"], form["hint"]), ("ثبت قطعه", "مرز را بکشید"))
        self.assertNotIn("at", by)  # زمان خودکار

    def test_ingest_skips_geometry_by_default(self):
        s = add(spec(), {"kind": "ingest", "table": "farm_plots"})
        names = [f["name"] for f in compiled(s)["p1"]["ingest"][0]["fields"]]
        self.assertNotIn("boundary", names)


class RecordsTests(SimpleTestCase):
    def test_records(self):
        s = add(spec(), {"kind": "records", "table": "farm_plots", "title": "قطعه‌ها", "columns": ["owner", "crop"], "can_delete": False, "limit": 30})
        page = compiled(s)["p1"]
        rec = page["records"][0]
        self.assertEqual((rec["columns"], rec["can_delete"], rec["limit"]), (["owner", "crop"], False, 30))
        self.assertEqual([t["name"] for t in page["tables"]], ["farm_plots"])  # جدول به صفحه می‌آید
        self.assertIn("boundary", [f["name"] for f in rec["fields"]])
        pagekit.parse_page(PID, page)

    def test_records_needs_plain_column(self):
        s = add(spec(), {"kind": "records", "table": "farm_plots", "fields": ["boundary"]})
        self.assertFalse(blueprint.analyze(s, PID)["ok"])


class ReportTests(SimpleTestCase):
    def test_report_maps_block_ids_to_indexes(self):
        s = add(spec(), {"kind": "kpi", "table": "farm_plots", "title": "الف"})
        s = add(s, {"kind": "form", "table": "farm_plots"})   # بلوک نمایشی نیست؛ شماره‌گذاری را بههم نمی‌زند
        s = add(s, {"kind": "table", "table": "farm_plots", "title": "ب"})
        ids = [b["id"] for b in s["pages"][0]["blocks"]]
        s = add(s, {"kind": "report", "title": "گزارش هفتگی", "blocks": [ids[3], ids[1]], "landscape": True, "button": "PDF"})
        rep = compiled(s)["p1"]["reports"][0]
        self.assertEqual((rep["blocks"], rep["orientation"], rep["button"]), ([3, 2], "landscape", "PDF"))

    def test_report_rejects_foreign_block(self):
        s = add(spec(), {"kind": "kpi", "table": "farm_plots"})
        s = add(s, {"kind": "report", "title": "گ", "blocks": ["nope"]})
        self.assertFalse(blueprint.analyze(s, PID)["ok"])


SRC = {"kind": "source", "title": "هواشناسی", "table": "farm_weather", "url": "https://api.open-meteo.com/v1/forecast", "layout": "columns",
       "rows_path": "daily", "every_minutes": 180, "since_days": 2,
       "query": [["latitude", "{lat}"], ["longitude", "{lon}"], ["daily", "temperature_2m_max,temperature_2m_min"], ["timezone", "auto"]],
       "map": [{"column": "day", "path": "time"}, {"column": "tmax", "path": "temperature_2m_max"}, {"column": "tmin", "path": "temperature_2m_min"}],
       "inputs": [{"name": "lat", "label": "عرض", "kind": "number", "min": -90, "max": 90}, {"name": "lon", "label": "طول", "kind": "number", "min": -180, "max": 180}]}


class SourceTests(SimpleTestCase):
    def test_source_compiles(self):
        s = add(spec(), SRC)
        page = compiled(s)["p1"]
        src = page["sources"][0]
        self.assertEqual((src["table"], src["layout"], src["rows_path"]), ("farm_weather", "columns", "daily"))
        self.assertEqual([(f["name"], f["path"]) for f in src["fields"]], [("day", "time"), ("tmax", "temperature_2m_max"), ("tmin", "temperature_2m_min")])
        self.assertEqual(src["query"]["latitude"], "{lat}")
        self.assertEqual(page["need"], "editor")
        self.assertTrue(blueprint.analyze(s, PID)["ok"])

    def test_source_validation_comes_from_kit(self):
        for over in ({"url": "http://x.com/a"}, {"url": "https://127.0.0.1/a"}, {"map": []}, {"every_minutes": 5}, {"query": [["a", "{unknown}"]]}):
            s = add(spec(), {**SRC, **over})
            self.assertFalse(blueprint.analyze(s, PID)["ok"], over)

    def test_source_secret_exclusive(self):
        s = add(spec(), {**SRC, "secret_header": "X-Api-Key", "secret_param": "key"})
        self.assertFalse(blueprint.analyze(s, PID)["ok"])
        s = add(spec(), {**SRC, "secret_header": "X-Api-Key"})
        self.assertTrue(blueprint.analyze(s, PID)["ok"])


class PreviewKinds(SimpleTestCase):
    def test_new_kinds_are_actions_in_preview(self):
        s = add(spec(), {"kind": "kpi", "table": "farm_plots"})
        for blk in ({"kind": "records", "table": "farm_plots"}, SRC, {"kind": "report", "title": "گ"}):
            s = add(s, blk)
        pv = sampledata.preview(s, "p1")
        self.assertEqual(sorted(a["action"] for a in pv["actions"]), ["records", "report", "source"])
        self.assertEqual(len(pv["blocks"]), 2)  # متن + شمارنده
