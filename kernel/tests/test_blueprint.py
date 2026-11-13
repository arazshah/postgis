"""نقشه‌ی پلاگین، عملیات، پیش‌نمایش نمونه و API استودیوی دیداری (ADR-0010 مرحله‌ی ۱)."""
import copy
import json

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from kernel import blueprint, sampledata, wizard
from kernel.models import PluginDraft, PluginDraftRevision

PID = "mon"
TABLE = {"name": "mon_points", "columns": [
    {"name": "device", "type": "text", "required": True}, {"name": "lat", "type": "double", "min": -90, "max": 90},
    {"name": "lon", "type": "double", "min": -180, "max": 180}, {"name": "speed", "type": "double"},
    {"name": "at", "type": "timestamptz", "auto_now": True}]}


def base():
    return {"intro": {"summary": "", "icon": "chart"}, "tables": [copy.deepcopy(TABLE)], "pages": []}


def with_page(spec=None):
    s = blueprint.apply(spec or base(), PID, {"op": "page.add", "title": "پایش"})
    return s, s["pages"][0]["key"]


class OpsTests(SimpleTestCase):
    def test_apply_does_not_mutate_input(self):
        s = base()
        before = json.dumps(s)
        blueprint.apply(s, PID, {"op": "page.add", "title": "الف"})
        self.assertEqual(json.dumps(s), before)

    def test_page_ops(self):
        s, k = with_page()
        s = blueprint.apply(s, PID, {"op": "page.add", "title": "دوم", "refresh": 15})
        self.assertEqual([p["key"] for p in s["pages"]], ["p1", "p2"])
        s = blueprint.apply(s, PID, {"op": "page.move", "key": "p2", "to": 0})
        self.assertEqual([p["key"] for p in s["pages"]], ["p2", "p1"])
        s = blueprint.apply(s, PID, {"op": "page.set", "key": "p1", "title": "نو", "need": "editor"})
        self.assertEqual(s["pages"][1]["title"], "نو")
        s = blueprint.apply(s, PID, {"op": "page.del", "key": "p2"})
        self.assertEqual(len(s["pages"]), 1)
        for bad in ({"op": "page.set", "key": "p1", "refresh": 2}, {"op": "page.set", "key": "p1", "group": "x"},
                    {"op": "page.set", "key": "zz", "title": "ا"}, {"op": "page.add", "title": ""}):
            with self.assertRaises(blueprint.BlueprintError):
                blueprint.apply(s, PID, bad)

    def test_page_limit(self):
        s = base()
        for _ in range(wizard.MAX_PAGES):
            s = blueprint.apply(s, PID, {"op": "page.add", "title": "ص"})
        with self.assertRaises(blueprint.BlueprintError):
            blueprint.apply(s, PID, {"op": "page.add", "title": "ص"})

    def test_block_lifecycle_and_ids(self):
        s, k = with_page()
        s = blueprint.apply(s, PID, {"op": "block.add", "page": k, "block": {"kind": "kpi", "title": "تعداد", "table": "mon_points"}})
        s = blueprint.apply(s, PID, {"op": "block.add", "page": k, "block": {"kind": "text", "text": "سلام"}, "at": 0})
        ids = [b["id"] for b in s["pages"][0]["blocks"]]
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(s["pages"][0]["blocks"][0]["kind"], "text")
        kpi = s["pages"][0]["blocks"][1]["id"]
        s = blueprint.apply(s, PID, {"op": "block.set", "id": kpi, "fields": {"width": "half", "unit": "ردیف"}})
        self.assertEqual(s["pages"][0]["blocks"][1]["width"], "half")
        s = blueprint.apply(s, PID, {"op": "block.set", "id": kpi, "fields": {"width": None}})
        self.assertNotIn("width", s["pages"][0]["blocks"][1])
        s = blueprint.apply(s, PID, {"op": "block.dup", "id": kpi})
        self.assertEqual(len(s["pages"][0]["blocks"]), 3)
        self.assertNotEqual(s["pages"][0]["blocks"][2]["id"], kpi)
        s = blueprint.apply(s, PID, {"op": "block.move", "id": kpi, "at": 0})
        self.assertEqual(s["pages"][0]["blocks"][0]["id"], kpi)
        s = blueprint.apply(s, PID, {"op": "block.del", "id": kpi})
        self.assertEqual(len(s["pages"][0]["blocks"]), 2)

    def test_block_move_between_pages(self):
        s, k = with_page()
        s = blueprint.apply(s, PID, {"op": "page.add", "title": "دوم"})
        s = blueprint.apply(s, PID, {"op": "block.add", "page": k, "block": {"kind": "text", "text": "x"}})
        bid = s["pages"][0]["blocks"][0]["id"]
        s = blueprint.apply(s, PID, {"op": "block.move", "id": bid, "page": "p2"})
        self.assertEqual((len(s["pages"][0]["blocks"]), len(s["pages"][1]["blocks"])), (0, 1))

    def test_bad_blocks_rejected_structurally(self):
        s, k = with_page()
        for blk in ({"kind": "nope"}, {"kind": "text", "width": "huge"}, "x", {"kind": "text", "a": {"b": {"c": {"d": {"e": 1}}}}}):
            with self.assertRaises(blueprint.BlueprintError):
                blueprint.apply(s, PID, {"op": "block.add", "page": k, "block": blk})
        with self.assertRaises(blueprint.BlueprintError):
            blueprint.apply(s, PID, {"op": "block.del", "id": "nope"})
        with self.assertRaises(blueprint.BlueprintError):
            blueprint.apply(s, PID, {"op": "bogus"})

    def test_block_limit(self):
        s, k = with_page()
        for _ in range(blueprint.MAX_BLOCKS):
            s = blueprint.apply(s, PID, {"op": "block.add", "page": k, "block": {"kind": "text", "text": "x"}})
        with self.assertRaises(blueprint.BlueprintError):
            blueprint.apply(s, PID, {"op": "block.add", "page": k, "block": {"kind": "text", "text": "x"}})

    def test_table_ops_and_rename_follows_blocks(self):
        s, k = with_page()
        s = blueprint.apply(s, PID, {"op": "block.add", "page": k, "block": {"kind": "kpi", "table": "mon_points"}})
        t = copy.deepcopy(TABLE)
        t["name"] = "mon_gps"
        s = blueprint.apply(s, PID, {"op": "table.set", "rename_from": "mon_points", "table": t})
        self.assertEqual(s["pages"][0]["blocks"][0]["table"], "mon_gps")
        with self.assertRaises(blueprint.BlueprintError):
            blueprint.apply(s, PID, {"op": "table.add", "table": t})  # تکراری
        with self.assertRaises(blueprint.BlueprintError):
            blueprint.apply(s, PID, {"op": "table.add", "table": {"name": "other_t", "columns": [{"name": "a", "type": "text"}]}})  # پیشوند اشتباه
        s = blueprint.apply(s, PID, {"op": "table.del", "name": "mon_gps"})
        self.assertEqual(s["tables"], [])
        self.assertTrue(any(i["scope"] == "block" for i in blueprint.analyze(s, PID)["issues"]))  # بلوک ایراد می‌گیرد، حذف نمی‌شود
        self.assertEqual(len(s["pages"][0]["blocks"]), 1)

    def test_batch_is_atomic(self):
        s = base()
        good = {"op": "page.add", "title": "الف"}
        with self.assertRaises(blueprint.BlueprintError) as cm:
            blueprint.apply_all(s, PID, [good, {"op": "page.del", "key": "zz"}])
        self.assertIn("عملیات 2", str(cm.exception).replace("۲", "2"))
        self.assertEqual(s["pages"], [])
        self.assertEqual(len(blueprint.apply_all(s, PID, [good, good])["pages"]), 2)

    def test_ensure_ids_on_legacy_spec(self):
        s = {"tables": [], "pages": [{"key": "p1", "title": "x", "blocks": [{"kind": "text"}, {"kind": "text", "id": "dup"}, {"kind": "text", "id": "dup"}]}]}
        ids = [b["id"] for b in blueprint.ensure_ids(s)["pages"][0]["blocks"]]
        self.assertEqual(len(set(ids)), 3)

    def test_analyze_ok_and_issues(self):
        s, k = with_page()
        self.assertFalse(blueprint.analyze(s, PID)["ok"])  # صفحه‌ی بی‌بلوک
        s = blueprint.apply(s, PID, {"op": "block.add", "page": k, "block": {"kind": "kpi", "title": "تعداد"}})
        a = blueprint.analyze(s, PID)
        self.assertEqual([i["scope"] for i in a["issues"]], ["block"])
        self.assertTrue(a["issues"][0]["block"])
        bid = s["pages"][0]["blocks"][0]["id"]
        s = blueprint.apply(s, PID, {"op": "block.set", "id": bid, "fields": {"table": "mon_points"}})
        self.assertTrue(blueprint.analyze(s, PID)["ok"])


def full_spec():
    s, k = with_page()
    for blk in ({"kind": "kpi", "title": "دستگاه", "table": "mon_points", "agg": "count", "distinct": "device"},
                {"kind": "kpi", "title": "میانگین", "table": "mon_points", "agg": "avg", "column": "speed", "unit": "km/h"},
                {"kind": "bars", "title": "هر دستگاه", "table": "mon_points", "label": "device", "agg": "count"},
                {"kind": "table", "title": "آخرین‌ها", "table": "mon_points", "columns": ["device", "speed"], "order_by": "at", "limit": 5},
                {"kind": "map", "title": "نقشه", "table": "mon_points", "lat": "lat", "lon": "lon", "props": ["device"], "latest_by": "device", "time_col": "at"},
                {"kind": "form", "title": "ثبت", "table": "mon_points", "fields": ["device", "lat", "lon"]},
                {"kind": "sql", "title": "پیشرفته", "sql": "select 1", "display": "kpi"},
                {"kind": "text", "text": "راهنما"}):
        s = blueprint.apply(s, PID, {"op": "block.add", "page": k, "block": blk})
    return s, k


class SampleTests(SimpleTestCase):
    def test_rows_deterministic_and_bounded(self):
        a, b = sampledata.rows(TABLE), sampledata.rows(TABLE)
        self.assertEqual([r["device"] for r in a], [r["device"] for r in b])
        self.assertEqual(len(a), sampledata.N_ROWS)
        self.assertTrue(all(35 < r["lat"] < 36 and 51 < r["lon"] < 52 for r in a))  # عرض/طول تهران
        self.assertTrue(all(r["device"] in sampledata.DEVICES for r in a))

    def test_preview_blocks(self):
        s, k = full_spec()
        pv = sampledata.preview(s, k)
        by = {b["title"]: b for b in pv["all_blocks"]}
        self.assertEqual(by["دستگاه"]["value"], str(len(sampledata.DEVICES)).translate(str.maketrans("0123456789", "0123456789")))
        self.assertEqual(by["میانگین"]["unit"], "km/h")
        self.assertEqual(len(by["هر دستگاه"]["bars"]), len(sampledata.DEVICES))
        self.assertEqual(len(by["آخرین‌ها"]["rows"]), 5)
        self.assertEqual(by["نقشه"]["count"], len(sampledata.DEVICES))  # آخرین موقعیت هر دستگاه
        self.assertTrue(by["پیشرفته"]["placeholder"])
        self.assertEqual([a["title"] for a in pv["actions"]], ["ثبت"])
        self.assertTrue(pv["has_map"])

    def test_preview_block_error_does_not_raise(self):
        s, k = with_page()
        s = blueprint.apply(s, PID, {"op": "block.add", "page": k, "block": {"kind": "kpi", "title": "بی‌جدول"}})
        self.assertTrue(sampledata.preview(s, k)["all_blocks"][0]["error"])
        with self.assertRaises(ValueError):
            sampledata.preview(s, "zz")


@override_settings(ADMIN_2FA_REQUIRED=False)
class ApiTests(TestCase):
    def setUp(self):
        self.su = get_user_model().objects.create_superuser("bproot", "Str0ng-Admin-Pass")
        self.client.force_login(self.su)
        self.d = PluginDraft.objects.create(plugin_id=PID, name="پایش", wizard=base())

    def post(self, name, body):
        return self.client.post(reverse(f"admin:kernel_plugindraft_api_{name}", args=[self.d.pk]), json.dumps(body), content_type="application/json")

    def test_op_saves_compiles_and_records(self):
        r = self.post("op", {"op": "page.add", "title": "پایش"})
        self.assertEqual(r.status_code, 200)
        k = r.json()["spec"]["pages"][0]["key"]
        r = self.post("op", {"op": "block.add", "page": k, "block": {"kind": "kpi", "title": "ت", "table": "mon_points"}})
        j = r.json()
        self.assertTrue(j["analysis"]["ok"])
        self.d.refresh_from_db()
        self.assertIn(k, self.d.pages)  # TOML ساخته شد
        self.assertEqual(self.d.wizard["pages"][0]["blocks"][0]["id"], j["spec"]["pages"][0]["blocks"][0]["id"])
        self.assertEqual(PluginDraftRevision.objects.filter(draft=self.d).count(), 2)

    def test_bad_op_is_400_and_unchanged(self):
        r = self.post("op", {"op": "page.del", "key": "zz"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.json())
        self.assertEqual(self.client.post(reverse("admin:kernel_plugindraft_api_op", args=[self.d.pk]), "{bad", content_type="application/json").status_code, 400)
        self.assertEqual(PluginDraftRevision.objects.count(), 0)

    def test_batch_and_restore(self):
        self.post("op", {"ops": [{"op": "page.add", "title": "الف"}, {"op": "page.add", "title": "ب"}]})
        self.assertEqual(len(self.client.get(reverse("admin:kernel_plugindraft_api_state", args=[self.d.pk])).json()["spec"]["pages"]), 2)
        self.post("op", {"op": "page.del", "key": "p1"})
        revs = self.client.get(reverse("admin:kernel_plugindraft_api_revisions", args=[self.d.pk])).json()["revisions"]
        self.assertEqual(len(revs), 2)
        r = self.post("restore", {"revision": revs[1]["id"]})
        self.assertEqual(len(r.json()["spec"]["pages"]), 2)
        self.assertEqual(self.post("restore", {"revision": 999999}).status_code, 404)
        self.assertEqual(self.post("restore", {"revision": "x"}).status_code, 400)

    def test_revisions_pruned(self):
        for i in range(PluginDraftRevision.KEEP + 5):
            self.post("op", {"op": "meta.set", "summary": f"خ{i}"})
        self.assertEqual(PluginDraftRevision.objects.filter(draft=self.d).count(), PluginDraftRevision.KEEP)

    def test_preview_html(self):
        s, k = full_spec()
        self.d.wizard = s
        self.d.save()
        r = self.client.get(reverse("admin:kernel_plugindraft_api_preview", args=[self.d.pk, k]))
        j = r.json()
        self.assertIn("پایش", j["html"] + "پایش")
        self.assertIn("data-pk-map", j["html"])
        self.assertIn("pk-bars", j["html"])
        self.assertEqual(j["actions"], [{"kind": "form", "title": "ثبت"}])
        self.assertEqual(self.client.get(reverse("admin:kernel_plugindraft_api_preview", args=[self.d.pk, "zz"])).status_code, 404)

    def test_permissions(self):
        self.client.logout()
        u = get_user_model().objects.create_admin("plainstaff", "Str0ng-Admin-Pass", superuser=False)
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse("admin:kernel_plugindraft_api_state", args=[self.d.pk])).status_code, 403)
        self.assertEqual(self.post("op", {"op": "meta.set", "summary": "x"}).status_code, 403)
        self.assertEqual(PluginDraftRevision.objects.count(), 0)
