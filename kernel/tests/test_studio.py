import io
import zipfile
from unittest import mock

from django.test import TestCase

from kernel import pkg, studio
from kernel.models import PluginDraft

PASS = "Str0ng-Admin-Pass"
PAGE = studio.TEMPLATES["monitor"][0].format(key="live")


def draft(**kw):
    base = dict(plugin_id="fleet", name="پایش ناوگان", version="1.0.0", kind="custom", requires="", pages={"live": PAGE})
    return PluginDraft(**{**base, **kw})


class StudioCoreTests(TestCase):
    def test_generated_manifest_is_valid_and_matches_pages(self):
        files = studio.files_of(draft(requires="databases"))
        m = pkg._manifest(files)
        self.assertEqual((m["id"], m["tier"], m["requires"]), ("fleet", 1, ["databases"]))
        self.assertEqual(m["contributes"]["pages"], ["pages/live.toml"])
        self.assertTrue(studio.ok(studio.check(draft(requires="databases"))))

    def test_name_with_quotes_cannot_break_manifest(self):
        d = draft(name='x" \n[evil]\nk="v')
        m = pkg._manifest(studio.files_of(d))
        self.assertEqual(m["name"], 'x" \n[evil]\nk="v')
        self.assertNotIn("evil", m)

    def test_errors_are_reported_in_persian(self):
        cases = [draft(plugin_id="Bad Id"), draft(version="x"), draft(kind="system"), draft(pages={}),
                 draft(pages={"live": "not toml ["}), draft(pages={"live": PAGE.replace("kpi", "weird")}),
                 draft(requires="ghost_plugin"), draft(plugin_id="billing")]
        for d in cases:
            with self.subTest(d=d.plugin_id + d.version + d.kind):
                steps = studio.check(d)
                self.assertFalse(studio.ok(steps))
                self.assertTrue(steps[-1]["detail"])

    def test_writes_are_flagged_and_need_editor(self):
        form = studio.TEMPLATES["form"][0].format(key="rep")
        steps = studio.check(draft(pages={"rep": form}))
        self.assertTrue(studio.ok(steps))
        self.assertIn("my_table", steps[-1]["detail"])
        bad = studio.check(draft(pages={"rep": form.replace('need = "editor"', 'need = "viewer"')}))
        self.assertFalse(studio.ok(bad))

    def test_export_has_no_signature_and_roundtrips_through_inspect_stages(self):
        z = zipfile.ZipFile(io.BytesIO(studio.export_zip(draft())))
        self.assertEqual(sorted(z.namelist()), ["pages/live.toml", "plugin.toml"])
        self.assertNotIn(pkg.SIG_NAME, z.namelist())




# ---------------------------------------------------------------------- سطح ۲ در استودیو
from django.test import override_settings as _override  # noqa: E402

BLOCK = studio.HANDLER_TEMPLATES["block"][0]
IMPORTER = studio.HANDLER_TEMPLATES["importer"][0]
EXPORTER = studio.HANDLER_TEMPLATES["exporter"][0]
ALERT = studio.HANDLER_TEMPLATES["alert"][0]
IO_PAGE = PAGE.replace('need = "viewer"', 'need = "editor"') + (
    '\n[[imports]]\nkey = "gps"\ntitle = "ورود"\nhandler = "parse"\nextensions = [".csv"]\n'
    '\n[[exports]]\nkey = "rep"\ntitle = "خروجی"\nhandler = "report"\nformat = "csv"\n')


def draft2(**kw):
    base = dict(plugin_id="fleet", name="پایش", version="1.0.0", kind="custom", requires="",
                pages={"live": IO_PAGE}, code={"parse": IMPORTER, "report": EXPORTER}, alerts={"parse": 15},
                tests={"parse": studio.HANDLER_TESTS["importer"], "report": studio.HANDLER_TESTS["exporter"]})
    return PluginDraft(**{**base, **kw})


class StudioTier2CoreTests(TestCase):
    def test_manifest_becomes_tier2_with_handlers_and_alerts(self):
        m = pkg._manifest(studio.files_of(draft2()))
        self.assertEqual((m["tier"], m["contributes"]["handlers"]), (2, ["parse", "report"]))
        self.assertEqual(m["contributes"]["alerts"], [{"handler": "parse", "every_minutes": 15}])
        self.assertTrue(studio.ok(studio.check(draft2())))
        self.assertEqual(pkg._manifest(studio.files_of(draft()))["tier"], 1)  # بدون کد همان سطح ۱

    def test_every_template_passes_the_real_check(self):
        for name, (src, _label) in studio.HANDLER_TEMPLATES.items():
            with self.subTest(template=name):
                d = draft2(code={"parse": src, "report": EXPORTER}, pages={"live": IO_PAGE},
                           tests={"parse": studio.HANDLER_TESTS[name], "report": studio.HANDLER_TESTS["exporter"]})
                steps = studio.check(d)
                self.assertTrue(studio.ok(steps), steps)

    def test_dangerous_code_and_bad_alert_are_reported(self):
        steps = studio.check(draft2(code={"parse": "import os\ndef handle(c, p): return 1", "report": EXPORTER}))
        bad = next(s for s in steps if not s["ok"])
        self.assertIn("code/parse.py:", bad["detail"])
        steps = studio.check(draft2(alerts={"parse": 1}))
        self.assertIn("every_minutes", next(s for s in steps if not s["ok"])["detail"])
        steps = studio.check(draft2(pages={"live": IO_PAGE.replace('handler = "parse"', 'handler = "ghost"')}))
        self.assertIn("handler «ghost»", next(s for s in steps if not s["ok"])["detail"])

    def test_export_zip_contains_code_and_no_signature(self):
        names = zipfile.ZipFile(io.BytesIO(studio.export_zip(draft2()))).namelist()
        self.assertEqual(sorted(names), ["code/parse.py", "code/report.py", "pages/live.toml", "plugin.toml", "tests/parse.toml", "tests/report.toml"])

    def test_tests_are_mandatory_and_run_in_studio(self):
        steps = studio.check(draft2(tests={}))
        bad = next(x for x in steps if not x["ok"])
        self.assertEqual(bad["stage"], "آزمون‌های بسته (ساختار)")
        self.assertIn("آزمون لازم است", bad["detail"])
        res = studio.run_tests(draft2())
        self.assertTrue(res["ok"], res)
        self.assertEqual(len(res["results"]), 2)
        broken = draft2(tests={"parse": studio.HANDLER_TESTS["importer"].replace("rows_count = 2", "rows_count = 9"), "report": studio.HANDLER_TESTS["exporter"]})
        res = studio.run_tests(broken)
        self.assertFalse(res["ok"])
        self.assertIn("انتظار 9", [r["message"] for r in res["results"] if not r["ok"]][0])
        with _override(PLUGIN_RUNNER_MODE="off"):
            self.assertIn("فعال نیست", studio.run_tests(draft2())["error"])

    def test_roles_detect_import_export_block(self):
        d = draft2(pages={"live": IO_PAGE + '\n[[blocks]]\nkind = "table"\nhandler = "calc"\n'}, code={"parse": IMPORTER, "report": EXPORTER, "calc": BLOCK})
        self.assertEqual({k: v[0] for k, v in studio.roles(d).items()}, {"parse": "import", "report": "export", "calc": "block"})


class StudioTrialTests(TestCase):
    def test_exporter_trial_validates_like_production(self):
        with mock.patch("kernel.pagekit.read_select", lambda ws, q, a=None: {"columns": ["n"], "rows": [[7]]}):
            out = studio.trial(draft2(), "report", {}, ws=mock.Mock(pk=1))
        self.assertTrue(out["ok"], out)
        self.assertIn("خروجی معتبر", out["verdict"][0])
        self.assertIn("report.csv", out["verdict"][0])

    def test_importer_trial_uses_uploaded_file_and_nothing_is_written(self):
        with mock.patch("kernel.pluginio.create_table") as create:
            out = studio.trial(draft2(), "parse", {}, b"a,1.5\nb,2\n")
        self.assertTrue(out["ok"], out)
        self.assertIn("2 ردیف", out["verdict"][0])
        create.assert_not_called()

    def test_bad_import_shape_and_missing_file_are_errors(self):
        d = draft2(code={"parse": "def handle(c, p):\n    return {'columns': [{'name': 'a', 'type': 'money'}], 'rows': []}", "report": EXPORTER})
        out = studio.trial(d, "parse", {}, b"x")
        self.assertFalse(out["ok"])
        self.assertIn("معتبر نیست", out["error"])
        self.assertIn("فایلی ندارد", studio.trial(draft2(), "parse", {})["error"])

    def test_without_database_sql_is_unavailable(self):
        out = studio.trial(draft2(), "report", {})
        self.assertIn("دسترسی ندارد", out["error"])

    def test_static_check_blocks_execution_and_off_mode_never_runs(self):
        bad = draft2(code={"parse": "import os\ndef handle(c, p): return 1", "report": EXPORTER})
        with mock.patch("kernel.runner.client.run_files") as run:
            out = studio.trial(bad, "parse", {})
            self.assertIn("بررسی ایستا", out["error"])
            run.assert_not_called()
        with _override(PLUGIN_RUNNER_MODE="off"):
            self.assertIn("فعال نیست", studio.trial(draft2(), "report", {})["error"])
        self.assertIn("در پیش‌نویس نیست", studio.trial(draft2(), "nope", {})["error"])

    def test_handler_failure_is_reported_and_logs_are_captured(self):
        d = draft2(code={"parse": "def handle(c, p):\n    c.log('hello')\n    return 1/0", "report": EXPORTER})
        out = studio.trial(d, "parse", {}, b"x")
        self.assertIn("ZeroDivisionError", out["error"])
        d = draft2(code={"parse": "def handle(c, p):\n    c.log('hello')\n    return {'columns': [{'name': 'a', 'type': 'text'}], 'rows': [['x']]}", "report": EXPORTER})
        self.assertEqual(studio.trial(d, "parse", {}, b"x")["logs"], ["hello"])
