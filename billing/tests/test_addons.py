from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing import services
from billing.models import Invoice, PluginAddon
from kernel import entitlements
from kernel.models import Entitlement, PluginState
from kernel.plugins import registry

from .test_billing import BillingTests as _Base


class AddonBillingTests(TestCase):
    def setUp(self):
        _Base.setUp(self)  # فقط ساخت کاربر، پایگاه داده و تنظیم فروش؛ آزمون‌های پلن دوباره اجرا نمی‌شوند
        registry.register("fleet", "ناوگان", kind="custom")
        self.addCleanup(registry.remove_plugin, "fleet")
        self.addCleanup(entitlements.invalidate)
        self.addon = PluginAddon.objects.create(plugin_id="fleet", title="پایش ناوگان", price_toman=90000, duration_days=30,
                                                limits={"page_views_per_month": 500})
        entitlements.invalidate()

    def test_buy_workspace_addon_grants_entitlement(self):
        inv = services.create_addon_invoice(self.user, self.addon, self.db)
        self.assertEqual((inv.kind, inv.plan_id, inv.amount_toman), ("addon", None, 90000))
        self.assertIn("پایش ناوگان", inv.title)
        services.mark_paid(inv)
        inv.refresh_from_db()
        self.assertIsNotNone(inv.applied_at)
        PluginState.objects.filter(plugin_id="fleet").update(access="restricted")
        entitlements.invalidate()
        self.assertTrue(entitlements.allowed("fleet", user=self.user, ws=self.db))
        self.assertEqual(entitlements.limits("fleet", user=self.user, ws=self.db)["page_views_per_month"], 500)
        ent = Entitlement.objects.get(state__plugin_id="fleet")
        self.assertEqual((ent.kind, ent.subject, ent.source), ("workspace", str(self.db.pk), "purchase"))
        self.assertIn(inv.number, ent.note)

    def test_renewal_extends_not_resets(self):
        for _ in range(2):
            inv = services.create_addon_invoice(self.user, self.addon, self.db)
            services.mark_paid(inv)
            inv.status = Invoice.Status.CANCELLED  # تا فاکتور تازه ساخته شود
            inv.save()
        ent = Entitlement.objects.get(state__plugin_id="fleet")
        left = (ent.expires_at - timezone.now()).days
        self.assertGreaterEqual(left, 58)

    def test_user_scope_and_double_apply_is_noop(self):
        self.addon.scope = PluginAddon.Scope.USER
        self.addon.save()
        inv = services.create_addon_invoice(self.user, self.addon)
        services.mark_paid(inv)
        services.mark_paid(inv)
        inv.refresh_from_db()
        services.apply_invoice(inv)
        ent = Entitlement.objects.get(state__plugin_id="fleet")
        self.assertEqual((ent.kind, ent.subject), ("user", str(self.user.pk)))
        self.assertLessEqual((ent.expires_at - timezone.now()).days, 30)

    def test_guards(self):
        other = type(self.user).objects.create_user("09125550000")
        with self.assertRaises(services.BillingError):
            services.create_addon_invoice(other, self.addon, self.db)  # پایگاه داده‌ی دیگری
        with self.assertRaises(services.BillingError):
            services.create_addon_invoice(self.user, self.addon, None)  # پایگاه داده لازم است
        self.addon.is_public = False
        self.addon.save()
        with self.assertRaises(services.BillingError):
            services.create_addon_invoice(self.user, self.addon, self.db)

    def test_system_or_missing_plugin_not_sold(self):
        a = PluginAddon.objects.create(plugin_id="billing", title="سیستمی", price_toman=1)
        b = PluginAddon.objects.create(plugin_id="ghost", title="نصب‌نشده", price_toman=1)
        names = {x.title for x in services.public_addons()}
        self.assertNotIn(a.title, names)
        self.assertNotIn(b.title, names)

    def test_start_addon_view(self):
        r = self.client.post(reverse("billing:start_addon"), {"addon": self.addon.pk, "target": self.db.pk})
        inv = Invoice.objects.get(kind="addon")
        self.assertRedirects(r, reverse("billing:invoice", args=[inv.number]), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("billing:invoice", args=[inv.number])), "پایش ناوگان")
        page = self.client.get(reverse("billing:plans"))
        self.assertContains(page, "پایش ناوگان")

    def test_entitlement_grant_validation(self):
        with self.assertRaises(ValueError):
            entitlements.grant("billing", "user", "1")
        with self.assertRaises(ValueError):
            entitlements.grant("fleet", "user", "")
        with self.assertRaises(ValueError):
            entitlements.grant("fleet", "nope", "1")
