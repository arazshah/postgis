"""قابلیت‌های مشترک به‌صورت پلاگین مستقل: ثبت، روشن/خاموش و محدودسازی هر کدام جدا از بقیه."""
import json
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from databases import services
from databases.tests.test_services import BaseCase
from kernel import caps, entitlements, notify, pagekit, platform, sources
from kernel.models import Entitlement, NotifyAddress, PluginState, SourceHost, SourceState
from kernel.plugins import registry
from kernel.tests.test_pagekit import STORAGES

PAGE = {"key": "lab", "title": "آزمایشگاه", "need": "editor", "blocks": [{"kind": "text", "text": "x"}],
        "tables": [{"name": "demo_t", "columns": [{"name": "name", "type": "text"}, {"name": "area", "type": "polygon"}]}],
        "forms": [{"key": "plain", "title": "ساده", "table": "demo_t", "fields": [{"name": "name", "kind": "text", "label": "نام"}]},
                  {"key": "geo", "title": "هندسه", "table": "demo_t", "fields": [{"name": "area", "kind": "geometry", "geom": "polygon", "label": "محدوده"}]}],
        "records": [{"key": "rows", "title": "ردیف‌ها", "table": "demo_t", "fields": [{"name": "name", "kind": "text", "label": "نام"}]}],
        "sources": [{"key": "wx", "title": "هوا", "url": "https://api.open-meteo.com/v1/forecast", "table": "demo_t",
                     "fields": [{"name": "name", "kind": "text", "label": "نام", "path": "x"}]}],
        "reports": [{"key": "rep", "title": "گزارش"}]}


class RegistryTests(SimpleTestCase):
    def test_five_independent_plugins_are_registered(self):
        for c in caps.CAPS:
            p = registry.plugins[caps.pid(c)]
            self.assertEqual((p.kind, p.tier), ("feature", 1))
            self.assertTrue(p.name and p.description)
        self.assertEqual(len(caps.CAPS), 5)


class SwitchTests(BaseCase):
    @override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
    def setUp(self):
        super().setUp()
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(platform.invalidate)
        self.page = pagekit.parse_page("demo", PAGE)
        for target, val in (("kernel.pagekit.get", lambda a, b: self.page if (a, b) == ("demo", "lab") else None),
                            ("kernel.pagekit.render_block", lambda *a, **k: {"kind": "text", "paras": ["x"], "width": "full", "title": ""}),
                            ("kernel.pagekit.fetch_records", lambda ws, rc: (["id", "name"], [[1, "الف"]]))):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)
        self.db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)

    def off(self, cap):
        PluginState.objects.update_or_create(plugin_id=caps.pid(cap), defaults={"enabled": False, "access": "open"})
        entitlements.invalidate()

    def get_page(self):
        return self.client.get(reverse("kernel:page", args=[self.db.pk, "demo", "lab"]))

    def test_all_on_by_default(self):
        r = self.get_page()
        for part in ('id="record-rows"', 'id="source-wx"', "گزارش PDF", 'id="form-geo"', 'id="form-plain"'):
            self.assertContains(r, part)

    def test_reports_off_hides_buttons_and_blocks_endpoints(self):
        self.off("reports")
        r = self.get_page()
        self.assertNotContains(r, "گزارش PDF")
        self.assertNotContains(r, "چیدمان")
        a = [self.db.pk, "demo", "lab", "rep"]
        for name in ("report", "report_png", "report_editor"):
            self.assertEqual(self.client.get(reverse(f"kernel:{name}", args=a)).status_code, 404, name)
        for name in ("report_save", "report_preview", "report_logo"):
            self.assertEqual(self.client.post(reverse(f"kernel:{name}", args=a), data="{}", content_type="application/json").status_code, 404, name)
        self.assertContains(r, 'id="form-plain"')  # بقیه‌ی قابلیت‌ها سالم

    def test_sources_off_hides_card_blocks_actions_and_tick_skips(self):
        self.off("sources")
        self.assertNotContains(self.get_page(), 'id="source-wx"')
        a = [self.db.pk, "demo", "lab", "wx"]
        self.assertEqual(self.client.post(reverse("kernel:source_save", args=a), {"do": "enable"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("kernel:source_run", args=a)).status_code, 404)
        SourceState.objects.create(plugin_id="demo", page="lab", key="wx", workspace_id=self.db.pk, enabled=True, next_run=timezone.now())
        platform.set_("sources_enabled", "1")
        SourceHost.objects.create(host="api.open-meteo.com")
        with mock.patch.object(sources, "_fetch") as fetch, mock.patch("kernel.workspace.peek", return_value=SimpleNamespace(pk=self.db.pk, is_live=True, owner=self.user)):
            self.assertEqual(sources.tick()["ran"], 0)
        fetch.assert_not_called()

    def test_draw_off_hides_records_and_geometry_forms_only(self):
        self.off("draw")
        r = self.get_page()
        self.assertNotContains(r, 'id="record-rows"')
        self.assertNotContains(r, 'id="form-geo"')
        self.assertContains(r, 'id="form-plain"')
        self.assertEqual(self.client.get(reverse("kernel:record_edit", args=[self.db.pk, "demo", "lab", "rows", 1])).status_code, 404)
        self.assertEqual(self.client.post(reverse("kernel:record_delete", args=[self.db.pk, "demo", "lab", "rows", 1])).status_code, 404)
        with mock.patch("kernel.pagekit.insert_row") as ins:
            self.assertEqual(self.client.post(reverse("kernel:form", args=[self.db.pk, "demo", "lab", "geo"]),
                                              {"f_area": json.dumps({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]})}).status_code, 404)
            ins.assert_not_called()
            self.assertEqual(self.client.post(reverse("kernel:form", args=[self.db.pk, "demo", "lab", "plain"]), {"f_name": "x"}).status_code, 302)

    def test_restricted_plugin_needs_a_grant(self):
        st = PluginState.objects.create(plugin_id=caps.pid("reports"), enabled=True, access="restricted")
        entitlements.invalidate()
        self.assertNotContains(self.get_page(), "گزارش PDF")
        Entitlement.objects.create(state=st, kind="workspace", subject=str(self.db.pk))
        entitlements.invalidate()
        self.assertContains(self.get_page(), "گزارش PDF")


class NotifyCapTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u", phone="09120000011", password="x")
        notify.save_channel("bale", enabled=True, token="1:T", bot_username="b")
        NotifyAddress.objects.create(user=self.user, channel="bale", chat_id="5")
        self.addCleanup(entitlements.invalidate)

    def test_off_means_sms_email_only_and_no_linking(self):
        PluginState.objects.create(plugin_id=caps.pid("notify"), enabled=False)
        entitlements.invalidate()
        with mock.patch.object(notify, "_http") as h, mock.patch("kernel.workspace.notify_user") as sms:
            out = notify.deliver(self.user, "a", "b")
        h.assert_not_called()
        sms.assert_called_once()
        self.assertEqual((out["sent"], out["fallback"]), ([], True))
        with self.assertRaises(notify.NotifyError):
            notify.begin_link(self.user, "bale")

    def test_on_sends_to_messenger(self):
        with mock.patch.object(notify, "_http", return_value={"ok": True, "result": {}}) as h:
            self.assertEqual(notify.deliver(self.user, "a", "b")["sent"], ["bale"])
        h.assert_called_once()
