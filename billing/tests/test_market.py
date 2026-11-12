"""بازار پلاگین سمت مشتری: صفحه، دوره‌ی آزمایشی یک‌بار، خرید و تمدید، و اطلاع‌رسانی انقضا (ADR-0008 مرحله‌ی ۶)."""
import datetime
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing import market_jobs, services
from billing.models import PluginAddon
from kernel import entitlements
from kernel.models import Entitlement, PluginState
from kernel.plugins import registry

from .test_billing import BillingTests as _Base


class MarketTests(TestCase):
    def setUp(self):
        _Base.setUp(self)
        registry.register("fleet", "ناوگان", kind="custom", description="پایش زنده‌ی ناوگان")
        registry.register("freebie", "رایگان‌ی", kind="feature", description="همیشه رایگان")
        for pid in ("fleet", "freebie"):
            self.addCleanup(registry.remove_plugin, pid)
        self.addCleanup(entitlements.invalidate)
        PluginState.objects.create(plugin_id="fleet", access="restricted")
        PluginState.objects.create(plugin_id="freebie", access="open")
        self.addon = PluginAddon.objects.create(plugin_id="fleet", title="پایش ناوگان", description="خلاصه", price_toman=90000, duration_days=30,
                                                trial_days=7, limits={"page_views_per_month": 500})
        entitlements.invalidate()
        self.client.force_login(self.user)
        self.url = reverse("billing:market")

    def test_page_lists_paid_with_trial_and_free_plugins(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "پایش ناوگان")
        self.assertContains(r, "شروع آزمایشی")
        self.assertContains(r, "رایگان‌ی")  # بخش رایگان و فعال برای همه
        self.assertContains(r, self.db.db_name)

    def test_anonymous_is_redirected(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_trial_grants_time_limited_license_once(self):
        r = self.client.post(reverse("billing:start_trial"), {"addon": self.addon.pk, "target": self.db.pk})
        self.assertEqual(r.status_code, 302)
        ent = Entitlement.objects.get(state__plugin_id="fleet")
        self.assertEqual((ent.kind, ent.subject, ent.source), ("workspace", str(self.db.pk), "trial"))
        self.assertTrue(6 <= (ent.expires_at - timezone.now()).days <= 7)
        self.assertEqual(ent.limits, {"page_views_per_month": 500})
        entitlements.invalidate()
        self.assertTrue(entitlements.allowed("fleet", user=self.user, ws=self.db))
        # بار دوم (حتی بعد از انقضا) ممنوع است
        self.client.post(reverse("billing:start_trial"), {"addon": self.addon.pk, "target": self.db.pk})
        self.assertEqual(Entitlement.objects.filter(state__plugin_id="fleet").count(), 1)
        Entitlement.objects.update(expires_at=timezone.now() - datetime.timedelta(days=1))
        with self.assertRaises(services.BillingError):
            services.start_trial(self.user, self.addon, self.db)
        entitlements.invalidate()
        self.assertFalse(entitlements.allowed("fleet", user=self.user, ws=self.db))  # منقضی ⇒ بسته

    def test_trial_rules(self):
        self.addon.trial_days = 0
        self.addon.save()
        with self.assertRaises(services.BillingError):
            services.start_trial(self.user, self.addon, self.db)
        self.addon.trial_days = 7
        self.addon.is_public = False
        self.addon.save()
        with self.assertRaises(services.BillingError):
            services.start_trial(self.user, self.addon, self.db)
        self.addon.is_public = True
        self.addon.save()
        from accounts.models import User

        other = User.objects.create_user("09125550000")
        with self.assertRaises(services.BillingError):  # پایگاه کس دیگر
            services.start_trial(other, self.addon, self.db)
        with self.assertRaises(services.BillingError):  # پایگاه نامشخص
            services.start_trial(self.user, self.addon, None)

    def test_user_scope_trial_and_status(self):
        self.addon.scope = PluginAddon.Scope.USER
        self.addon.save()
        self.assertEqual(services.addon_status(self.addon, self.user)["state"], "none")
        services.start_trial(self.user, self.addon)
        st = services.addon_status(self.addon, self.user)
        self.assertEqual((st["state"], st["source"]), ("trial", "trial"))
        self.assertTrue(6 <= st["days_left"] <= 7)
        self.assertContains(self.client.get(self.url), "آزمایشی؛")

    def test_status_active_expired_and_unlimited(self):
        ent = entitlements.grant("fleet", "workspace", str(self.db.pk), source="purchase", days=30)
        self.assertEqual(services.addon_status(self.addon, self.user, self.db)["state"], "active")
        ent.expires_at = timezone.now() - datetime.timedelta(hours=1)
        ent.save()
        self.assertEqual(services.addon_status(self.addon, self.user, self.db)["state"], "expired")
        self.assertContains(self.client.get(self.url), "منقضی شد")
        ent.expires_at = None
        ent.save()
        self.assertEqual(services.addon_status(self.addon, self.user, self.db)["days_left"], None)

    def test_buy_from_market_creates_invoice_and_renewal_extends_trial(self):
        services.start_trial(self.user, self.addon, self.db)
        r = self.client.post(reverse("billing:start_addon"), {"addon": self.addon.pk, "target": self.db.pk, "from": "market"})
        self.assertEqual(r.status_code, 302)
        inv = self.user.invoices.latest("pk")
        services.mark_paid(inv)
        ent = Entitlement.objects.get(state__plugin_id="fleet")
        self.assertEqual(ent.source, "purchase")
        self.assertGreaterEqual((ent.expires_at - timezone.now()).days, 35)  # آزمایشی + ۳۰ روز

    def test_failed_purchase_from_market_returns_to_market(self):
        r = self.client.post(reverse("billing:start_addon"), {"addon": self.addon.pk, "target": "", "from": "market"})
        self.assertRedirects(r, self.url, fetch_redirect_response=False)

    def test_wizard_summary_reaches_the_market_via_manifest_description(self):
        from kernel import studio

        class D:
            plugin_id, name, version, kind, requires, code, alerts = "monitoring", "مانیتورینگ", "1.0.0", "custom", "databases", {}, {}
            pages = {"p1": "x"}
            wizard = {"intro": {"summary": "پایش زنده‌ی دستگاه‌ها"}}

        self.assertIn('description = "پایش زنده‌ی دستگاه‌ها"', studio.manifest_text(D))


class ExpiryNoticeTests(TestCase):
    def setUp(self):
        _Base.setUp(self)
        registry.register("fleet", "ناوگان", kind="custom")
        self.addCleanup(registry.remove_plugin, "fleet")
        self.addCleanup(entitlements.invalidate)
        PluginState.objects.create(plugin_id="fleet", access="restricted")
        n = mock.patch("kernel.workspace.notify_user")
        self.notify = n.start()
        self.addCleanup(n.stop)

    def grant(self, hours, source="purchase", kind="workspace", subject=None):
        e = entitlements.grant("fleet", kind, subject or str(self.db.pk), source=source, days=1)
        e.expires_at = timezone.now() + datetime.timedelta(hours=hours)
        e.save()
        return e

    def test_warns_once_before_expiry_then_announces_expiry_once(self):
        e = self.grant(24 * 3)
        out = market_jobs.tick()
        self.assertEqual(out, {"warned": 1, "expired": 0})
        self.assertEqual(self.notify.call_args.args[0], self.user)
        self.assertIn("روز دیگر", self.notify.call_args.args[2])
        self.assertEqual(market_jobs.tick(), {"warned": 0, "expired": 0})  # دوباره نمی‌گوید
        e.refresh_from_db()
        self.assertEqual(e.notified, 1)
        Entitlement.objects.update(expires_at=timezone.now() - datetime.timedelta(minutes=5))
        self.assertEqual(market_jobs.tick(), {"warned": 0, "expired": 1})
        self.assertIn("به پایان رسید", self.notify.call_args.args[2])
        self.assertEqual(market_jobs.tick(), {"warned": 0, "expired": 0})

    def test_renewal_resets_notifications(self):
        self.grant(24)
        market_jobs.tick()
        e = entitlements.grant("fleet", "workspace", str(self.db.pk), source="purchase", days=30)
        self.assertEqual(e.notified, 0)
        self.assertEqual(market_jobs.tick(), {"warned": 0, "expired": 0})  # حالا ۳۰ روز مانده

    def test_far_manual_unlimited_and_other_sources_are_ignored(self):
        self.grant(24 * 30)  # دور
        e = self.grant(24 * 2, source="manual")  # دستی: پیامی ندارد
        e.subject = "999"
        e.save()
        Entitlement.objects.create(state=PluginState.objects.get(plugin_id="fleet"), kind="all", source="purchase", expires_at=None)
        self.assertEqual(market_jobs.tick(), {"warned": 0, "expired": 0})

    def test_user_scope_and_unknown_owner(self):
        self.grant(24, kind="user", subject=str(self.user.pk), source="trial")
        self.assertEqual(market_jobs.tick()["warned"], 1)
        self.assertIn("آزمایشی", self.notify.call_args.args[2])
        self.notify.reset_mock()
        e = self.grant(24, kind="org", subject="1")
        self.assertEqual(market_jobs.tick(), {"warned": 1, "expired": 0})  # شمرده می‌شود ولی گیرنده ندارد
        self.assertFalse(self.notify.called)
        e.refresh_from_db()
        self.assertEqual(e.notified, 1)

    def test_notify_failure_does_not_break_the_tick(self):
        self.grant(24)
        self.notify.side_effect = RuntimeError("sms down")
        self.assertEqual(market_jobs.tick(), {"warned": 1, "expired": 0})

    def test_registered_as_periodic_job(self):
        from kernel import jobs

        self.assertIn("billing.market_jobs.tick", [c.value for c in registry.contributions(jobs.TICK)])
