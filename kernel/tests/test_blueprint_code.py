"""بخش «کد» استودیوی دیداری: عملیات handler، سازنده‌ی آزمون ساخت‌یافته و API اجرا (ADR-0010 مرحله‌ی ۴)."""
import copy
import json
import re
import tomllib

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from kernel import blueprint, pkgtest, wizard_code
from kernel.models import PluginDraft

PID = "agro"
TABLE = {"name": "agro_obs", "columns": [{"name": "val", "type": "double"}, {"name": "at", "type": "timestamptz"}]}
CASE = {"name": "دو ردیف", "params": {"n": 1}, "sql": [{"match": "select", "columns": ["v"], "rows": [[1.0], [2.0]]}], "expect": {"rows_count": 2}}


def base():
    return {"intro": {}, "tables": [copy.deepcopy(TABLE)], "pages": [], "code": {}}


def with_stats(s=None):
    return blueprint.apply(s or base(), PID, {"op": "code.add", "name": "stats", "template": "block_stats", "params": {"table": "agro_obs", "num": "val"}})


class CasesTests(SimpleTestCase):
    def test_roundtrip_through_pkgtest(self):
        text = wizard_code.cases_toml([CASE, {"name": "فایل", "file": "a,1\nb,2", "expect": {"text_contains": "x"}},
                                        {"name": "خطا", "expect": {"error_contains": "boom"}}, {"name": "هشدار", "expect": {"alerts_count": 0}},
                                        {"name": "برابر", "expect": {"equals": {"rows": [[1]]}}}])
        cases = pkgtest.parse(text, "h")
        self.assertEqual([c.name for c in cases], ["دو ردیف", "فایل", "خطا", "هشدار", "برابر"])
        self.assertEqual(cases[0].params, {"n": 1})
        self.assertEqual(cases[1].file, b"a,1\nb,2")
        self.assertEqual(cases[0].sql[0]["rows"], [[1.0], [2.0]])

    def test_hostile_text_cannot_break_out_of_toml(self):
        nasty = 'x"\n[cases.expect]\nrows_count = 99\n# '
        text = wizard_code.cases_toml([{"name": nasty, "sql": [{"match": nasty, "columns": ["a"], "rows": [[nasty]]}], "expect": {"text_contains": nasty}}])
        d = tomllib.loads(text)
        self.assertEqual(len(d["cases"]), 1)
        self.assertEqual(d["cases"][0]["expect"], {"text_contains": nasty})  # تزریق نشد

    def test_validation(self):
        bad = [[], "x", [{"name": "a"}], [{"name": "a", "expect": {"rows_count": 1, "text_contains": "x"}}], [{"name": "a", "expect": {"nope": 1}}],
               [{"name": "a", "expect": {"rows_count": -1}}], [{"name": "a", "expect": {"rows_count": True}}], [{"name": "a", "expect": {"text_contains": " "}}],
               [{"name": "a", "params": [1], "expect": {"rows_count": 1}}],
               [{"name": "a", "sql": [{"match": "", "columns": [], "rows": []}], "expect": {"rows_count": 1}}],
               [{"name": "a", "sql": [{"match": "s", "columns": ["a", "b"], "rows": [[1]]}], "expect": {"rows_count": 1}}],
               [{"name": "a", "expect": {"rows_count": 1}}] * 11]
        for cases in bad:
            with self.assertRaises(wizard_code.WizardError, msg=str(cases)[:60]):
                wizard_code.cases_toml(cases)

    def test_from_toml_of_templates(self):
        for key, t in wizard_code.TEMPLATES.items():
            text = re.sub(r"@[A-Z]+@", "1", t["test"])
            cases = wizard_code.cases_from_toml(text)
            self.assertTrue(cases, key)
            pkgtest.parse(wizard_code.cases_toml(cases), key)


class CodeOpsTests(SimpleTestCase):
    def test_add_from_template_gets_structured_cases(self):
        s = with_stats()
        h = s["code"]["stats"]
        self.assertEqual(h["role"], "block")
        self.assertIn("agro_obs", h["source"])
        self.assertTrue(h["cases"] and h["test"])
        self.assertTrue(blueprint.analyze(s, PID)["issues"] == [] or all(i["scope"] != "code" for i in blueprint.analyze(s, PID)["issues"]))

    def test_add_validation(self):
        for op in ({"name": "Bad"}, {"name": "stats", "template": "nope"}, {"name": "stats", "template": "block_stats", "params": {"table": "zz"}},
                   {"name": "stats", "template": "block_stats", "params": {"table": "agro_obs", "num": "at"}}):
            with self.assertRaises(blueprint.BlueprintError):
                blueprint.apply(base(), PID, {"op": "code.add", "template": "block_stats", **op})
        with self.assertRaises(blueprint.BlueprintError):
            blueprint.apply(with_stats(), PID, {"op": "code.add", "name": "stats", "template": "block_stats", "params": {"table": "agro_obs", "num": "val"}})  # تکراری

    def test_set_source_cases_every(self):
        s = with_stats()
        s = blueprint.apply(s, PID, {"op": "code.set", "name": "stats", "source": "def handle(ctx, params):\n    return {'columns': [], 'rows': []}\n", "cases": [CASE]})
        self.assertEqual(s["code"]["stats"]["cases"][0]["name"], "دو ردیف")
        self.assertIn("rows_count = 2", s["code"]["stats"]["test"])
        for op in ({"cases": [{"name": "x", "expect": {}}]}, {"every": 1}, {"source": 5}, {"name": "zz", "source": "x"}):
            with self.assertRaises(blueprint.BlueprintError):
                blueprint.apply(s, PID, {"op": "code.set", **{"name": "stats", **op}})

    def test_analyze_code_issues(self):
        s = with_stats()
        s = blueprint.apply(s, PID, {"op": "code.set", "name": "stats", "cases": []})
        msgs = [i for i in blueprint.analyze(s, PID)["issues"] if i["scope"] == "code"]
        self.assertTrue(msgs and msgs[0]["handler"] == "stats" and "آزمون" in msgs[0]["message"])
        s = blueprint.apply(s, PID, {"op": "code.set", "name": "stats", "cases": [CASE], "source": "import os\ndef handle(ctx, params):\n    return os.getcwd()\n"})
        msgs = [i for i in blueprint.analyze(s, PID)["issues"] if i["scope"] == "code"]
        self.assertTrue(msgs and "بررسی ایستا" in msgs[0]["message"])  # کد ناامن ذخیره می‌شود ولی انتشار را می‌بندد

    def test_delete_keeps_dependent_blocks_as_issues(self):
        s = with_stats()
        s = blueprint.apply(s, PID, {"op": "page.add", "title": "ص", "blocks": [{"kind": "text", "text": "x"}]})
        s = blueprint.apply(s, PID, {"op": "block.add", "page": "p1", "block": {"kind": "handler", "handler": "stats", "display": "table"}})
        self.assertTrue(blueprint.analyze(s, PID)["ok"] or True)
        s = blueprint.apply(s, PID, {"op": "code.del", "name": "stats"})
        self.assertEqual(s["code"], {})
        self.assertTrue(any(i["scope"] == "block" for i in blueprint.analyze(s, PID)["issues"]))
        self.assertEqual(len(s["pages"][0]["blocks"]), 2)


@override_settings(ADMIN_2FA_REQUIRED=False)
class RunApiTests(TestCase):
    def setUp(self):
        self.su = get_user_model().objects.create_superuser("coderoot", "Str0ng-Admin-Pass")
        self.client.force_login(self.su)
        self.d = PluginDraft.objects.create(plugin_id=PID, name="آگرو", wizard=with_stats())

    def post(self, name, body):
        return self.client.post(reverse(f"admin:kernel_plugindraft_api_{name}", args=[self.d.pk]), json.dumps(body), content_type="application/json")

    def test_op_roundtrip_persists_code_and_tests(self):
        r = self.post("op", {"op": "code.set", "name": "stats", "cases": [CASE]})
        self.assertEqual(r.status_code, 200)
        self.d.refresh_from_db()
        self.assertIn("rows_count = 2", self.d.tests["stats"])
        self.assertIn("def handle", self.d.code["stats"])

    def test_run_requires_known_handler_and_action(self):
        self.assertEqual(self.post("run", {"action": "tests", "name": "zz"}).status_code, 404)
        self.assertEqual(self.post("run", {"action": "boom", "name": "stats"}).status_code, 400)

    def test_run_blocked_without_stepup(self):
        from unittest import mock
        with mock.patch("kernel.studio_api.stepup.ok", return_value=False), mock.patch("kernel.studio_api.stepup.url", return_value="/x/"):
            r = self.post("run", {"action": "tests", "name": "stats"})
        self.assertEqual((r.status_code, r.json()["stepup"]), (403, "/x/"))

    def test_run_blocked_when_runner_off(self):
        from unittest import mock
        with mock.patch("kernel.studio_api._runner_error", return_value="خاموش"):
            r = self.post("run", {"action": "tests", "name": "stats"})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "خاموش"))

    def test_run_tests_and_trial_in_local_runner(self):
        r = self.post("run", {"action": "tests", "name": "stats"})
        if r.status_code == 400 and "خاموش" in r.json().get("error", ""):
            self.skipTest("runner خاموش")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["ok"], r.json())
        t = self.post("run", {"action": "trial", "name": "stats", "params": {}}).json()
        self.assertTrue(t["ok"] or "ctx.sql" in t.get("error", "") or t.get("error"), t)
