"""مرحله‌ی ۳ سطح ۳: پیش‌پرواز شروع، کارت پنل و فایل نشانه."""
import os
import shutil
import tempfile
import textwrap
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from kernel import admin_cards, extpreflight


def ids_stub(ok_for=None, fail=()):
    """run_fn ساختگی: ثبت فراخوانی‌ها؛ شکست برای شناسه‌هایی که تنها پلاگین فعال‌اند."""
    calls = []

    def fn(args, env):
        calls.append((args, env))
        off = {x for x in env["PLUGINS_DISABLED"].split(",") if x}
        if args[0] == "migrate":
            pid = args[-1].removeprefix("x_")
            return (False, "مهاجرت خراب") if pid in fail.get("migrate", ()) else (True, "")
        for pid in fail.get("check", ()):
            if pid not in off:
                return False, f"ImportError: {pid}"
        return True, ""

    fn.calls = calls
    return fn


class RunLogicTests(SimpleTestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"PLUGINS_DISABLED": "", "PLUGINS_SAFE_MODE": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_no_plugins_runs_nothing(self):
        fn = ids_stub(fail={})
        res = extpreflight.run([], run_fn=fn)
        self.assertEqual((res.disabled, res.safe_mode, fn.calls), ({}, False, []))

    def test_all_good(self):
        res = extpreflight.run(["aa", "bb"], run_fn=ids_stub(fail={}))
        self.assertEqual((res.disabled, res.safe_mode), ({}, False))

    def test_broken_import_is_quarantined_alone(self):
        res = extpreflight.run(["aa", "bad"], run_fn=ids_stub(fail={"check": ["bad"]}))
        self.assertEqual(list(res.disabled), ["bad"])
        self.assertIn("بارگذاری", res.disabled["bad"])
        self.assertFalse(res.safe_mode)

    def test_probe_isolates_each_plugin(self):
        fn = ids_stub(fail={})
        extpreflight.run(["aa", "bb"], run_fn=fn)
        first = fn.calls[0][1]["PLUGINS_DISABLED"].split(",")
        self.assertEqual(first, ["bb"])  # فقط aa روشن

    def test_migration_failure_quarantines(self):
        res = extpreflight.run(["aa", "mig"], migrate=True, run_fn=ids_stub(fail={"migrate": ["mig"]}))
        self.assertEqual(list(res.disabled), ["mig"])
        self.assertIn("مهاجرت", res.disabled["mig"])

    def test_no_migrate_by_default(self):
        fn = ids_stub(fail={"migrate": ["aa"]})
        res = extpreflight.run(["aa"], run_fn=fn)
        self.assertEqual(res.disabled, {})
        self.assertFalse([c for c in fn.calls if c[0][0] == "migrate"])

    def test_combination_failure_goes_safe_mode(self):
        calls = {"n": 0}

        def fn(args, env):
            calls["n"] += 1
            return (True, "") if calls["n"] <= 2 else (False, "تداخل مسیر")

        res = extpreflight.run(["aa", "bb"], run_fn=fn)
        self.assertTrue(res.safe_mode)
        self.assertIn("تداخل", res.reason)

    def test_already_disabled_is_skipped(self):
        os.environ["PLUGINS_DISABLED"] = "bad"
        fn = ids_stub(fail={"check": ["bad"]})
        res = extpreflight.run(["aa", "bad"], run_fn=fn)
        self.assertEqual(res.disabled, {})

    def test_shell_output_is_safe(self):
        r = extpreflight.Result(ids=["aa"], disabled={"aa": "x", "a;rm -rf": "y"}, safe_mode=True)
        out = extpreflight.shell_env(r)
        self.assertIn("EXT_DISABLED_NOW='aa'", out)
        self.assertNotIn("rm", out)
        self.assertIn("EXT_SAFE_MODE_NOW=1", out)


class InstalledIdsTests(SimpleTestCase):
    def test_matches_loader_rules(self):
        import ext

        root = Path(tempfile.mkdtemp())
        for n in ("good_one", "Bad", "x"):
            (root / n).mkdir()
            (root / n / "apps.py").write_text("")
        (root / "noapps").mkdir()
        self.assertEqual(extpreflight.installed_ids(root), [m.removeprefix("ext.") for m in ext.discover(root=root)])


@override_settings(EXT_PREFLIGHT_FILE=str(Path(tempfile.gettempdir()) / "ext-preflight-test.json"))
class MarkerAndCardTests(TestCase):
    def setUp(self):
        self.addCleanup(lambda: extpreflight.marker_path().unlink(missing_ok=True))

    def test_no_marker_no_card(self):
        self.assertEqual(admin_cards.ext_state(), [])

    def test_marker_roundtrip_and_card(self):
        extpreflight.write_marker(extpreflight.Result(ids=["bad"], disabled={"bad": "بارگذاری: ImportError"}))
        self.assertEqual(extpreflight.read_marker()["disabled"], {"bad": "بارگذاری: ImportError"})
        items = admin_cards.ext_state()
        self.assertEqual(items[0]["level"], "bad")
        self.assertIn("«bad» در شروع کنار گذاشته شد", items[0]["text"])

    def test_safe_mode_card(self):
        extpreflight.write_marker(extpreflight.Result(ids=["a"], safe_mode=True, reason="تداخل"))
        self.assertIn("حالت امن", admin_cards.ext_state()[0]["text"])
        with override_settings(PLUGINS_SAFE_MODE=True):
            self.assertEqual(admin_cards.ext_state()[0]["level"], "warn")

    def test_manual_disable_card(self):
        with override_settings(PLUGINS_DISABLED="foo, bar"):
            self.assertIn("foo", admin_cards.ext_state()[0]["text"])

    def test_corrupt_marker_is_ignored(self):
        extpreflight.marker_path().write_text("{bad json")
        self.assertEqual(extpreflight.read_marker(), {})
        self.assertEqual(admin_cards.ext_state(), [])


class RealSubprocessTests(SimpleTestCase):
    """یک پلاگین سالم و یک پلاگین با خطای import واقعی در ext/ (موقت)؛ زیرپردازه‌ی واقعی manage.py check."""

    def _plugin(self, name, apps_extra=""):
        d = Path(settings.BASE_DIR) / "ext" / name
        self.addCleanup(shutil.rmtree, d, True)
        d.mkdir()
        (d / "__init__.py").write_text("")
        (d / "apps.py").write_text(textwrap.dedent(f'''
            from django.apps import AppConfig
            {apps_extra}
            class C(AppConfig):
                name = "ext.{name}"
                label = "x_{name}"
        '''))
        (d / "plugin.py").write_text(f'from kernel.plugins import register\nregister("{name}", "{name}", kind="custom", tier=3)\n')

    def test_real_bad_plugin_is_quarantined(self):
        self._plugin("pf_good")
        self._plugin("pf_bad", apps_extra="raise RuntimeError('boom')")
        res = extpreflight.run(["pf_good", "pf_bad"])
        self.assertEqual(list(res.disabled), ["pf_bad"], res.disabled)
        self.assertFalse(res.safe_mode, res.reason)
