"""قطع‌کن خودکار: شمارش فقط خطای خود کد، آستانه، بازگشت یا خاموشی، ردپا و اعلان."""
import datetime
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from kernel import handlers, health, pagekit, pkg
from kernel.models import PluginHealthBucket, PluginRelease, PluginTrip
from kernel.plugins import registry
from kernel.runner import client

S = PluginRelease.Status


def release(version, status, activated=True, plugin="compute"):
    return PluginRelease.objects.create(
        plugin_id=plugin, version=version, name="x", sha256=f"{plugin}{version}".ljust(64, "0"), blob=b"x", status=status,
        activated_at=timezone.now() - datetime.timedelta(days=1) if activated else None)


class BreakerBase(TestCase):
    def setUp(self):
        registry.register("compute", "محاسبه", kind="custom")
        self.addCleanup(registry.remove_plugin, "compute")
        pkg._loaded["compute"] = "hash"
        self.addCleanup(pkg._loaded.pop, "compute", None)
        s = mock.patch("kernel.pkg.sync", return_value=0)
        s.start()
        self.addCleanup(s.stop)
        n = mock.patch("kernel.workspace.notify_user")
        self.notify = n.start()
        self.addCleanup(n.stop)
        self.admin = get_user_model().objects.create_admin("root", "Str0ng-Admin-Pass")

    def feed(self, ok, bad, now=None):
        now = now or timezone.now()
        for _ in range(ok):
            health.record("compute", True, now)
        for _ in range(bad):
            health.record("compute", False, now)


class RecordTests(BreakerBase):
    def test_counts_and_ignores_non_package_plugins(self):
        self.feed(3, 2)
        self.assertEqual(health.stats("compute"), (5, 2))
        health.record("billing", False)  # بسته نیست
        self.assertFalse(PluginHealthBucket.objects.filter(plugin_id="billing").exists())

    def test_window_excludes_old_buckets_and_threshold(self):
        old = timezone.now() - datetime.timedelta(minutes=health.WINDOW_MIN + 20)
        self.feed(0, 30, now=old)
        self.assertEqual(health.stats("compute"), (0, 0))
        self.assertFalse(health.should_trip(19, 19))  # کم‌تر از حداقل اجرا
        self.assertFalse(health.should_trip(40, 19))  # زیر ۵۰٪
        self.assertTrue(health.should_trip(40, 20))

    def test_record_never_raises(self):
        with mock.patch("kernel.models.PluginHealthBucket.objects") as m:
            m.get_or_create.side_effect = RuntimeError("db")
            health.record("compute", False)


class ClientCountingTests(BreakerBase):
    def setUp(self):
        super().setUp()
        handlers.register("compute", "h", "def handle(c, p):\n    return {'columns': [], 'rows': []}")

    def test_success_and_code_failure_counted_infra_failure_not(self):
        client.execute("compute", "h", {}, lambda q, a: {})
        handlers.register("compute", "h", "def handle(c, p):\n    return 1/0")
        with self.assertRaises(client.HandlerFailed):
            client.execute("compute", "h", {}, lambda q, a: {})
        self.assertEqual(health.stats("compute"), (2, 1))
        with override_settings(PLUGIN_RUNNER_MODE="off"), self.assertRaises(client.RunnerError):
            client.execute("compute", "h", {}, lambda q, a: {})
        with override_settings(PLUGIN_RUNNER_MODE="remote", PLUGIN_RUNNER_URL="", PLUGIN_RUNNER_TOKEN="", PLUGIN_RUNNER_CALLBACK=""), \
                self.assertRaises(client.RunnerError):
            client.execute("compute", "h", {}, lambda q, a: {}, 5)
        self.assertEqual(health.stats("compute"), (2, 1))  # خرابی زیرساخت شمرده نشد

    def test_block_render_failure_path_counts_through_client(self):
        handlers.register("compute", "calc", "def handle(c, p):\n    return 1/0")
        page = pagekit.parse_page("compute", {"key": "main", "title": "t", "blocks": [{"kind": "table", "handler": "calc"}]})
        out = pagekit.render_block(object(), page, page.blocks[0], {})
        self.assertIn("ZeroDivisionError", out["error"])
        self.assertEqual(health.stats("compute"), (1, 1))


class TripTests(BreakerBase):
    def test_rolls_back_to_latest_previous_approved_version(self):
        release("1.0.0", S.RETIRED)
        r2 = release("1.1.0", S.RETIRED)
        bad = release("2.0.0", S.ACTIVE)
        self.feed(5, 30)
        out = health.tick()
        self.assertEqual(out, {"tripped": ["compute"]})
        bad.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual((bad.status, r2.status), (S.RETIRED, S.ACTIVE))
        t = PluginTrip.objects.get()
        self.assertEqual((t.action, t.version, t.restored_version, t.errors, t.runs), ("rollback", "2.0.0", "1.1.0", 30, 35))
        self.assertEqual(health.stats("compute"), (0, 0))  # شمارنده صفر شد
        self.notify.assert_called_once()
        self.assertEqual(self.notify.call_args[0][0], self.admin)

    def test_disables_when_no_previous_version(self):
        only = release("1.0.0", S.ACTIVE)
        self.feed(0, 25)
        health.tick()
        only.refresh_from_db()
        self.assertEqual(only.status, S.RETIRED)
        self.assertEqual(PluginTrip.objects.get().action, "disable")
        self.assertFalse(PluginRelease.objects.filter(status=S.ACTIVE).exists())

    def test_tripped_version_is_never_a_rollback_target_and_newer_ones_are_skipped(self):
        release("1.0.0", S.RETIRED)
        newer = release("3.0.0", S.RETIRED)  # قبلاً فعال بوده ولی از نسخه‌ی فعلی بالاتر است
        active = release("2.0.0", S.ACTIVE)
        PluginTrip.objects.create(plugin_id="compute", release=newer, version="3.0.0", action="disable", runs=30, errors=30)
        self.feed(0, 30)
        health.tick()
        self.assertEqual(PluginTrip.objects.filter(release=active).get().restored_version, "1.0.0")

    def test_never_activated_releases_are_not_restored(self):
        release("1.0.0", S.CHECKED, activated=False)
        release("2.0.0", S.ACTIVE)
        self.feed(0, 30)
        health.tick()
        self.assertEqual(PluginTrip.objects.get().action, "disable")

    def test_healthy_or_quiet_plugin_is_left_alone_and_old_buckets_pruned(self):
        release("1.0.0", S.ACTIVE)
        self.feed(30, 5)
        self.assertEqual(health.tick(), {"tripped": []})
        self.feed(0, 10, now=timezone.now() - datetime.timedelta(hours=30))
        health.tick()
        self.assertFalse(PluginHealthBucket.objects.filter(bucket__lt=timezone.now() - datetime.timedelta(hours=25)).exists())
        self.assertFalse(PluginTrip.objects.exists())

    def test_tick_is_registered_and_trip_without_active_release_is_noop(self):
        from kernel import jobs

        self.assertEqual(registry.get(jobs.TICK, "plugin_breaker"), "kernel.health.tick")
        self.assertIsNone(health.trip("compute", 30, 30))
