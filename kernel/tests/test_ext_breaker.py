"""مرحله‌ی ۴ سطح ۳: قطع‌کن زمان اجرا (استثنای نما و سهم ← خاموشی آنی، ردپا، اعلان، جداسازی بین پلاگین‌ها)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase

from kernel import entitlements, gate, health
from kernel.models import PluginHealthBucket, PluginState, PluginTrip
from kernel.plugins import registry


def make_view(plugin, behaviour):
    def view(request):
        if isinstance(behaviour, BaseException):
            raise behaviour
        return HttpResponse(status=behaviour)

    view.__module__ = f"ext.{plugin}.views"
    return view


class Base(TestCase):
    def setUp(self):
        for pid in ("t4_a", "t4_b"):
            registry.register(pid, pid, kind="custom", tier=3)
            self.addCleanup(registry.remove_plugin, pid)
            PluginState.objects.create(plugin_id=pid, enabled=True, access="open")
        self.addCleanup(entitlements.invalidate)
        entitlements.invalidate()
        n = mock.patch("kernel.workspace.notify_user")
        self.notify = n.start()
        self.addCleanup(n.stop)
        self.admin = get_user_model().objects.create_admin("root4", "Str0ng-Admin-Pass")
        self.rf = RequestFactory()

    def call(self, plugin, behaviour):
        """درخواست را از زنجیره‌ی میان‌افزار دروازه می‌گذراند و پاسخ را برمی‌گرداند."""
        view = make_view(plugin, behaviour)
        req = self.rf.get(f"/x/{plugin}/")
        req.user = self.admin
        mw = gate.PluginGateMiddleware(lambda r: self._inner(r, view))
        return mw(req)

    def _inner(self, req, view):
        mw = gate.PluginGateMiddleware(lambda r: None)
        try:
            pre = mw.process_view(req, view, (), {})
        except Http404:
            return HttpResponse(status=404)
        if pre is not None:
            return pre
        try:
            return view(req)
        except Exception as exc:  # noqa: BLE001 - مثل حلقه‌ی جنگو
            if isinstance(exc, (Http404, PermissionDenied)):
                return HttpResponse(status=404 if isinstance(exc, Http404) else 403)
            mw.process_exception(req, exc)
            return HttpResponse(status=500)


class RecordingTests(Base):
    def test_success_and_error_counted(self):
        self.call("t4_a", 200)
        self.call("t4_a", RuntimeError("boom"))
        self.assertEqual(health.stats("t4_a"), (2, 1))

    def test_exception_counted_once(self):
        self.call("t4_a", RuntimeError("boom"))
        self.assertEqual(health.stats("t4_a"), (1, 1))

    def test_4xx_is_not_the_plugins_fault(self):
        self.call("t4_a", Http404())
        self.call("t4_a", PermissionDenied())
        self.call("t4_a", 400)
        self.assertEqual(health.stats("t4_a"), (3, 0))

    def test_5xx_response_without_exception_is_error(self):
        self.call("t4_a", 503)
        self.assertEqual(health.stats("t4_a"), (1, 1))

    def test_other_plugin_unaffected(self):
        self.call("t4_a", RuntimeError("x"))
        self.assertEqual(health.stats("t4_b"), (0, 0))

    def test_tier1_plugin_not_tracked(self):
        registry.register("t4_plain", "ساده", kind="feature")
        self.addCleanup(registry.remove_plugin, "t4_plain")
        self.call("t4_plain", RuntimeError("x"))
        self.assertFalse(PluginHealthBucket.objects.filter(plugin_id="t4_plain").exists())

    def test_unauthorised_probe_is_not_counted(self):
        PluginState.objects.filter(plugin_id="t4_a").update(access="restricted")
        entitlements.invalidate()
        self.call("t4_a", 200)
        self.assertEqual(health.stats("t4_a"), (0, 0))

    def test_contribution_failure_counted_for_tier3_only(self):
        health.contribution_failed("t4_a")
        health.contribution_failed("billing")
        self.assertEqual(health.stats("t4_a"), (1, 1))
        self.assertFalse(PluginHealthBucket.objects.filter(plugin_id="billing").exists())


class TripTests(Base):
    def feed(self, plugin, ok, bad):
        for _ in range(ok):
            health.record(plugin, True)
        for _ in range(bad):
            health.record(plugin, False)

    def test_threshold_disables_instantly_and_records_trip(self):
        self.feed("t4_a", 10, 20)
        out = health.tick()
        self.assertEqual(out["tripped"], ["t4_a"])
        self.assertFalse(PluginState.objects.get(plugin_id="t4_a").enabled)
        t = PluginTrip.objects.get(plugin_id="t4_a")
        self.assertEqual((t.action, t.release_id, t.runs, t.errors), ("disable", None, 30, 20))
        self.assertTrue(self.notify.called)
        entitlements.invalidate()
        self.assertFalse(entitlements.allowed("t4_a"))

    def test_below_threshold_stays_on(self):
        self.feed("t4_a", 40, 10)
        self.assertEqual(health.tick()["tripped"], [])
        self.assertTrue(PluginState.objects.get(plugin_id="t4_a").enabled)

    def test_one_plugin_tripping_does_not_touch_the_other(self):
        self.feed("t4_a", 0, 25)
        self.feed("t4_b", 25, 0)
        health.tick()
        self.assertTrue(PluginState.objects.get(plugin_id="t4_b").enabled)
        self.assertFalse(PluginState.objects.get(plugin_id="t4_a").enabled)

    def test_no_double_trip_and_counter_reset(self):
        self.feed("t4_a", 0, 25)
        health.tick()
        self.feed("t4_a", 0, 25)
        self.assertEqual(health.tick()["tripped"], [])
        self.assertEqual(PluginTrip.objects.filter(plugin_id="t4_a").count(), 1)

    def test_trip_creates_restricted_state_if_missing(self):
        PluginState.objects.filter(plugin_id="t4_a").delete()
        entitlements.invalidate()
        self.feed("t4_a", 0, 25)
        health.tick()
        st = PluginState.objects.get(plugin_id="t4_a")
        self.assertEqual((st.enabled, st.access), (False, "restricted"))

    def test_view_errors_end_to_end(self):
        for _ in range(25):
            self.call("t4_a", RuntimeError("boom"))
        health.tick()
        self.assertFalse(PluginState.objects.get(plugin_id="t4_a").enabled)

    def test_card_shows_the_trip(self):
        from kernel import admin_cards

        self.feed("t4_a", 0, 25)
        health.tick()
        self.assertIn("t4_a", admin_cards.attention()[0]["text"])


class VisibleGuardTests(Base):
    def test_broken_visible_hides_section_and_counts(self):
        from types import SimpleNamespace

        from core.templatetags import ws

        item = SimpleNamespace(visible="kernel.tests.test_ext_breaker.boom", plugin="t4_a")
        self.assertFalse(ws._visible(item))
        self.assertEqual(health.stats("t4_a"), (1, 1))


def boom():
    raise RuntimeError("visible خراب")


class WorkspaceSpreadTests(Base):
    """خطای یک مشتری (داده‌ی خراب) پلاگین را برای همه خاموش نکند؛ خطای چند مشتری یا تک‌مشتری خاموش می‌کند."""

    def feed(self, ws, ok, bad, plugin="t4_a"):
        for _ in range(ok):
            health.record(plugin, True, ws=ws)
        for _ in range(bad):
            health.record(plugin, False, ws=ws)

    def test_one_bad_customer_among_many_does_not_trip(self):
        self.feed(1, 0, 30)  # فقط پایگاه ۱ خطا می‌دهد
        self.feed(2, 40, 0)
        self.feed(3, 40, 0)
        self.assertEqual(health.stats_ws("t4_a"), (110, 30, 3, 1))
        self.assertEqual(health.tick()["tripped"], [])

    def test_high_rate_but_single_failing_workspace_among_two_does_not_trip(self):
        self.feed(1, 0, 40)
        self.feed(2, 5, 0)
        runs, errors, run_ws, err_ws = health.stats_ws("t4_a")
        self.assertTrue(errors / runs >= 0.5)
        self.assertFalse(health.should_trip(runs, errors, run_ws, err_ws))
        self.assertEqual(health.tick()["tripped"], [])

    def test_two_failing_workspaces_trip(self):
        self.feed(1, 0, 15)
        self.feed(2, 0, 15)
        self.assertEqual(health.tick()["tripped"], ["t4_a"])

    def test_single_customer_plugin_still_trips(self):
        self.feed(7, 5, 30)
        self.assertEqual(health.stats_ws("t4_a")[2:], (1, 1))
        self.assertEqual(health.tick()["tripped"], ["t4_a"])

    def test_unknown_workspace_keeps_old_behaviour(self):
        self.feed(0, 5, 30)
        self.assertEqual(health.tick()["tripped"], ["t4_a"])

    def test_gate_records_workspace_of_the_request(self):
        from types import SimpleNamespace

        req = self.rf.get("/x")
        req.resolver_match = SimpleNamespace(kwargs={"pk": 42})
        self.assertEqual(gate.PluginGateMiddleware._ws(req), 42)
        req.resolver_match = SimpleNamespace(kwargs={})
        self.assertEqual(gate.PluginGateMiddleware._ws(req), 0)
        req.resolver_match = None
        self.assertEqual(gate.PluginGateMiddleware._ws(req), 0)


class TierColumnTests(Base):
    def test_plugin_list_shows_tier(self):
        from django.contrib import admin as dj_admin

        from kernel.admin import PluginStateAdmin

        ma = PluginStateAdmin(PluginState, dj_admin.site)
        registry.register("t4_t2", "دو", kind="custom", tier=2)
        self.addCleanup(registry.remove_plugin, "t4_t2")
        self.assertIn("۳", ma.tier(PluginState(plugin_id="t4_a")))
        self.assertIn("۲", ma.tier(PluginState(plugin_id="t4_t2")))
        self.assertEqual(ma.tier(PluginState(plugin_id="nothing")), "—")
        self.assertIn("tier", ma.list_display)
