"""سطح ۲: بسته‌ی دارای کد، بررسی ایستا، ثبت handler و اجرای بلوک از راه جعبه‌ی محلی."""
from unittest import mock

from django.test import TestCase, override_settings

from kernel import handlers, pagekit, pkg
from kernel.plugins import registry
from kernel.runner import client
from kernel.tests.test_pkg import KEYS, PRIV, build  # noqa: F401

MANIFEST = '''id = "compute"
name = "محاسبه"
version = "1.0.0"
api = 1
kind = "custom"
tier = 2
[contributes]
pages = ["pages/live.toml"]
handlers = ["stats"]
'''
PAGE = '''key = "live"
title = "آمار"
icon = "chart"
group = "data"
[[blocks]]
kind = "table"
title = "نتیجه"
handler = "stats"
'''
CODE = '''import statistics

def handle(ctx, params):
    r = ctx.sql("select n from t")
    vals = [row[0] for row in r["rows"]]
    return {"columns": ["شاخص", "مقدار"], "rows": [["میانگین", statistics.mean(vals)], ["تعداد", len(vals)]]}
'''


def files(**over):
    f = {"plugin.toml": MANIFEST.encode(), "pages/live.toml": PAGE.encode(), "code/stats.py": CODE.encode()}
    f.update({k: (v.encode() if isinstance(v, str) else v) for k, v in over.items()})
    return {k: v for k, v in f.items() if v is not None}


def failed(data):
    ins = pkg.inspect(data, keys={"acme": PRIV.public_key()})
    return ins, next((s for s in ins.steps if not s.ok), None)


class Tier2PackageTests(TestCase):
    def test_good_tier2_package_passes_and_exposes_code(self):
        ins, bad = failed(build(files()))
        self.assertIsNone(bad, ins.report())
        self.assertEqual(list(ins.code), ["stats"])
        self.assertEqual(ins.pages[0].blocks[0].handler, "stats")
        self.assertIn("کد سطح ۲", [s.stage for s in ins.steps])

    def test_dangerous_code_is_rejected_with_line_numbers(self):
        for src in ("import os\ndef handle(c, p): return 1", "def handle(c, p):\n    return ().__class__", "def handle(c, p):\n    open('x')"):
            with self.subTest(src=src):
                _ins, bad = failed(build(files(**{"code/stats.py": src})))
                self.assertEqual(bad.stage, "کد سطح ۲")
                self.assertIn("code/stats.py:", bad.detail)
        _ins, bad = failed(build(files(**{"code/stats.py": "x = 1"})))
        self.assertIn("handle", bad.detail)

    def test_code_requires_tier2_and_consistent_lists(self):
        _i, bad = failed(build(files(**{"plugin.toml": MANIFEST.replace("tier = 2", "tier = 1")})))
        self.assertIn("سطح ۲", bad.detail)
        _i, bad = failed(build(files(**{"plugin.toml": MANIFEST.replace('["stats"]', '["other"]')})))
        self.assertIn("یکی نیست", bad.detail)
        _i, bad = failed(build(files(**{"code/stats.py": None, "plugin.toml": MANIFEST.replace('handlers = ["stats"]', "handlers = []")})))
        self.assertIn("handler لازم", bad.detail)

    def test_block_must_reference_a_declared_handler(self):
        _i, bad = failed(build(files(**{"pages/live.toml": PAGE.replace('"stats"', '"ghost"')})))
        self.assertIn("handler «ghost»", bad.detail)

    def test_import_and_export_must_reference_declared_handlers_and_are_flagged_as_writes(self):
        io_page = PAGE + ('[[imports]]\nkey = "gps"\ntitle = "ورود"\nhandler = "stats"\n\n'
                          '[[exports]]\nkey = "rep"\ntitle = "خروجی"\nhandler = "stats"\nformat = "csv"\n')
        io_page = io_page.replace('group = "data"', 'group = "data"\nneed = "editor"')
        ins, bad = failed(build(files(**{"pages/live.toml": io_page})))
        self.assertIsNone(bad, ins.report())
        self.assertIn("جدول تازه", ins.steps[-1].detail)
        _i, bad = failed(build(files(**{"pages/live.toml": io_page.replace('handler = "stats"\n\n[[exports]]', 'handler = "ghost"\n\n[[exports]]')})))
        self.assertIn("handler «ghost»", bad.detail)
        _i, bad = failed(build(files(**{"pages/live.toml": io_page.replace('need = "editor"', 'need = "viewer"')})))
        self.assertIn("editor", bad.detail)

    def test_only_safe_file_names_are_accepted(self):
        for name in ("code/Evil.py", "code/../x.py", "code/a.pyc", "code/sub/x.py", "lib/x.py"):
            with self.subTest(name=name):
                _i, bad = failed(build(files(**{name: "x=1"})))
                self.assertIsNotNone(bad)
                self.assertEqual(bad.stage, "دریافت و بازکردن امن")

    def test_block_spec_rules(self):
        for blk in ({"kind": "map", "handler": "stats"}, {"kind": "text", "text": "x", "handler": "stats"},
                    {"kind": "table", "handler": "stats", "sql": "select 1"}, {"kind": "table", "handler": "Bad Name"}):
            with self.subTest(blk=blk), self.assertRaises(pagekit.SpecError):
                pagekit.parse_page("p", {"key": "k", "title": "t", "blocks": [blk]})


class HandlerRenderTests(TestCase):
    def setUp(self):
        registry.register("compute", "محاسبه", kind="custom")
        self.addCleanup(registry.remove_plugin, "compute")
        handlers.register("compute", "stats", CODE)
        self.page = pagekit.parse_page("compute", {"key": "live", "title": "آمار", "blocks": [{"kind": "table", "handler": "stats", "title": "نتیجه"}]})
        p = mock.patch("kernel.pagekit.read_select", return_value={"columns": ["n"], "rows": [[2], [4], [6]]})
        self.read = p.start()
        self.addCleanup(p.stop)

    def render(self):
        return pagekit.render_block(object(), self.page, self.page.blocks[0], {})

    def test_local_mode_runs_code_and_renders_table(self):
        out = self.render()
        self.assertEqual(out["error"], "")
        self.assertEqual(out["headers"], ["شاخص", "مقدار"])
        self.assertEqual(out["rows"], [["میانگین", "4"], ["تعداد", "3"]])

    @override_settings(PLUGIN_RUNNER_MODE="off")
    def test_off_mode_never_executes_code(self):
        out = self.render()
        self.assertIn("فعال نیست", out["error"])
        self.read.assert_not_called()

    def test_code_errors_become_short_block_errors(self):
        handlers.register("compute", "stats", "def handle(c, p):\n    return 1 / 0")
        out = self.render()
        self.assertIn("ZeroDivisionError", out["error"])
        handlers.register("compute", "stats", "def handle(c, p):\n    return {'rows': 1}")
        self.assertIn("columns", self.render()["error"])

    def test_missing_handler_and_runs_are_metered(self):
        from kernel import metering

        self.render()
        self.assertEqual(metering.used("compute", "handler_runs"), 1)
        registry.remove_plugin("compute")
        registry.register("compute", "محاسبه", kind="custom")
        self.assertIn("در دسترس نیست", self.render()["error"])

    def test_client_unknown_mode_is_refused(self):
        with override_settings(PLUGIN_RUNNER_MODE="weird"), self.assertRaises(client.RunnerError):
            client.execute("compute", "stats", {}, lambda q, a: {})
