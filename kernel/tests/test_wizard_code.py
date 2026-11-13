"""کد سطح ۲ در ویزارد (ADR-0008 مرحله‌ی ۴): قالب‌های GIS، ساخت امن، آزمون در جعبه، انتشار با کد."""
import json
import tomllib
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from kernel import entitlements, handlers, pagekit, pkgtest, studio, studio_common, wizard, wizard_code
from kernel.models import PluginDraft, PluginRelease
from kernel.plugins import registry
from kernel.tests.test_publish import POINTS, cleanup_loaded

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
                results = studio_common.test_results(key, h)
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
class CodeApiTests(TestCase):
    """handler در استودیوی دیداری: ساخت از قالب، ویرایش، آزمون و اجرای آزمایشی در جعبه، انتشار (ADR-0010 مرحله‌ی ۴ و ۱۱)."""

    def setUp(self):
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(cleanup_loaded)
        self.su = get_user_model().objects.create_superuser("codroot", "Str0ng-Admin-Pass")
        self.client.force_login(self.su)
        self.client.post(reverse("admin:kernel_plugindraft_new"), {"name": "مانیتورینگ آنلاین", "plugin_id": "monitoring", "summary": "پایش", "icon": "pulse", "recipe": "blank"})
        self.draft = PluginDraft.objects.get(plugin_id="monitoring")
        self.api("op", {"op": "table.add", "table": POINTS})

    def api(self, name, body=None):
        url = reverse(f"admin:kernel_plugindraft_api_{name}", args=[self.draft.pk])
        return self.client.get(url) if body is None else self.client.post(url, json.dumps(body), content_type="application/json")

    def d(self):
        return PluginDraft.objects.get(pk=self.draft.pk)

    def add(self, template="block_stats", name="stats", **p):
        return self.api("op", {"op": "code.add", "template": template, "name": name, "params": {"table": "monitoring_points", "num": "speed", "lat": "lat", "lon": "lon", **p}})

    def page(self, *blocks):
        return self.api("op", {"op": "page.add", "title": "پایش", "icon": "pulse", "blocks": list(blocks) or [{"kind": "text", "text": "x"}]})

    def test_add_handler_syncs_code_tests_and_manifest_tier(self):
        self.assertEqual(self.add().status_code, 200)
        d = self.d()
        self.assertIn("def handle", d.code["stats"])
        self.assertIn("rows_count", d.tests["stats"])
        self.assertIn("tier = 2", studio.manifest_text(d))

    def test_invalid_name_duplicate_and_bad_params_rejected(self):
        self.assertEqual(self.add(name="Bad Name").status_code, 400)
        self.assertEqual(self.add(template="block_stats", name="xx", num="device").status_code, 400)  # عددی نیست
        self.assertEqual(self.d().wizard.get("code", {}), {})
        self.assertEqual(self.add().status_code, 200)
        self.assertEqual(self.add().status_code, 400)
        self.assertEqual(list(self.d().wizard["code"]), ["stats"])

    def test_bad_tests_are_rejected_and_unsafe_code_blocks_publish(self):
        self.add()
        good = self.d().wizard["code"]["stats"]
        r = self.api("op", {"op": "code.set", "name": "stats", "cases": [{"name": "x", "expect": {}}]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.d().wizard["code"]["stats"]["source"], good["source"])
        r = self.api("op", {"op": "code.set", "name": "stats", "source": "import os\ndef handle(c, p):\n    return {}\n"}).json()
        self.assertTrue(any(i["scope"] == "code" and "بررسی ایستا" in i["message"] for i in r["analysis"]["issues"]))
        self.assertFalse(r["quality"]["publishable"])
        new_src = good["source"] + "\n# edited\n"
        self.api("op", {"op": "code.set", "name": "stats", "source": new_src})
        self.assertIn("# edited", self.d().code["stats"])

    def test_alert_interval(self):
        self.add(template="alert_threshold", name="lowwater", threshold="50")
        self.assertEqual(self.d().alerts, {"lowwater": 60})
        self.assertEqual(self.api("op", {"op": "code.set", "name": "lowwater", "every": 15}).status_code, 200)
        self.assertEqual(self.d().alerts, {"lowwater": 15})
        self.assertEqual(self.api("op", {"op": "code.set", "name": "lowwater", "every": 1}).status_code, 400)  # ۱ مجاز نیست
        self.assertEqual(self.d().alerts, {"lowwater": 15})

    def test_tests_and_trial_run_in_the_sandbox(self):
        self.add()
        r = self.api("run", {"action": "tests", "name": "stats"}).json()
        self.assertTrue(r["ok"] and all(x["ok"] for x in r["results"]), r)
        self.add(template="importer_csv_points", name="csvpts")
        r = self.api("run", {"action": "trial", "name": "csvpts", "params": {}, "file_text": "name,lat,lon\nA,35.7,51.4\nB,36,52\n"}).json()
        self.assertTrue(r["ok"] and "ورود معتبر است: 2 ردیف" in r["verdict"], r)
        self.assertEqual(self.api("run", {"action": "trial", "name": "csvpts", "params": [1]}).status_code, 400)
        r = self.api("run", {"action": "trial", "name": "csvpts", "params": {}, "file_text": "h\nA,x,1\n"}).json()
        self.assertFalse(r["ok"])
        self.assertTrue(r["error"])

    def test_runner_off_blocks_tests_trial_and_publish(self):
        self.add()
        self.page({"kind": "handler", "title": "آمار", "handler": "stats", "display": "table"})
        self.api("access", {"access": {"mode": "public_free"}})
        with mock.patch("kernel.runner.client.mode", return_value="off"):
            r = self.api("run", {"action": "tests", "name": "stats"})
            self.assertEqual((r.status_code, "خاموش" in r.json()["error"]), (400, True))
            r = self.api("publish", {})
            self.assertEqual(r.status_code, 400)
            self.assertIn("خاموش است", r.json()["error"])
        self.assertFalse(PluginRelease.objects.exists())

    def test_delete_handler_keeps_dependent_blocks_as_issues(self):
        self.add()
        self.add(template="ingest_csv_lines", name="lines")
        self.page({"kind": "handler", "handler": "stats", "display": "table"}, {"kind": "text", "text": "x"},
                  {"kind": "ingest", "table": "monitoring_points", "fields": ["device", "lat", "lon"], "handler": "lines"})
        self.assertEqual(len(self.d().wizard["pages"][0]["blocks"]), 3)
        self.api("op", {"op": "code.del", "name": "stats"})
        r = self.api("op", {"op": "code.del", "name": "lines"}).json()
        self.assertEqual(len(r["spec"]["pages"][0]["blocks"]), 3)  # حذف نمی‌شوند
        self.assertEqual(sum(1 for i in r["analysis"]["issues"] if i["scope"] == "block"), 2)  # ایراد می‌گیرند
        self.assertEqual(self.d().code, {})

    def test_page_blocks_need_existing_handlers_of_the_right_role(self):
        self.add()
        self.page({"kind": "text", "text": "x"})
        for bad in ({"kind": "handler", "handler": "missing", "display": "table"}, {"kind": "import", "handler": "stats"},
                    {"kind": "export", "handler": "stats"}, {"kind": "handler", "handler": "stats", "display": "xxx"}):
            r = self.api("op", {"op": "block.add", "page": "p1", "block": bad}).json()
            bid = r["spec"]["pages"][0]["blocks"][-1]["id"]
            self.assertTrue(any(i["block"] == bid for i in r["analysis"]["issues"]), bad)
            self.api("op", {"op": "block.del", "id": bid})

    def test_publish_with_code_end_to_end_and_handler_runs(self):
        self.add(template="block_ndvi_classes", name="ndvi", nir="speed", red="lat")
        self.page({"kind": "handler", "title": "NDVI", "handler": "ndvi", "display": "bars"})
        self.api("access", {"access": {"mode": "public_free"}})
        r = self.api("publish", {}).json()
        self.assertTrue(r["active"], r)
        rel = PluginRelease.objects.get(plugin_id="monitoring")
        self.assertEqual(rel.status, "active")
        self.assertEqual(rel.manifest["tier"], 2)
        self.assertEqual(rel.manifest["contributes"]["handlers"], ["ndvi"])
        self.assertIn("def handle", handlers.get("monitoring", "ndvi"))
        from kernel.runner import client

        out = client.run_files(handlers.files_for("monitoring", "ndvi"), "ndvi", {}, None, 0, allow_no_ws=True,
                               mock_sql=[{"match": "select", "columns": ["a", "b"], "rows": [[0.5, 0.1]]}], plugin="t")
        self.assertEqual(dict(out["rows"])["پوشش انبوه"], 1)

    def test_live_preview_of_handler_block_uses_temporary_handlers_and_cleans_up(self):
        self.add()
        self.page({"kind": "handler", "title": "آمار", "handler": "stats", "display": "table"})
        seen = {}

        def fake_preview(d, key, ws, q):
            seen["src"] = handlers.get(d.plugin_id, "stats")
            return {"page": None, "blocks": [], "values": {}, "layers": {}, "param_errors": [], "has_map": False}

        with mock.patch("kernel.workspace.peek", return_value=mock.Mock(is_live=True, pk=9, db_name="gp_x")), mock.patch("kernel.studio.preview_page", fake_preview), \
                mock.patch("kernel.workspace.log_event"):
            r = self.api("preview_live", {"page": "p1", "database": "9"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("def handle", seen["src"])
        self.assertIsNone(handlers.get("monitoring", "stats"))  # بعد از پیش‌نمایش پاک شد
        self.assertNotIn("monitoring", registry.plugins)
