import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from kernel import entitlements, metering
from kernel.models import Entitlement, PluginState, PluginUsage
from kernel.plugins import registry


class MeteringTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("09120000001")
        self.ws = mock.Mock(pk=7, plan=None, owner_id=None)

    def test_record_accumulates_per_day_and_subject(self):
        metering.record("demo", "calls", user=self.user, ws=self.ws)
        metering.record("demo", "calls", 4, user=self.user, ws=self.ws)
        metering.record("demo", "calls")
        self.assertEqual(PluginUsage.objects.count(), 2)
        self.assertEqual(metering.used("demo", "calls", ws=self.ws), 5)
        self.assertEqual(metering.used("demo", "calls", user=self.user), 5)
        self.assertEqual(metering.used("demo", "calls"), 6)

    def test_window_excludes_old_days(self):
        PluginUsage.objects.create(plugin_id="demo", metric="calls", day=timezone.localdate() - datetime.timedelta(days=40), count=9)
        metering.record("demo", "calls")
        self.assertEqual(metering.used("demo", "calls"), 1)
        self.assertEqual(metering.used("demo", "calls", days=60), 10)

    def test_non_positive_ignored_and_never_raises(self):
        metering.record("demo", "calls", 0)
        metering.record("demo", "calls", -3)
        self.assertEqual(PluginUsage.objects.count(), 0)
        with mock.patch("kernel.models.PluginUsage.objects") as m:
            m.get_or_create.side_effect = RuntimeError("db down")
            metering.record("demo", "calls")  # بدون استثنا

    def test_limit_from_entitlement(self):
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        self.addCleanup(entitlements.invalidate)
        st = PluginState.objects.create(plugin_id="demo", access=PluginState.Access.RESTRICTED)
        Entitlement.objects.create(state=st, kind=Entitlement.Kind.USER, subject=str(self.user.pk), limits={"calls_per_month": 2})
        entitlements.invalidate()
        self.assertEqual(metering.limit("demo", "calls", user=self.user), 2)
        ok, now, cap = metering.check("demo", "calls", user=self.user)
        self.assertEqual((ok, now, cap), (True, 0, 2))
        metering.record("demo", "calls", 2, user=self.user)
        self.assertFalse(metering.check("demo", "calls", user=self.user)[0])
        self.assertIsNone(metering.limit("demo", "other", user=self.user))

    def test_prune(self):
        PluginUsage.objects.create(plugin_id="demo", metric="calls", day=timezone.localdate() - datetime.timedelta(days=500), count=1)
        metering.record("demo", "calls")
        self.assertEqual(metering.prune(), 1)
        self.assertEqual(PluginUsage.objects.count(), 1)
