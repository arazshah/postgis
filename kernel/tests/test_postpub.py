"""آمار پس از انتشار (ADR-0010 مرحله‌ی ۱۰): شمارنده‌ها، فروش، مصرف، سلامت؛ بدون هیچ نشانی از مشتری."""
import datetime
import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice, PluginAddon
from kernel import ai, entitlements, postpub, studio_ai
from kernel.models import Entitlement, PluginDraft, PluginRelease, PluginState, PluginTrip, PluginUsage
from kernel.plugins import registry
from kernel.tests.test_studio_ai import Fake

PID = "fleet"


@override_settings(ADMIN_2FA_REQUIRED=False)
class PostPubTests(TestCase):
    def setUp(self):
        registry.register(PID, "ناوگان", kind="custom", description="پایش")
        self.addCleanup(registry.remove_plugin, PID)
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(ai.set_provider, ai._provider)
        self.su = get_user_model().objects.create_superuser("psroot", "Str0ng-Admin-Pass")
        self.client.force_login(self.su)
        self.state = PluginState.objects.create(plugin_id=PID, access="restricted")
        self.addon = PluginAddon.objects.create(plugin_id=PID, title="ناوگان", price_toman=90000, trial_days=7, limits={"page_views_per_month": 100})

    def ent(self, kind, subject, source, days=30, **kw):
        return Entitlement.objects.create(state=self.state, kind=kind, subject=str(subject), source=source,
                                          expires_at=None if days is None else timezone.now() + datetime.timedelta(days=days), **kw)

    def test_empty_plugin(self):
        s = postpub.collect(PID)
        self.assertFalse(s["published"])
        self.assertEqual((s["customers"]["active"], s["usage"], s["near_limit"]), (0, {}, 0))
        self.assertEqual(s["health"], {"trips_30d": 0, "unseen": 0, "last": None})

    def test_customers_and_expiry(self):
        self.ent("workspace", 1, "trial", days=3)
        self.ent("workspace", 2, "purchase", days=40)
        self.ent("user", 3, "purchase", days=None)
        self.ent("workspace", 4, "purchase", days=-5)        # منقضی در ۳۰ روز اخیر
        self.ent("workspace", 5, "purchase", days=-90)       # قدیمی: شمرده نمی‌شود
        c = postpub.collect(PID)["customers"]
        self.assertEqual((c["active"], c["trial"], c["purchase"], c["expiring_7d"], c["expired_30d"]), (3, 1, 2, 1, 1))

    def test_usage_series_and_near_limit(self):
        self.ent("workspace", 7, "purchase", limits={"page_views_per_month": 100})
        self.ent("workspace", 8, "purchase", limits={"page_views_per_month": 100})
        today = timezone.localdate()
        PluginUsage.objects.create(plugin_id=PID, metric="page_views", day=today, workspace_id=7, count=90)
        PluginUsage.objects.create(plugin_id=PID, metric="page_views", day=today - datetime.timedelta(days=2), workspace_id=8, count=10)
        PluginUsage.objects.create(plugin_id=PID, metric="form_submits", day=today, workspace_id=7, count=3)
        PluginUsage.objects.create(plugin_id=PID, metric="page_views", day=today - datetime.timedelta(days=60), workspace_id=9, count=999)  # بیرون پنجره
        s = postpub.collect(PID)
        pv = s["usage"]["page_views"]
        self.assertEqual((pv["total_30d"], pv["workspaces"], len(pv["series"]), pv["series"][-1], pv["series"][-3]), (100, 2, postpub.SERIES_DAYS, 90, 10))
        self.assertEqual(s["usage"]["form_submits"]["total_30d"], 3)
        self.assertEqual(s["near_limit"], 1)  # فقط پایگاه ۷ (۹۰٪)

    def test_sales_from_billing_provider(self):
        u = get_user_model().objects.create_user(email="buyer@example.com", password="x" * 12)
        for amount, ago in ((90000, 2), (90000, 40), (180000, 70)):
            inv = Invoice.objects.create(number=f"T{amount}{ago}", user=u, kind="addon", addon=self.addon, amount_toman=amount, status="paid", paid_at=timezone.now() - datetime.timedelta(days=ago), expires_at=timezone.now())
            assert inv.pk
        Invoice.objects.create(number="TOPEN", user=u, kind="addon", addon=self.addon, amount_toman=90000, status="pending", expires_at=timezone.now())
        sales = postpub.collect(PID)["sales"]
        self.assertEqual((sales["invoices_paid"], sales["revenue_total"], sales["revenue_30d"], sales["invoices_30d"], sales["invoices_open"]), (3, 360000, 90000, 1, 1))
        self.assertTrue(sales["months"] and all({"month", "count", "amount"} <= set(m) for m in sales["months"]))
        self.assertEqual(postpub.collect("nope")["sales"], {"listed": False})

    def test_health_and_versions(self):
        r = PluginRelease.objects.create(plugin_id=PID, version="1.0.0", sha256="a" * 64, blob=b"", status="active", notes="نخست")
        PluginRelease.objects.create(plugin_id=PID, version="0.9.0", sha256="b" * 64, blob=b"", status="rejected")
        PluginTrip.objects.create(plugin_id=PID, release=r, version="1.0.0", action="rollback", runs=50, errors=40)
        s = postpub.collect(PID)
        self.assertEqual([v["version"] for v in s["versions"]], ["1.0.0"])  # ردشده نمی‌آید
        self.assertEqual((s["published"], s["active_version"], s["health"]["trips_30d"], s["health"]["unseen"], s["health"]["last"]["action"]), (True, "1.0.0", 1, 1, "rollback"))

    def test_nothing_identifying_leaves_the_server(self):
        u = get_user_model().objects.create_user(email="secret-customer@example.com", password="x" * 12)
        self.ent("workspace", 4242, "purchase", limits={"page_views_per_month": 5})
        Invoice.objects.create(number="TZ", user=u, kind="addon", addon=self.addon, amount_toman=90000, status="paid", paid_at=timezone.now(), expires_at=timezone.now())
        PluginUsage.objects.create(plugin_id=PID, metric="page_views", day=timezone.localdate(), workspace_id=4242, count=9)
        text = json.dumps(postpub.collect(PID), ensure_ascii=False)
        for needle in ("secret-customer", "example.com", "4242", "TZ"):
            self.assertNotIn(needle, text)

    def test_api_and_assistant_mode(self):
        d = PluginDraft.objects.create(plugin_id=PID, name="ناوگان", wizard={"intro": {}, "tables": [], "pages": [], "code": {}})
        self.ent("workspace", 1, "trial", days=3)
        got = self.client.get(reverse("admin:kernel_plugindraft_api_stats", args=[d.pk])).json()
        self.assertEqual(got["customers"]["trial"], 1)
        fake = Fake({"reply": "خلاصه", "ops": []})
        ai.set_provider(fake)
        r = self.client.post(reverse("admin:kernel_plugindraft_api_assistant", args=[d.pk]), json.dumps({"mode": "postpub", "message": "جمع‌بندی"}), content_type="application/json").json()
        self.assertEqual(r["reply"], "خلاصه")
        ctx = fake.calls[0][1][1]["content"]
        self.assertIn('"postpub"', ctx)
        self.assertIn('"trial": 1', ctx)
        # در حالت‌های دیگر آمار به مدل نمی‌رود
        fake2 = Fake({"reply": "x", "ops": []})
        ai.set_provider(fake2)
        studio_ai.ask(None, d.wizard, PID, "سلام", mode="chat", stats={"customers": {"active": 99}})
        self.assertNotIn("postpub", fake2.calls[0][1][1]["content"])

    def test_permissions(self):
        d = PluginDraft.objects.create(plugin_id=PID, name="ناوگان", wizard={})
        self.client.logout()
        u = get_user_model().objects.create_admin("psstaff", "Str0ng-Admin-Pass", superuser=False)
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse("admin:kernel_plugindraft_api_stats", args=[d.pk])).status_code, 403)
