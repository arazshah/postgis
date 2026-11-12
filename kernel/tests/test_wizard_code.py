"""کد سطح ۲ در ویزارد (ADR-0008 مرحله‌ی ۴): قالب‌های GIS، ساخت امن، آزمون در جعبه، انتشار با کد."""
import tomllib
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from kernel import entitlements, handlers, pagekit, pkgtest, studio, wizard, wizard_admin, wizard_code
from kernel.models import PluginDraft, PluginRelease
from kernel.plugins import registry
from kernel.tests.test_publish import cleanup_loaded
from kernel.tests.test_wizard_admin import TBL

TABLE = {"name": "agro_pixels", "columns": [
    {"name": "nir", "type": "double"}, {"name": "red", "type": "double"}, {"name": "lat", "type": "double", "required": True},
    {"name": "lon", "type": "double", "required": True}, {"name": "level", "type": "double"}, {"name": "tmin", "type": "double"},
    {"name": "tmax", "type": "double"}, {"name": "day", "type": "date"}, {"name": "label", "type": "text"}]}
PARAMS = {"table": "agro_pixels", "num": "level", "nir": "nir", "red": "red", "lat": "lat", "lon": "lon", "time": "day",
          "tmin": "tmin", "tmax": "tmax", "latv": "35.7", "threshold": "100"}


def spec():
    return {"tables": [TABLE], "pages": [], "code": {}}


class TemplateTests(SimpleTestCase):
    def test_every_template_builds_scans_and_passes_its_own_tests_in_the_sandbox(self):
        for key in wizard_code.TEMPLATES:
            with self.subTest(template=key):
                h = wizard_code.build(spec(), key, PARAMS)
                self.assertNotRegex(h["source"] + h["test"], r"@[A-Z]+@")  # جانشین باقی نمانده
                wizard_code.check_source(h["source"], key)
                cases = pkgtest.parse(h["test"], key)
                self.assertTrue(cases)
                results = wizard_admin._test_results(key, h)
                self.assertTrue(all(r["ok"] for r in results), results)

    def test_roles_and_alert_defaults(self):
        self.assertEqual(wizard_code.build(spec(), "alert_threshold", PARAMS)["every"], 60)
        self.assertEqual(wizard_code.build(spec(), "importer_csv_points", {})["role"], "importer")
        self.assertEqual(wizard_code.build(spec(), "block_stats", PARAMS)["tables"], ["agro_pixels"])
        self.assertEqual(wizard_code.build(spec(), "ingest_csv_lines", {})["tables"], [])

    def test_substitution_only_with_validated_names_and_numbers(self):
        bad = [{**PARAMS, "table": "nope"}, {**PARAMS, "num": "label"}, {**PARAMS, "num": 'level"; drop table x; --'},
               {**PARAMS, "num": "missing"}, {**PARAMS, "latv": "abc"}, {**PARAMS, "latv": "99"}, {**PARAMS, "latv": "nan"}]
        for p in bad:
            with self.subTest(p=str(p)[:50]), self.assertRaises(wizard.WizardError):
                wizard_code.build(spec(), "block_et0_gdd" if "latv" in str(p) and p.get("latv") != "35.7" else "block_stats", p)
        with self.assertRaises(wizard.WizardError):
            wizard_code.build(spec(), "alert_threshold", {**PARAMS, "threshold": "x"})
        with self.assertRaises(wizard.WizardError):
            wizard_code.build(spec(), "nope", PARAMS)
        s = spec()
        s["tables"][0]["columns"][4]["name"] = 'lev"el'
        with self.assertRaises(wizard.WizardError):
            wizard_code.build(s, "block_stats", {**PARAMS, "num": 'lev"el'})

    def test_check_source_blocks_unsafe_code(self):
        for src in ("import os\n", "import subprocess\n", "x = open('f')\n", "from math import __builtins__\n", "def f(:\n", "x=1\n" * 30000):
            with self.subTest(src=src[:20]), self.assertRaises(wizard.WizardError):
                wizard_code.check_source(src)
        wizard_code.check_source("import geo\nimport math\n\ndef handle(ctx, params):\n    return geo.haversine_km(0, 0, 0, 1) + math.pi\n")

    def test_validate_code_rules(self):
        s = spec()
        s["code"] = {"ok_one": {"role": "block", "source": "def handle(ctx, params):\n    return {}\n"}}
        wizard_code.validate_code(s)
        for bad in ({"Bad Name": {"role": "block", "source": "x=1"}}, {"ok_one": {"role": "weird", "source": "x=1"}},
                    {"ok_one": {"role": "alert", "source": "x=1", "every": 1}}, {"ok_one": {"role": "alert", "source": "x=1"}},
                    {f"h{i}x": {"role": "block", "source": "x=1"} for i in range(9)}):
            with self.subTest(bad=list(bad)[0]), self.assertRaises(wizard.WizardError):
                wizard_code.validate_code({"code": bad})


class CompileWithCodeTests(SimpleTestCase):
    def full(self):
        s = spec()
        for name, key in (("ndvi", "block_ndvi_classes"), ("csvpts", "importer_csv_points"), ("geoexp", "exporter_geojson"), ("lines", "ingest_csv_lines")):
            s["code"][name] = wizard_code.build(s, key, PARAMS)
        s["pages"] = [{"key": "p1", "title": "کشاورزی", "icon": "pulse", "need": "viewer", "blocks": [
            {"kind": "handler", "title": "طبقه‌های NDVI", "handler": "ndvi", "display": "bars"},
            {"kind": "import", "title": "ورود نقطه‌ها", "handler": "csvpts", "extensions": ".csv, geojson"},
            {"kind": "export", "title": "خروجی", "handler": "geoexp", "format": "geojson"},
            {"kind": "ingest", "title": "دریافت", "table": "agro_pixels", "fields": ["lat", "lon"], "handler": "lines"}]}]
        return s

    def test_compiles_handler_import_export_and_ingest_handler(self):
        page = pagekit.parse_page("agro", tomllib.loads(wizard.compile_pages("agro", self.full())["p1"]))
        self.assertEqual([b.handler for b in page.blocks], ["ndvi"])
        self.assertEqual((page.blocks[0].kind, page.imports[0].handler, page.imports[0].extensions, page.exports[0].format, page.ingests[0].handler),
                         ("bars", "csvpts", (".csv", ".geojson"), "geojson", "lines"))
        self.assertEqual(page.need, "editor")  # ورود/دریافت نوشتن است
        self.assertEqual([t.name for t in page.tables], ["agro_pixels"])  # جدولی که کد می‌خواند ساخته شود

    def test_handler_role_and_existence_are_checked(self):
        for mutate in (lambda s: s["pages"][0]["blocks"][0].update(handler="csvpts"), lambda s: s["pages"][0]["blocks"][0].update(handler="nope"),
                       lambda s: s["pages"][0]["blocks"][1].update(handler="ndvi"), lambda s: s["pages"][0]["blocks"][2].update(handler="lines"),
                       lambda s: s["pages"][0]["blocks"][3].update(handler="geoexp"), lambda s: s["pages"][0]["blocks"][1].update(extensions="exe!"),
                       lambda s: s["pages"][0]["blocks"][0].update(display="map3d")):
            s = self.full()
            mutate(s)
            with self.assertRaises(wizard.WizardError):
                wizard.compile_pages("agro", s)


@override_settings(ADMIN_2FA_REQUIRED=False)
class CodeStepTests(TestCase):
    def setUp(self):
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(cleanup_loaded)
        self.su = get_user_model().objects.create_superuser("codroot", "Str0ng-Admin-Pass")
        self.client.force_login(self.su)
        self.client.post(reverse("admin:kernel_plugindraft_wizard_new"), {
            "name": "مانیتورینگ آنلاین", "plugin_id": "monitoring", "summary": "پایش", "description": "", "icon": "pulse"})
        self.draft = PluginDraft.objects.get(plugin_id="monitoring")
        self.step = lambda n: reverse("admin:kernel_plugindraft_wizard", args=[self.draft.pk, n])
        self.client.post(self.step(2), TBL)

    def d(self):
        return PluginDraft.objects.get(pk=self.draft.pk)

    def add(self, template="block_stats", name="stats", **p):
        return self.client.post(self.step(3), {"op": "addhandler", "template": template, "name": name, "table": "monitoring_points", "num": "speed",
                                               "lat": "lat", "lon": "lon", **p})

    def test_add_handler_syncs_code_tests_and_manifest_tier(self):
        self.add()
        d = self.d()
        self.assertIn("def handle", d.code["stats"])
        self.assertIn("rows_count", d.tests["stats"])
        self.assertIn("tier = 2", studio.manifest_text(d))
        self.assertContains(self.client.get(self.step(3)), "stats")
        self.assertEqual(self.client.get(self.step(3)).status_code, 200)

    def test_invalid_name_duplicate_and_bad_params_rejected(self):
        self.add(name="Bad Name")
        self.add(template="block_stats", name="x", num="device")  # عددی نیست
        self.assertEqual(self.d().wizard.get("code", {}), {})
        self.add()
        self.add()
        self.assertEqual(list(self.d().wizard["code"]), ["stats"])

    def test_save_rejects_unsafe_code_and_bad_tests_and_keeps_old(self):
        self.add()
        good = self.d().wizard["code"]["stats"]
        self.client.post(self.step(3), {"op": "savehandler:stats", "source": "import os\ndef handle(c, p):\n    return {}\n", "test": good["test"]})
        self.client.post(self.step(3), {"op": "savehandler:stats", "source": good["source"], "test": "[[cases]]\nname = 'x'\n"})  # expect خالی
        self.assertEqual(self.d().wizard["code"]["stats"]["source"], good["source"])
        new_src = good["source"].replace("آمار", "آمار")  # تغییر بی‌اثر ولی معتبر
        self.client.post(self.step(3), {"op": "savehandler:stats", "source": new_src + "\n# edited\n", "test": good["test"]})
        self.assertIn("# edited", self.d().code["stats"])

    def test_alert_interval(self):
        self.add(template="alert_threshold", name="lowwater", threshold="50")
        self.assertEqual(self.d().alerts, {"lowwater": 60})
        h = self.d().wizard["code"]["lowwater"]
        self.client.post(self.step(3), {"op": "savehandler:lowwater", "source": h["source"], "test": h["test"], "every": "15"})
        self.assertEqual(self.d().alerts, {"lowwater": 15})
        self.client.post(self.step(3), {"op": "savehandler:lowwater", "source": h["source"], "test": h["test"], "every": "1"})
        self.assertEqual(self.d().alerts, {"lowwater": 15})  # ۱ مجاز نیست

    def test_tests_and_trial_run_in_the_sandbox(self):
        self.add()
        r = self.client.post(self.step(3), {"op": "tests:stats"})
        self.assertContains(r, "آزمون‌های «stats»")
        self.assertContains(r, "✓")
        self.add(template="importer_csv_points", name="csvpts")
        up = SimpleUploadedFile("a.csv", b"name,lat,lon\nA,35.7,51.4\nB,36,52\n")
        r = self.client.post(self.step(3), {"op": "trial:csvpts", "params": "{}", "file": up})
        self.assertContains(r, "ورود معتبر است: 2 ردیف")
        r = self.client.post(self.step(3), {"op": "trial:csvpts", "params": "[1]"})
        self.assertEqual(r.status_code, 302)
        bad = SimpleUploadedFile("b.csv", b"h\nA,x,1\n")
        r = self.client.post(self.step(3), {"op": "trial:csvpts", "params": "{}", "file": bad})
        self.assertContains(r, "ناموفق")

    def test_runner_off_blocks_tests_trial_and_publish(self):
        self.add()
        with mock.patch("kernel.runner.client.mode", return_value="off"):
            r = self.client.post(self.step(3), {"op": "tests:stats"})
            self.assertEqual(r.status_code, 302)
            self.assertContains(self.client.get(self.step(3)), "خاموش است")
            self.client.post(self.step(4), {"op": "addpage", "title": "پایش", "icon": "pulse"})
            self.client.post(self.step(4), {"op": "addblock:p1", "kind": "handler", "title": "آمار", "handler": "stats", "display": "table"})
            self.client.post(self.step(5), {"mode": "public_free"})
            self.assertContains(self.client.get(self.step(6)), "اجرای کد در این استقرار خاموش است")
            self.client.post(self.step(6), {"op": "publish"})
        self.assertFalse(PluginRelease.objects.exists())

    def test_delete_handler_removes_dependent_blocks_and_ingest_handler(self):
        self.add()
        self.add(template="ingest_csv_lines", name="lines")
        self.client.post(self.step(4), {"op": "addpage", "title": "پایش", "icon": "pulse"})
        self.client.post(self.step(4), {"op": "addblock:p1", "kind": "handler", "handler": "stats", "display": "table"})
        self.client.post(self.step(4), {"op": "addblock:p1", "kind": "text", "text": "x"})
        self.client.post(self.step(4), {"op": "addblock:p1", "kind": "ingest", "table": "monitoring_points", "fields": ["device", "lat", "lon"], "ingest_handler": "lines"})
        self.assertEqual(len(self.d().wizard["pages"][0]["blocks"]), 3)
        self.client.post(self.step(3), {"op": "delhandler:stats"})
        self.client.post(self.step(3), {"op": "delhandler:lines"})
        blocks = self.d().wizard["pages"][0]["blocks"]
        self.assertEqual([b["kind"] for b in blocks], ["text", "ingest"])
        self.assertNotIn("handler", blocks[1])
        self.assertEqual(self.d().code, {})

    def test_page_blocks_need_existing_handlers_of_the_right_role(self):
        self.add()
        self.client.post(self.step(4), {"op": "addpage", "title": "پایش", "icon": "pulse"})
        for bad in ({"kind": "handler", "handler": "missing", "display": "table"}, {"kind": "import", "import_handler": "stats"},
                    {"kind": "export", "export_handler": "stats"}, {"kind": "handler", "handler": "stats", "display": "xxx"}):
            self.client.post(self.step(4), {"op": "addblock:p1", **bad})
        self.assertEqual(self.d().wizard["pages"][0]["blocks"], [])
        r = self.client.get(self.step(4))
        self.assertContains(r, "stats")  # فهرست handler در فرم بلوک

    def test_publish_with_code_end_to_end_and_handler_runs(self):
        self.add(template="block_ndvi_classes", name="ndvi", nir="speed", red="lat")
        self.client.post(self.step(4), {"op": "addpage", "title": "پایش", "icon": "pulse"})
        self.client.post(self.step(4), {"op": "addblock:p1", "kind": "handler", "title": "NDVI", "handler": "ndvi", "display": "bars"})
        self.client.post(self.step(5), {"mode": "public_free"})
        r = self.client.post(self.step(6), {"op": "publish"})
        self.assertEqual(r.status_code, 302)
        rel = PluginRelease.objects.get(plugin_id="monitoring")
        self.assertEqual(rel.status, "active")
        self.assertEqual(rel.manifest["tier"], 2)
        self.assertEqual(rel.manifest["contributes"]["handlers"], ["ndvi"])
        self.assertIn("def handle", handlers.get("monitoring", "ndvi"))
        from kernel.runner import client

        out = client.run_files(handlers.files_for("monitoring", "ndvi"), "ndvi", {}, None, 0, allow_no_ws=True,
                               mock_sql=[{"match": "select", "columns": ["a", "b"], "rows": [[0.5, 0.1]]}], plugin="t")
        self.assertEqual(dict(out["rows"])["پوشش انبوه"], 1)

    def test_preview_of_handler_block_uses_temporary_handlers_and_cleans_up(self):
        self.add()
        self.client.post(self.step(4), {"op": "addpage", "title": "پایش", "icon": "pulse"})
        self.client.post(self.step(4), {"op": "addblock:p1", "kind": "handler", "title": "آمار", "handler": "stats", "display": "table"})
        seen = {}

        def fake_preview(d, key, ws, q):
            seen["src"] = handlers.get(d.plugin_id, "stats")
            return {"page": None, "blocks": [], "values": {}, "layers": {}, "param_errors": [], "has_map": False}

        with mock.patch("kernel.workspace.peek", return_value=mock.Mock(is_live=True, pk=9)), mock.patch("kernel.studio.preview_page", fake_preview), \
                mock.patch("kernel.workspace.log_event"):
            self.client.post(self.step(4), {"op": "preview:p1", "preview_db": "9"})
        self.assertIn("def handle", seen["src"])
        self.assertIsNone(handlers.get("monitoring", "stats"))  # بعد از پیش‌نمایش پاک شد
        self.assertNotIn("monitoring", registry.plugins)
