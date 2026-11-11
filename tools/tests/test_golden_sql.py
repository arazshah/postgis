"""SQL طلایی: خروجی هر ابزار برای ورودی‌های ثابت باید با فایل ثبت‌شده یکی بماند (محافظ بازسازی موتور ابزارها)."""
import json

from django.test import SimpleTestCase

from tools import engine

from . import golden


class GoldenSqlTests(SimpleTestCase):
    maxDiff = None

    def test_every_case_matches_the_recorded_output(self):
        saved = json.loads(golden.PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(saved), len(golden.CASES))
        for row in saved:
            with self.subTest(tool=row["tool"], params=row["params"]):
                got = json.loads(json.dumps(golden.render(engine, row["tool"], row["routing"], row["params"])))
                self.assertEqual(got, row["result"])

    def test_cases_cover_every_tool_with_a_select_and_an_error(self):
        saved = json.loads(golden.PATH.read_text(encoding="utf-8"))
        ok = {r["tool"] for r in saved if "sql" in r["result"]}
        self.assertEqual(ok, {t.key for t in engine.TOOLS})


class NewToolIsOneModuleTests(SimpleTestCase):
    """ابزار تازه فقط با ثبت یک کلاس اضافه می‌شود: گالری، فرم، اعتبارسنجی و خلاصه بدون تغییر فایل دیگر."""

    def setUp(self):
        from psycopg import sql

        from kernel.plugins import registry
        from tools import sdk

        class Centroid(sdk.ToolPlugin):
            key, order, category, icon = "zz_centroid", 999, "proximity", "t-buffer"
            title, description, output, example = "مرکز عارضه", "مرکز هر عارضه را می‌دهد.", "نقطه", "مرکز هر محله."
            columns = ("geom",)
            params = (sdk.Param("layer", "layer", "لایه"),)

            def build(self, ctx):
                t = ctx.table("layer")
                col, srid, _ = sdk.geom_of(t)
                return sql.SQL("SELECT ST_Centroid({g}) AS geom FROM {t} s").format(g=sdk.geom4326("s", col, srid), t=sdk.ident(t))

        class Unsafe(Centroid):
            key = "zz_unsafe"

            def build(self, ctx):
                return "SELECT 1"

        sdk.register(Centroid)
        sdk.register(Unsafe)
        self.addCleanup(lambda: [registry._points[sdk.POINT].pop(k) for k in ("zz_centroid", "zz_unsafe")])

    def test_registered_tool_is_listed_validated_and_summarized(self):
        from django.core.checks import run_checks

        from tools import catalog

        self.assertIn("zz_centroid", catalog.info())
        self.assertIn("zz_centroid", [t.key for g in catalog.category_groups() for t in g["tools"]])
        self.assertEqual(engine.public_params("zz_centroid"), ("layer", "output", "replace"))
        got = golden.render(engine, "zz_centroid", False, {"layer": "public.schools"})
        self.assertIn('ST_Centroid(ST_SetSRID("s"."geom"::geometry, 4326))', got["sql"])
        self.assertEqual(got["summary"], "schools")
        self.assertEqual([e for e in run_checks() if e.id == "tools.E001"], [])

    def test_raw_string_sql_is_rejected(self):
        got = golden.render(engine, "zz_unsafe", False, {"layer": "public.schools"})
        self.assertEqual(got, {"error": "ابزار SQL امن برنگرداند."})
