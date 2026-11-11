"""آزمون خودکار بسته‌ی سطح ۲: قالب، انتظارها، اجرا در runner، اتصال به بارگذاری و فعال‌سازی."""
from django.test import TestCase, override_settings

from kernel import pkg, pkgtest
from kernel.tests.test_pkg import PRIV
from kernel.tests.test_tier2 import CODE, TESTS, build, files

IMPORTER = '''def handle(ctx, p):
    rows = [l.split(",") for l in ctx.file().decode().splitlines()]
    return {"columns": [{"name": "a", "type": "text"}, {"name": "b", "type": "double"}], "rows": [[a, float(b)] for a, b in rows]}
'''
EXPORTER = '''def handle(ctx, p):
    n = ctx.sql("select count")["rows"][0][0]
    return {"filename": "r", "text": "n\\n" + str(n) + "\\n"}
'''
ALERT = '''def handle(ctx, p):
    n = ctx.sql("select count")["rows"][0][0]
    return {"alerts": [{"title": "زیاد"}] if n > 5 else []}
'''


def case(**kw):
    return pkgtest.Case(**{"name": "c", "expect": {"rows_count": 1}, **kw})


class ParseTests(TestCase):
    def test_valid_file_parses_into_cases(self):
        cases = pkgtest.parse(TESTS, "stats")
        self.assertEqual((len(cases), cases[0].sql[0]["match"], cases[0].expect["rows_count"]), (1, "select n", 2))

    def test_limits_and_errors(self):
        many = "".join('[[cases]]\n[cases.expect]\nrows_count = 1\n' for _ in range(11))
        for text, needle in [(many, "حداکثر"), ('[[cases]]\nfile = 5\n[cases.expect]\nrows_count = 1\n', "file"),
                             ('[[cases]]\nparams = 1\n[cases.expect]\nrows_count = 1\n', "params")]:
            with self.subTest(needle=needle), self.assertRaisesMessage(pkgtest.TestSpecError, needle):
                pkgtest.parse(text, "h")


class RunCaseTests(TestCase):
    def run_it(self, src, c, role="block", spec=None):
        return pkgtest.run_case("h", src, role, spec, c)

    def test_block_rows_count_and_equals(self):
        c = case(sql=({"match": "select n", "columns": ["n"], "rows": [[2], [4]]},), expect={"rows_count": 2})
        self.assertEqual(self.run_it(CODE, c), "")
        self.assertIn("انتظار 3", self.run_it(CODE, case(sql=c.sql, expect={"rows_count": 3})))
        self.assertIn("equals", self.run_it(CODE, case(sql=c.sql, expect={"equals": {"x": 1}})))

    def test_missing_mock_is_a_clear_failure(self):
        msg = self.run_it(CODE, case(expect={"rows_count": 1}))
        self.assertIn("پاسخ ساختگی", msg)

    def test_expected_error_and_unexpected_success(self):
        boom = "def handle(c, p):\n    return 1/0"
        self.assertEqual(self.run_it(boom, case(expect={"error_contains": "ZeroDivision"})), "")
        self.assertIn("اجرا شکست خورد", self.run_it(boom, case(expect={"rows_count": 1})))
        self.assertIn("انتظار خطا بود", self.run_it(CODE, case(sql=({"match": "select", "columns": ["n"], "rows": [[1]]},),
                                                              expect={"error_contains": "x"})))

    def test_importer_is_validated_like_production(self):
        spec = None
        ok = case(file=b"a,1\nb,2\n", expect={"rows_count": 2})
        self.assertEqual(self.run_it(IMPORTER, ok, "import", spec), "")
        self.assertIn("معتبر نیست", self.run_it("def handle(c, p):\n    return {'columns': [{'name': 'a', 'type': 'money'}], 'rows': []}", ok, "import", spec))
        self.assertIn("فایلی ندارد", self.run_it(IMPORTER, case(expect={"rows_count": 1}), "import", spec))

    def test_exporter_text_contains(self):
        from types import SimpleNamespace
        spec = SimpleNamespace(format="csv")
        sql = ({"match": "select count", "columns": ["n"], "rows": [[4]]},)
        self.assertEqual(self.run_it(EXPORTER, case(sql=sql, expect={"text_contains": "4"}), "export", spec), "")
        self.assertIn("را ندارد", self.run_it(EXPORTER, case(sql=sql, expect={"text_contains": "999"}), "export", spec))

    def test_alerts_count(self):
        sql = lambda n: ({"match": "select count", "columns": ["n"], "rows": [[n]]},)  # noqa: E731
        self.assertEqual(self.run_it(ALERT, case(sql=sql(9), expect={"alerts_count": 1})), "")
        self.assertEqual(self.run_it(ALERT, case(sql=sql(1), expect={"alerts_count": 0})), "")
        self.assertIn("انتظار 1", self.run_it(ALERT, case(sql=sql(1), expect={"alerts_count": 1})))

    @override_settings(PLUGIN_RUNNER_MODE="off")
    def test_runner_off_means_not_runnable_not_failed(self):
        with self.assertRaises(pkgtest.TestSpecError):
            self.run_it(CODE, case())


class PipelineTests(TestCase):
    def inspect(self, fs, **kw):
        return pkg.inspect(build(fs), keys={"acme": PRIV.public_key()}, **kw)

    def test_good_package_passes_with_tests_run(self):
        ins = self.inspect(files(), run_tests=True)
        self.assertTrue(ins.ok, ins.report())
        self.assertIn("آزمون‌های بسته (اجرا)", [s.stage for s in ins.steps])
        ran = [s for s in ins.steps if s.stage == "آزمون‌های بسته (اجرا)"][0]
        self.assertTrue(ran.ok)

    def test_not_run_by_default(self):
        ins = self.inspect(files())
        self.assertNotIn("آزمون‌های بسته (اجرا)", [s.stage for s in ins.steps])

    def test_failing_case_rejects_the_package_with_a_clear_message(self):
        bad = TESTS.replace("rows_count = 2", "rows_count = 99").replace(', "تعداد", 2]', ', "تعداد", 2]')
        ins = self.inspect(files(**{"tests/stats.toml": bad.replace('equals = {columns = ["شاخص", "مقدار"], rows = [["میانگین", 3], ["تعداد", 2]]}', "")}), run_tests=True)
        failed = next(s for s in ins.steps if not s.ok)
        self.assertEqual(failed.stage, "آزمون‌های بسته (اجرا)")
        self.assertIn("1 از 1 مورد ناموفق", failed.detail)
        self.assertIn("stats/میانگین دو مقدار", failed.detail)

    @override_settings(PLUGIN_RUNNER_MODE="off")
    def test_without_runner_the_package_cannot_pass_tests(self):
        ins = self.inspect(files(), run_tests=True)
        failed = next(s for s in ins.steps if not s.ok)
        self.assertIn("آزمون‌ها اجرا نشد", failed.detail)
        self.assertTrue(self.inspect(files()).ok)  # بررسی ایستا بدون اجرا همچنان می‌گذرد (مثل sync هنگام بارگذاری)

    def test_submit_and_activate_run_the_tests(self):
        from django.contrib.auth import get_user_model
        from django.test import override_settings as ov

        user = get_user_model().objects.create_admin("up", "Str0ng-Admin-Pass")
        other = get_user_model().objects.create_admin("ap", "Str0ng-Admin-Pass")
        bad = files(**{"tests/stats.toml": TESTS.replace("rows_count = 2", "rows_count = 99").replace(
            'equals = {columns = ["شاخص", "مقدار"], rows = [["میانگین", 3], ["تعداد", 2]]}', "")})
        with ov(PLUGIN_PUBLISHER_KEYS=f"acme={__import__('base64').b64encode(PRIV.public_key().public_bytes_raw()).decode()}"):
            rel = pkg.submit(build(bad), user)
            self.assertEqual(rel.status, "rejected")
            self.assertIn("آزمون‌های بسته (اجرا)", [r["stage"] for r in rel.report if not r["ok"]])
            good = pkg.submit(build(files()), user)
            self.assertEqual(good.status, "checked")
            with ov(PLUGIN_RUNNER_MODE="off"), self.assertRaisesMessage(pkg.PackageError, "آزمون‌ها اجرا نشد"):
                pkg.activate(good, other)
            pkg.activate(good, other)
