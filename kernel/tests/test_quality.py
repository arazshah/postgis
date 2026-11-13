"""امتیاز و فهرست کیفیت (ADR-0010 مرحله‌ی ۷): بررسی‌های قطعی، راه‌حل خودکار و امتیاز."""
import copy
import json

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from kernel import blueprint, quality
from kernel.models import PluginDraft

PID = "fleet"
TABLE = {"name": "fleet_pts", "columns": [
    {"name": "device", "type": "text", "label": "دستگاه"}, {"name": "lat", "type": "double", "label": "عرض"},
    {"name": "lon", "type": "double", "label": "طول"}, {"name": "at", "type": "timestamptz", "auto_now": True}]}
CASE = {"name": "عادی", "sql": [{"match": "select", "columns": ["v"], "rows": [[1.0]]}], "expect": {"rows_count": 1}}
CASE2 = {"name": "خالی", "sql": [{"match": "select", "columns": ["v"], "rows": []}], "expect": {"rows_count": 1}}


def base(**intro):
    return {"intro": {"summary": "پایش ناوگان", **intro}, "tables": [copy.deepcopy(TABLE)], "pages": [], "code": {}, "access": {"mode": "public_free"}}


def good():
    s = blueprint.apply(base(), PID, {"op": "page.add", "title": "پایش", "subtitle": "آخرین موقعیت", "refresh": 15, "blocks": [
        {"kind": "kpi", "title": "تعداد", "table": "fleet_pts"},
        {"kind": "map", "title": "نقشه", "table": "fleet_pts", "lat": "lat", "lon": "lon"},
        {"kind": "table", "title": "آخرین‌ها", "table": "fleet_pts", "limit": 20}]})
    return s


def by(q, cid):
    return next(c for c in q["checks"] if c["id"] == cid)


class ScoreTests(SimpleTestCase):
    def test_clean_plugin_scores_full(self):
        q = quality.evaluate(good(), PID)
        self.assertEqual((q["score"], q["grade"], q["publishable"]), (100, "آماده‌ی فروش", True))
        self.assertTrue(all(c["ok"] for c in q["checks"]))
        self.assertEqual(sum(g["ok"] for g in q["groups"]), sum(g["total"] for g in q["groups"]))

    def test_blocker_makes_unpublishable(self):
        q = quality.evaluate(base(), PID)  # بدون صفحه
        self.assertFalse(q["publishable"])
        self.assertFalse(by(q, "valid")["ok"])
        self.assertEqual(q["counts"]["block"], 1)
        self.assertLessEqual(q["score"], 70)
        self.assertEqual(q["grade"], "نیازمند کار")

    def test_penalties_and_grades(self):
        s = good()
        s["intro"]["summary"] = ""
        s["access"] = {}
        q = quality.evaluate(s, PID)
        self.assertEqual((q["counts"]["warn"], q["score"]), (2, 100 - 2 * quality.PENALTY["warn"]))
        self.assertEqual(q["grade"], "آماده‌ی فروش" if q["score"] >= 90 else "نزدیک به آماده")

    def test_score_never_negative(self):
        s = blueprint.apply(base(), PID, {"op": "page.add", "title": "ص", "blocks": [{"kind": "kpi"}] * 5})
        s["intro"]["summary"] = ""
        self.assertGreaterEqual(quality.evaluate(s, PID)["score"], 0)


class CheckTests(SimpleTestCase):
    def test_labels_titles_subtitle(self):
        s = good()
        s["tables"][0]["columns"][0]["label"] = ""
        s["pages"][0]["blocks"][0]["title"] = ""
        s["pages"][0]["subtitle"] = ""
        q = quality.evaluate(s, PID)
        self.assertFalse(by(q, "labels")["ok"])
        self.assertIn("device", by(q, "labels")["message"])
        self.assertEqual(by(q, "titles")["where"]["block"], s["pages"][0]["blocks"][0]["id"])
        self.assertEqual(by(q, "subtitle")["severity"], "info")
        s["tables"][0]["columns"][0]["label"] = "دستگاه"
        self.assertTrue(by(quality.evaluate(s, PID), "labels")["ok"])  # ستون زمان خودکار (at) برچسب نمی‌خواهد

    def test_form_without_list(self):
        s = good()
        s["pages"][0]["blocks"] = [b for b in s["pages"][0]["blocks"] if b["kind"] != "table"]
        s = blueprint.apply(s, PID, {"op": "block.add", "page": "p1", "block": {"kind": "form", "title": "ثبت", "table": "fleet_pts"}})
        c = by(quality.evaluate(s, PID), "form_list")
        self.assertFalse(c["ok"])
        s = blueprint.apply(s, PID, {"op": "block.add", "page": "p1", "block": {"kind": "records", "title": "ویرایش", "table": "fleet_pts"}})
        self.assertTrue(by(quality.evaluate(s, PID), "form_list")["ok"])

    def test_live_refresh_fix_ops_resolve_it(self):
        s = good()
        s["pages"][0]["refresh"] = 0
        s = blueprint.apply(s, PID, {"op": "block.add", "page": "p1", "block": {"kind": "ingest", "title": "دستگاه", "table": "fleet_pts"}})
        c = by(quality.evaluate(s, PID), "live_refresh")
        self.assertFalse(c["ok"])
        self.assertEqual(c["fix_ops"], [{"op": "page.set", "key": "p1", "refresh": 15}])
        fixed = blueprint.apply_all(s, PID, c["fix_ops"])
        self.assertTrue(by(quality.evaluate(fixed, PID), "live_refresh")["ok"])

    def test_table_limit_and_write_need_fixes(self):
        s = good()
        s["pages"][0]["blocks"][2].pop("limit")
        s = blueprint.apply(s, PID, {"op": "block.add", "page": "p1", "block": {"kind": "form", "table": "fleet_pts", "title": "ثبت"}})
        s["pages"][0]["need"] = "viewer"
        q = quality.evaluate(s, PID)
        for cid in ("table_limit", "write_need"):
            self.assertFalse(by(q, cid)["ok"])
            s = blueprint.apply_all(s, PID, by(q, cid)["fix_ops"])
        q2 = quality.evaluate(s, PID)
        self.assertTrue(by(q2, "table_limit")["ok"] and by(q2, "write_need")["ok"])

    def test_many_blocks_and_unused_params(self):
        s = good()
        s["pages"][0]["blocks"] += [{"id": f"bx{i:04d}", "kind": "text", "text": "x"} for i in range(9)]
        s = blueprint.apply(s, PID, {"op": "page.set", "key": "p1", "params": [{"name": "hours", "kind": "choice", "label": "بازه", "default": "60", "choices": [["60", "یک ساعت"]]}]})
        q = quality.evaluate(s, PID)
        self.assertFalse(by(q, "many_blocks")["ok"])
        self.assertFalse(by(q, "params_used")["ok"])
        s["pages"][0]["blocks"][0].update(since_col="at", since_param="hours")
        self.assertTrue(by(quality.evaluate(s, PID), "params_used")["ok"])

    def test_code_checks(self):
        s = good()
        s["code"]["stats"] = {"role": "block", "source": "def handle(ctx, params):\n    return {'columns': [], 'rows': []}\n", "tables": ["fleet_pts"],
                              "cases": [CASE], "test": '[[cases]]\nname = "a"\n[cases.expect]\nrows_count = 1\n'}
        q = quality.evaluate(s, PID)
        self.assertFalse(by(q, "code_cases")["ok"])  # یک مورد
        self.assertFalse(by(q, "code_wired")["ok"])  # به صفحه وصل نیست
        s = blueprint.apply(s, PID, {"op": "code.set", "name": "stats", "cases": [CASE, CASE2]})
        s = blueprint.apply(s, PID, {"op": "block.add", "page": "p1", "block": {"kind": "handler", "handler": "stats", "display": "table", "title": "آمار"}})
        q = quality.evaluate(s, PID)
        self.assertTrue(by(q, "code_cases")["ok"] and by(q, "code_wired")["ok"])

    def test_market_and_safety_infos(self):
        s = good()
        s["access"] = {"mode": "public_paid", "price_toman": 1000, "trial_days": 0}
        s = blueprint.apply(s, PID, {"op": "block.add", "page": "p1", "block": {"kind": "sql", "display": "table", "sql": "select 1 as n", "title": "x"}})
        q = quality.evaluate(s, PID)
        self.assertFalse(by(q, "trial")["ok"])
        self.assertFalse(by(q, "raw_sql")["ok"])
        s["access"]["trial_days"] = 7
        self.assertTrue(by(quality.evaluate(s, PID), "trial")["ok"])
        s["access"] = {}
        self.assertFalse(by(quality.evaluate(s, PID), "access")["ok"])

    def test_every_check_has_group_and_where_shape(self):
        q = quality.evaluate(base(), PID)
        groups = {g[0] for g in quality.GROUPS}
        ids = [c["id"] for c in q["checks"]]
        self.assertEqual(len(ids), len(set(ids)))
        for c in q["checks"]:
            self.assertIn(c["group"], groups)
            self.assertIn(c["severity"], quality.PENALTY)
            self.assertIsInstance(c["where"], dict)
            self.assertEqual(c["message"] == "", c["ok"])


@override_settings(ADMIN_2FA_REQUIRED=False)
class ApiTests(TestCase):
    def test_state_carries_quality_and_updates_after_fix(self):
        su = get_user_model().objects.create_superuser("qroot", "Str0ng-Admin-Pass")
        self.client.force_login(su)
        s = good()
        s["pages"][0]["refresh"] = 0
        s = blueprint.apply(s, PID, {"op": "block.add", "page": "p1", "block": {"kind": "ingest", "title": "دستگاه", "table": "fleet_pts"}})
        d = PluginDraft.objects.create(plugin_id=PID, name="ناوگان", wizard=s)
        st = self.client.get(reverse("admin:kernel_plugindraft_api_state", args=[d.pk])).json()
        c = next(x for x in st["quality"]["checks"] if x["id"] == "live_refresh")
        self.assertFalse(c["ok"])
        r = self.client.post(reverse("admin:kernel_plugindraft_api_op", args=[d.pk]), json.dumps({"ops": c["fix_ops"]}), content_type="application/json").json()
        self.assertTrue(next(x for x in r["quality"]["checks"] if x["id"] == "live_refresh")["ok"])
        self.assertGreater(r["quality"]["score"], st["quality"]["score"])
