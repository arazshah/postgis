"""مرحله‌ی ۱ سطح ۳ (docs/adr/0007): بارگذار، حالت امن، مسیر با پیشوند، پیش‌فرض بسته."""
import tempfile
from pathlib import Path

from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase

import ext
from kernel import admin as kadmin
from kernel import entitlements, gate, routes
from kernel.models import PluginState
from kernel.plugins import PluginError, registry


def _tree(names):
    root = Path(tempfile.mkdtemp())
    for n in names:
        (root / n).mkdir()
        (root / n / "apps.py").write_text("")
    return root


class LoaderTests(TestCase):
    def test_empty_ext_adds_nothing(self):
        self.assertEqual(ext.discover(root=_tree([])), [])

    def test_discovers_valid_ids_only(self):
        root = _tree(["gps_live", "Bad-Name", "x"])
        (root / "no_apps").mkdir()
        self.assertEqual(ext.discover(root=root), ["ext.gps_live"])

    def test_safe_mode_loads_nothing(self):
        self.assertEqual(ext.discover(safe_mode=True, root=_tree(["gps_live"])), [])

    def test_disabled_list(self):
        root = _tree(["aa", "bb", "cc"])
        self.assertEqual(ext.discover(disabled="bb, cc", root=root), ["ext.aa"])
        self.assertEqual(ext.discover(disabled=["aa"], root=root), ["ext.bb", "ext.cc"])

    def test_real_ext_dir_has_no_plugin_yet(self):
        self.assertEqual(ext.discover(), [])


class TierTests(TestCase):
    def test_default_tier_and_validation(self):
        p = registry.register("t3_a", "الف", kind="feature")
        self.addCleanup(registry.remove_plugin, "t3_a")
        self.assertEqual(p.tier, 1)
        with self.assertRaises(PluginError):
            registry.register("t3_bad", "بد", tier=9)
        with self.assertRaises(PluginError):
            registry.register("t3_sys", "سیستمی", kind="system", tier=3)


class Tier3PolicyTests(TestCase):
    def setUp(self):
        registry.register("t3_demo", "نمونه", kind="custom", tier=3)
        self.addCleanup(registry.remove_plugin, "t3_demo")
        self.addCleanup(entitlements.invalidate)
        entitlements.invalidate()

    def test_closed_without_state_row(self):
        self.assertFalse(entitlements.allowed("t3_demo"))
        self.assertFalse(entitlements.is_enabled("t3_demo"))

    def test_sync_creates_restricted_row(self):
        kadmin.sync_states()
        st = PluginState.objects.get(plugin_id="t3_demo")
        self.assertEqual(st.access, PluginState.Access.RESTRICTED)
        entitlements.invalidate()
        self.assertFalse(entitlements.allowed("t3_demo"))

    def test_owner_plugin_resolves_ext_module(self):
        def view(request):
            return HttpResponse("ok")

        view.__module__ = "ext.t3_demo.views"
        self.assertEqual(gate.owner_plugin(view), "t3_demo")

    def test_gate_404_for_tier3_without_state(self):
        def view(request):
            return HttpResponse("ok")

        view.__module__ = "ext.t3_demo.views"
        req = RequestFactory().get("/x/t3_demo/")
        with self.assertRaises(Http404):
            gate.PluginGateMiddleware(lambda r: None).process_view(req, view, (), {})

    def test_tier1_without_state_stays_open(self):
        registry.register("t3_plain", "ساده", kind="feature")
        self.addCleanup(registry.remove_plugin, "t3_plain")
        self.assertTrue(entitlements.allowed("t3_plain"))


class RoutePrefixTests(TestCase):
    def test_ext_routes_need_id_prefix(self):
        with self.assertRaises(PluginError):
            routes.add("ext", "other/page/", "x.y.z", "p", plugin="t3_demo")
        with self.assertRaises(PluginError):
            routes.add("ws_ext", "page/", "x.y.z", "p", plugin="t3_demo")

    def test_other_groups_unaffected(self):
        registry.register("t3_rt", "مسیر", kind="feature")
        self.addCleanup(registry.remove_plugin, "t3_rt")
        routes.add("t3_group", "anything/", "x.y.z", "p", plugin="t3_rt")
        self.addCleanup(lambda: registry._points.get("route", {}).pop("t3_group:p", None))
