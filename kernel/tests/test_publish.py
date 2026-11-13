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


POINTS = {"name": "monitoring_points", "columns": [
    {"name": "device", "type": "text", "required": True, "label": "دستگاه"}, {"name": "lat", "type": "double", "min": -90, "max": 90, "required": True, "label": "عرض"},
    {"name": "lon", "type": "double", "min": -180, "max": 180, "required": True, "label": "طول"}, {"name": "speed", "type": "double", "label": "سرعت"},
    {"name": "at", "type": "timestamptz", "auto_now": True}], "indexes": [["device", "at"]]}


@override_settings(ADMIN_2FA_REQUIRED=False)
class PublishFlowTests(TestCase):
    def setUp(self):
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(cleanup_loaded)
        self.addCleanup(platform.invalidate)
        self.su = get_user_model().objects.create_superuser("pubroot", "Str0ng-Admin-Pass")
        self.client.force_login(self.su)
        r = self.client.post(reverse("admin:kernel_plugindraft_new"), {"name": "مانیتورینگ آنلاین", "plugin_id": "monitoring", "summary": "پایش زنده", "icon": "pulse", "recipe": "blank"})
        self.assertEqual(r.status_code, 302)
        self.draft = PluginDraft.objects.get(plugin_id="monitoring")
        self.api("op", {"ops": [{"op": "table.add", "table": POINTS}, {"op": "page.add", "title": "پایش", "icon": "pulse", "blocks": [
            {"kind": "kpi", "title": "تعداد", "table": "monitoring_points", "agg": "count"},
            {"kind": "ingest", "title": "دریافت", "table": "monitoring_points", "fields": ["device", "lat", "lon"]}]}]})

    def api(self, name, body=None):
        url = reverse(f"admin:kernel_plugindraft_api_{name}", args=[self.draft.pk])
        return self.client.get(url) if body is None else self.client.post(url, json.dumps(body), content_type="application/json")

    def publish(self, access, notes=""):
        r = self.api("access", {"access": access})
        self.assertEqual(r.status_code, 200, r.content[:300])
        return self.api("publish", {"notes": notes})

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
        self.publish({"mode": "private", "targets": [{"kind": "org", "subject": str(org.pk), "days": 30}]})
        st = PluginState.objects.get(plugin_id="monitoring")
        self.assertEqual(st.access, "restricted")
        g = Entitlement.objects.get(state=st)
        self.assertEqual((g.kind, g.subject, g.source), ("org", str(org.pk), "manual"))
        self.assertIsNotNone(g.expires_at)
        self.assertFalse(entitlements.allowed("monitoring"))  # بدون مجوز دیده نمی‌شود

    def test_private_unknown_target_is_rejected(self):
        r = self.api("access", {"access": {"mode": "private", "targets": [{"kind": "org", "subject": "999999", "days": ""}]}})
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("access", PluginDraft.objects.get(pk=self.draft.pk).wizard)

    def test_public_paid_creates_listing_via_billing(self):
        from billing.models import PluginAddon

        self.publish({"mode": "public_paid", "price_toman": 120000, "duration_days": 90, "scope": "user", "trial_days": 7, "limits": {"page_views_per_month": 5000}})
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
        self.api("op", {"op": "page.del", "key": "p1"})
        r = self.publish({"mode": "public_free"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(PluginRelease.objects.filter(plugin_id="monitoring").exists())

    def test_second_approval_keeps_release_pending_until_another_admin_approves(self):
        platform.set_("require_second_approval", "1")
        out = self.publish({"mode": "public_free"})
        self.assertEqual((out.status_code, out.json()["active"]), (200, False))
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
        self.assertIn("بارگذارنده", pkg.can_approve(rel, self.su))  # فقط ساخته‌ی استودیو معاف است

    def test_designer_renders_and_publish_requires_fresh_2fa(self):
        from kernel import stepup

        self.assertEqual(self.client.get(reverse("admin:kernel_plugindraft_designer", args=[self.draft.pk])).status_code, 200)
        self.api("access", {"access": {"mode": "public_free"}})

        class Deny(stepup.Provider):
            def ok(self, request):
                return False

            def url(self, request):
                return "/fresh/"

        old = stepup._provider
        stepup.set_provider(Deny())
        self.addCleanup(lambda: setattr(stepup, "_provider", old))
        r = self.api("publish", {})
        self.assertEqual((r.status_code, r.json()["stepup"]), (403, "/fresh/"))
        self.assertFalse(PluginRelease.objects.exists())

    def test_platform_page_toggles_second_approval(self):
        url = "/manage/kernel/publisherkey/"
        self.client.post(url, {"action": "save_publish", "require_second_approval": "1"})
        self.assertTrue(pkg.second_approval_required())
        self.client.post(url, {"action": "save_publish"})
        self.assertFalse(pkg.second_approval_required())

    def test_sealed_package_is_a_normal_package(self):
        self.draft.refresh_from_db()
        z = zipfile.ZipFile(io.BytesIO(studio.sealed_zip(self.draft)))
        self.assertIn("SIGNATURE", z.namelist())
        self.assertIn("plugin.toml", z.namelist())

    def test_upload_only_staff_cannot_publish_directly(self):
        from django.contrib.auth.models import Permission

        staff = get_user_model().objects.create_admin("pubstaff", "Str0ng-Admin-Pass", superuser=False)
        staff.user_permissions.add(*Permission.objects.filter(codename__in=["upload_pluginrelease", "view_pluginstate", "change_plugindraft", "view_plugindraft"]))
        self.api("access", {"access": {"mode": "public_free"}})
        self.client.force_login(staff)
        r = self.api("publish", {})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(PluginRelease.objects.exists())
        platform.set_("require_second_approval", "1")  # با تأیید نفر دوم همان نویسنده فقط ثبت می‌کند
        self.api("publish", {})
        rel = PluginRelease.objects.get()
        self.assertEqual(rel.status, "checked")

    def test_market_without_provider_is_a_clear_error(self):
        saved = registry._points.get(market.POINT)
        registry._points.pop(market.POINT, None)
        self.addCleanup(lambda: registry._points.__setitem__(market.POINT, saved) if saved is not None else None)
        with self.assertRaises(market.MarketError):
            market.upsert("billing", market.Listing(title="x", price_toman=5))
