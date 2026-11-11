"""SQL طلایی: خروجی هر ابزار برای ورودی‌های ثابت باید با فایل ثبت‌شده یکی بماند (محافظ بازسازی موتور ابزارها)."""
import json

from django.test import SimpleTestCase

from analysis import tools as engine

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
