"""صفحه‌های ویزارد ساخت پلاگین در پنل (ADR-0008 مرحله‌ی ۳)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from kernel import pagekit
from kernel.models import PluginDraft

TBL = {"suffix": "points", "indexes": "device,at", "c_name": ["device", "lat", "lon", "speed", "at"],
       "c_type": ["text", "double", "double", "double", "timestamptz"], "c_req_0": "1", "c_req_1": "1", "c_req_2": "1", "c_auto_4": "1",
       "op": "addtable"}


@override_settings(ADMIN_2FA_REQUIRED=False)
class WizardFlowTests(TestCase):
    def setUp(self):
        self.su = get_user_model().objects.create_superuser("wzroot", "Str0ng-Admin-Pass")
        self.client.force_login(self.su)

    def step1(self, **over):
        data = {"name": "مانیتورینگ آنلاین", "plugin_id": "monitoring", "summary": "پایش زنده", "description": "شرح", "icon": "pulse", **over}
        return self.client.post(reverse("admin:kernel_plugindraft_wizard_new"), data)

    def draft(self):
        return PluginDraft.objects.get(plugin_id="monitoring")

    def url(self, step):
        return reverse("admin:kernel_plugindraft_wizard", args=[self.draft().pk, step])

    def test_step1_creates_draft_and_goes_to_step2(self):
        r = self.step1()
        d = self.draft()
        self.assertRedirects(r, reverse("admin:kernel_plugindraft_wizard", args=[d.pk, 2]), fetch_redirect_response=False)
        self.assertEqual((d.name, d.version, d.kind, d.wizard["intro"]["icon"]), ("مانیتورینگ آنلاین", "1.0.0", "custom", "pulse"))
        self.assertEqual(self.client.get(self.url(1)).status_code, 200)

    def test_step1_rejects_bad_or_duplicate_id(self):
        for pid in ("Bad-Id", "x", "monitoring "[:0]):
            self.step1(plugin_id=pid)
        self.assertFalse(PluginDraft.objects.exists())
        self.step1()
        self.step1()  # شناسه‌ی تکراری
        self.assertEqual(PluginDraft.objects.count(), 1)
        self.step1(plugin_id="billing")  # پلاگین نصب‌شده
        self.assertEqual(PluginDraft.objects.count(), 1)

    def test_step2_add_and_delete_table_with_prefix(self):
        self.step1()
        self.client.post(self.url(2), TBL)
        t = self.draft().wizard["tables"][0]
        self.assertEqual(t["name"], "monitoring_points")
        self.assertEqual([c["name"] for c in t["columns"]], ["device", "lat", "lon", "speed", "at"])
        self.assertTrue(t["columns"][0]["required"] and t["columns"][4]["auto_now"])
        self.assertEqual(t["indexes"], [["device", "at"]])
        self.assertContains(self.client.get(self.url(2)), "monitoring_points")
        self.client.post(self.url(2), {"op": "deltable:monitoring_points"})
        self.assertEqual(self.draft().wizard["tables"], [])

    def test_step2_rejects_bad_names_and_types(self):
        self.step1()
        for bad in ({**TBL, "suffix": "Bad Name"}, {**TBL, "c_type": ["text", "serial", "double", "double", "timestamptz"]},
                    {**TBL, "c_name": ["id", "lat", "lon", "speed", "at"]}, {**TBL, "indexes": "nope"}):
            self.client.post(self.url(2), bad)
        self.assertEqual(self.draft().wizard["tables"], [])

    def test_step3_builds_pages_and_blocks(self):
        self.step1()
        self.client.post(self.url(2), TBL)
        self.client.post(self.url(4), {"op": "addpage", "title": "پایش", "group": "data", "need": "viewer", "refresh": "15", "icon": "pulse"})
        page = self.draft().wizard["pages"][0]
        self.assertEqual((page["key"], page["refresh"]), ("p1", 15))
        add = reverse("admin:kernel_plugindraft_wizard", args=[self.draft().pk, 4])
        blocks = [
            {"kind": "kpi", "title": "فعال", "table": "monitoring_points", "agg": "count", "distinct": "device", "since_col": "at", "since_minutes": "5"},
            {"kind": "table", "title": "آخرین‌ها", "table": "monitoring_points", "columns": ["device", "speed"], "order_by": "at", "limit": "10"},
            {"kind": "map", "title": "نقشه", "table": "monitoring_points", "lat": "lat", "lon": "lon", "props": ["device"], "latest_by": "device", "time_col": "at"},
            {"kind": "ingest", "title": "دریافت", "table": "monitoring_points", "fields": ["device", "lat", "lon", "speed"]},
            {"kind": "text", "title": "راهنما", "text": "سلام"}]
        for b in blocks:
            r = self.client.post(add, {"op": "addblock:p1", **b})
            self.assertEqual(r.status_code, 302)
        d = self.draft()
        self.assertEqual([b["kind"] for b in d.wizard["pages"][0]["blocks"]], ["kpi", "table", "map", "ingest", "text"])
        compiled = pagekit.parse_page("monitoring", __import__("tomllib").loads(d.pages["p1"]))
        self.assertEqual((len(compiled.blocks), compiled.ingests[0].table, compiled.tables[0].name), (4, "monitoring_points", "monitoring_points"))
        self.assertContains(self.client.get(add), "دریافت")

    def test_invalid_blocks_are_not_added(self):
        self.step1()
        self.client.post(self.url(2), TBL)
        self.client.post(self.url(4), {"op": "addpage", "title": "پایش", "icon": "pulse"})
        for bad in ({"kind": "kpi", "table": "other"}, {"kind": "kpi", "table": "monitoring_points", "agg": "avg", "column": "device"},
                    {"kind": "table", "table": "monitoring_points", "columns": ["nope"]}, {"kind": "nothing"},
                    {"kind": "map", "table": "monitoring_points", "lat": "device", "lon": "lon"},
                    {"kind": "ingest", "table": "monitoring_points", "fields": ["at"]},
                    {"kind": "sql", "display": "table", "sql": ""}):
            self.client.post(self.url(4), {"op": "addblock:p1", **bad})
        self.assertEqual(self.draft().wizard["pages"][0]["blocks"], [])

    def test_delete_block_page_and_table_cascade(self):
        self.step1()
        self.client.post(self.url(2), TBL)
        self.client.post(self.url(4), {"op": "addpage", "title": "پایش", "icon": "pulse"})
        self.client.post(self.url(4), {"op": "addblock:p1", "kind": "kpi", "table": "monitoring_points", "agg": "count"})
        self.client.post(self.url(4), {"op": "addblock:p1", "kind": "text", "text": "x"})
        self.client.post(self.url(4), {"op": "delblock:p1:1"})
        self.assertEqual([b["kind"] for b in self.draft().wizard["pages"][0]["blocks"]], ["kpi"])
        self.client.post(self.url(2), {"op": "deltable:monitoring_points"})  # بلوک وابسته هم پاک می‌شود
        self.assertEqual(self.draft().wizard["pages"][0]["blocks"], [])
        self.client.post(self.url(4), {"op": "delpage:p1"})
        self.assertEqual(self.draft().wizard["pages"], [])

    def test_incomplete_page_shows_errors_but_keeps_spec(self):
        self.step1()
        self.client.post(self.url(2), TBL)
        self.client.post(self.url(4), {"op": "addpage", "title": "خالی", "icon": "pulse"})
        r = self.client.get(self.url(4))
        self.assertContains(r, "دست‌کم یک بلوک نمایشی")
        self.assertEqual(self.draft().pages, {})  # صفحه‌ی ناقص ساخته نشد

    def test_studio_can_open_wizard_draft_and_check_it(self):
        from kernel import studio

        self.step1()
        self.client.post(self.url(2), TBL)
        self.client.post(self.url(4), {"op": "addpage", "title": "پایش", "icon": "pulse"})
        self.client.post(self.url(4), {"op": "addblock:p1", "kind": "kpi", "table": "monitoring_points", "agg": "count"})
        steps = studio.check(self.draft())
        self.assertTrue(studio.ok(steps), steps)
        self.assertContains(self.client.get(reverse("admin:kernel_plugindraft_studio", args=[self.draft().pk])), "monitoring")

    def test_preview_uses_sample_database_and_can_create_tables(self):
        self.step1()
        self.client.post(self.url(2), TBL)
        self.client.post(self.url(4), {"op": "addpage", "title": "پایش", "icon": "pulse"})
        self.client.post(self.url(4), {"op": "addblock:p1", "kind": "kpi", "table": "monitoring_points", "agg": "count"})
        ws = mock.Mock(is_live=True, pk=9)
        ctx = {"page": None, "blocks": [], "values": {}, "layers": {}, "param_errors": [], "has_map": False}
        with mock.patch("kernel.workspace.peek", return_value=ws), mock.patch("kernel.studio.preview_page", return_value=ctx), \
                mock.patch("kernel.tables.ensure", return_value=1) as ens, mock.patch("kernel.workspace.log_event"):
            r = self.client.post(self.url(4), {"op": "preview:p1", "preview_db": "9", "create_tables": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ens.call_count, 1)
        with mock.patch("kernel.workspace.peek", return_value=None):
            r = self.client.post(self.url(4), {"op": "preview:p1", "preview_db": "9"})
        self.assertContains(r, "پایگاه داده‌ی فعال")

    def test_permissions_and_hub_links(self):
        self.step1()
        self.client.force_login(get_user_model().objects.create_user("09120007771"))
        self.assertIn(self.client.get(self.url(1)).status_code, (302, 403))
        self.client.force_login(self.su)
        hub = self.client.get(reverse("plugin_hub"), {"tab": "create"})
        self.assertContains(hub, reverse("admin:kernel_plugindraft_wizard_new"))
        self.assertContains(hub, "monitoring")
        self.assertEqual(self.client.get(reverse("admin:kernel_plugindraft_wizard", args=[999999, 1])).status_code, 404)
