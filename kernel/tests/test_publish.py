"""انتشار پلاگین از ویزارد: مهر «panel»، دسترسی و قیمت، تأیید نفر دوم (ADR-0008 مرحله‌ی ۵)."""
import base64
import io
import json
import zipfile

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from kernel import entitlements, market, pkg, platform, publish, studio
from kernel.models import Entitlement, Organization, PluginDraft, PluginRelease, PluginState
from kernel.plugins import registry
from kernel.tests.test_wizard_admin import TBL


def cleanup_loaded():
    for p in list(pkg._loaded):
        registry.remove_plugin(p)
        pkg._loaded.pop(p, None)


class SealTests(SimpleTestCase):
    FILES = {"plugin.toml": b'id = "x"\n', "pages/a.toml": b"key = 'a'\n"}

    def test_seal_verifies_and_detects_tampering(self):
        files = {**self.FILES}
        files[pkg.SIG_NAME] = pkg.seal(files)
        self.assertEqual(pkg.verify(files, {}), "panel")
        files["pages/a.toml"] = b"key = 'b'\n"
        with self.assertRaises(pkg.PackageError):
            pkg.verify(files, {})

    def test_other_server_key_is_rejected(self):
        files = {**self.FILES}
        with override_settings(SECRET_KEY="server-one-" + "x" * 30):
            files[pkg.SIG_NAME] = pkg.seal(files)
        with override_settings(SECRET_KEY="server-two-" + "y" * 30), self.assertRaises(pkg.PackageError):
            pkg.verify(files, {})

    def test_panel_name_cannot_be_forged_with_ed25519_or_other_hmac_publisher(self):
        files = {**self.FILES}
        files[pkg.SIG_NAME] = json.dumps({"publisher": "panel", "alg": "ed25519", "sig": base64.b64encode(b"x" * 64).decode()}).encode()
        with self.assertRaises(pkg.PackageError):
            pkg.verify(files, {})
        files[pkg.SIG_NAME] = json.dumps({"publisher": "acme", "alg": "hmac-sha256", "sig": base64.b64encode(b"x" * 32).decode()}).encode()
        with self.assertRaises(pkg.PackageError):
            pkg.verify(files, {})
        files[pkg.SIG_NAME] = json.dumps({"publisher": "panel", "alg": "hmac-sha256", "sig": base64.b64encode(b"x" * 32).decode()}).encode()
        with self.assertRaises(pkg.PackageError):
            pkg.verify(files, {})


class AccessTests(SimpleTestCase):
    def test_modes(self):
        self.assertEqual(publish.normalize_access({"mode": "public_free", "price_toman": 5}), {"mode": "public_free"})
        paid = publish.normalize_access({"mode": "public_paid", "price_toman": "90000", "duration_days": "30", "scope": "user",
                                         "trial_days": "7", "limits": {"page_views_per_month": 100, "evil": 1}})
        self.assertEqual((paid["price_toman"], paid["scope"], paid["trial_days"], paid["limits"]), (90000, "user", 7, {"page_views_per_month": 100}))
        priv = publish.normalize_access({"mode": "private", "targets": [{"kind": "org", "subject": "3", "days": "30"}, {"kind": "plan", "subject": "pro"}]})
        self.assertEqual(priv["targets"][0]["days"], 30)
        self.assertIsNone(priv["targets"][1]["days"])

    def test_rejections(self):
        for bad in ({}, {"mode": "x"}, {"mode": "public_paid", "price_toman": 0}, {"mode": "public_paid", "price_toman": "abc"},
                    {"mode": "public_paid", "price_toman": 5, "scope": "world"}, {"mode": "public_paid", "price_toman": 5, "trial_days": 400},
                    {"mode": "public_paid", "price_toman": 5, "duration_days": 0}, {"mode": "private", "targets": []},
                    {"mode": "private", "targets": [{"kind": "alien", "subject": "1"}]}, {"mode": "private", "targets": [{"kind": "org", "subject": ""}]},
                    {"mode": "private", "targets": [{"kind": "org", "subject": "1", "days": "x"}]},
                    {"mode": "private", "targets": [{"kind": "org", "subject": "1", "days": 99999}]}):
            with self.subTest(bad=bad), self.assertRaises(publish.PublishError):
                publish.normalize_access(bad)


@override_settings(ADMIN_2FA_REQUIRED=False)
class PublishFlowTests(TestCase):
    def setUp(self):
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(cleanup_loaded)
        self.addCleanup(platform.invalidate)
        self.su = get_user_model().objects.create_superuser("pubroot", "Str0ng-Admin-Pass")
        self.client.force_login(self.su)
        self.client.post(reverse("admin:kernel_plugindraft_wizard_new"), {
            "name": "مانیتورینگ آنلاین", "plugin_id": "monitoring", "summary": "پایش زنده", "description": "", "icon": "pulse"})
        self.draft = PluginDraft.objects.get(plugin_id="monitoring")
        self.step = lambda n: reverse("admin:kernel_plugindraft_wizard", args=[self.draft.pk, n])
        self.client.post(self.step(2), TBL)
        self.client.post(self.step(4), {"op": "addpage", "title": "پایش", "icon": "pulse"})
        self.client.post(self.step(4), {"op": "addblock:p1", "kind": "kpi", "title": "تعداد", "table": "monitoring_points", "agg": "count"})
        self.client.post(self.step(4), {"op": "addblock:p1", "kind": "ingest", "table": "monitoring_points", "fields": ["device", "lat", "lon"]})

    def publish(self, access):
        r = self.client.post(self.step(5), access)
        self.assertEqual(r.status_code, 302, r.content[:200])
        return self.client.post(self.step(6), {"op": "publish"})

    def test_public_free_is_active_open_and_reachable(self):
        self.publish({"mode": "public_free"})
        rel = PluginRelease.objects.get(plugin_id="monitoring")
        self.assertEqual((rel.status, rel.publisher, rel.version, rel.access["mode"]), ("active", "panel", "1.0.0", "public_free"))
        st = PluginState.objects.get(plugin_id="monitoring")
        self.assertEqual((st.enabled, st.access), (True, "open"))
        self.assertIn("monitoring", registry.plugins)
        self.assertEqual(registry.plugins["monitoring"].version, "1.0.0")
        self.assertTrue(entitlements.allowed("monitoring"))

    def test_republish_bumps_version_and_keeps_previous_for_rollback(self):
        self.publish({"mode": "public_free"})
        self.publish({"mode": "public_free"})
        vers = sorted(PluginRelease.objects.filter(plugin_id="monitoring").values_list("version", "status"))
        self.assertEqual(vers, [("1.0.0", "retired"), ("1.0.1", "active")])
        self.assertEqual(registry.plugins["monitoring"].version, "1.0.1")

    def test_private_grants_only_chosen_targets(self):
        org = Organization.objects.create(name="شرکت نمونه", slug="sample")
        self.publish({"mode": "private", "t_kind": ["org"], "t_subject": [str(org.pk)], "t_days": ["30"]})
        st = PluginState.objects.get(plugin_id="monitoring")
        self.assertEqual(st.access, "restricted")
        g = Entitlement.objects.get(state=st)
        self.assertEqual((g.kind, g.subject, g.source), ("org", str(org.pk), "manual"))
        self.assertIsNotNone(g.expires_at)
        self.assertFalse(entitlements.allowed("monitoring"))  # بدون مجوز دیده نمی‌شود

    def test_private_unknown_target_is_rejected(self):
        r = self.client.post(self.step(5), {"mode": "private", "t_kind": ["org"], "t_subject": ["999999"], "t_days": [""]})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("access", PluginDraft.objects.get(pk=self.draft.pk).wizard)

    def test_public_paid_creates_listing_via_billing(self):
        from billing.models import PluginAddon

        self.publish({"mode": "public_paid", "price_toman": "120000", "duration_days": "90", "scope": "user", "trial_days": "7",
                      "page_views_per_month": "5000"})
        st = PluginState.objects.get(plugin_id="monitoring")
        self.assertEqual(st.access, "restricted")
        a = PluginAddon.objects.get(plugin_id="monitoring")
        self.assertEqual((a.price_toman, a.duration_days, a.scope, a.trial_days, a.is_public, a.title), (120000, 90, "user", 7, True, "مانیتورینگ آنلاین"))
        self.assertEqual(a.limits, {"page_views_per_month": 5000})
        self.assertEqual(a.description, "پایش زنده")
        # بازانتشار به رایگان آگهی را از فروشگاه برمی‌دارد
        self.publish({"mode": "public_free"})
        a.refresh_from_db()
        self.assertFalse(a.is_public)

    def test_incomplete_draft_is_not_published(self):
        self.client.post(self.step(4), {"op": "delpage:p1"})
        self.publish({"mode": "public_free"})
        self.assertFalse(PluginRelease.objects.filter(plugin_id="monitoring").exists())

    def test_second_approval_keeps_release_pending_until_another_admin_approves(self):
        platform.set_("require_second_approval", "1")
        out = self.publish({"mode": "public_free"})
        self.assertEqual(out.status_code, 302)
        rel = PluginRelease.objects.get(plugin_id="monitoring")
        self.assertEqual(rel.status, "checked")
        self.assertNotIn("monitoring", registry.plugins)
        self.assertIn("بارگذارنده", pkg.can_approve(rel, self.su))
        other = get_user_model().objects.create_superuser("pubroot2", "Str0ng-Admin-Pass")
        self.assertEqual(pkg.can_approve(rel, other), "")
        pkg.activate(rel, other)  # دسترسی هنگام فعال‌شدن اعمال می‌شود
        self.assertEqual(PluginState.objects.get(plugin_id="monitoring").access, "open")

    def test_without_second_approval_external_packages_still_need_two_people(self):
        rel = PluginRelease.objects.create(plugin_id="ext1", version="1.0.0", sha256="a" * 64, blob=b"x", status="checked",
                                           publisher="acme", uploaded_by=self.su)
        self.assertIn("بارگذارنده", pkg.can_approve(rel, self.su))  # فقط ساخته‌ی ویزارد معاف است

    def test_step5_and_4_render_and_publish_requires_fresh_2fa(self):
        from kernel import stepup

        self.client.post(self.step(5), {"mode": "public_free"})
        r = self.client.get(self.step(6))
        self.assertContains(r, "بررسی خودکار بسته")
        self.assertContains(r, "1.0.0")
        self.assertEqual(self.client.get(self.step(5)).status_code, 200)

        class Deny(stepup.Provider):
            def ok(self, request):
                return False

            def url(self, request):
                return "/fresh/"

        old = stepup._provider
        stepup.set_provider(Deny())
        self.addCleanup(lambda: setattr(stepup, "_provider", old))
        r = self.client.post(self.step(6), {"op": "publish"})
        self.assertEqual(r["Location"], "/fresh/")
        self.assertFalse(PluginRelease.objects.exists())

    def test_platform_page_toggles_second_approval(self):
        url = "/manage/kernel/publisherkey/"
        self.client.post(url, {"action": "save_publish", "require_second_approval": "1"})
        self.assertTrue(pkg.second_approval_required())
        self.client.post(url, {"action": "save_publish"})
        self.assertFalse(pkg.second_approval_required())

    def test_sealed_package_is_a_normal_package(self):
        z = zipfile.ZipFile(io.BytesIO(studio.sealed_zip(self.draft)))
        self.assertIn("SIGNATURE", z.namelist())
        self.assertIn("plugin.toml", z.namelist())

    def test_market_without_provider_is_a_clear_error(self):
        saved = registry._points.get(market.POINT)
        registry._points.pop(market.POINT, None)
        self.addCleanup(lambda: registry._points.__setitem__(market.POINT, saved) if saved is not None else None)
        with self.assertRaises(market.MarketError):
            market.upsert("billing", market.Listing(title="x", price_toman=5))
