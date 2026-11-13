"""ویترین بازارچه پلاگین (ADR-0011): هر پلاگین قابلیت پروفایل کامل دارد؛ بازارچه عمومی و در صفحه‌ی اول و نقشه‌ی سایت است."""
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from kernel import showcase
from kernel.plugins import registry


class ShowcaseContractTests(TestCase):
    def _feature_ids(self):
        return sorted(pid for pid, p in registry.plugins.items() if p.kind == "feature" and p.tier != 3 and not pid.startswith("x_"))

    def test_every_feature_plugin_has_a_complete_profile(self):
        """پلاگین قابلیت تازه بدون پروفایل ویترین، بازارچه را خالی نشان می‌دهد؛ این آزمون جلویش را می‌گیرد."""
        for pid in self._feature_ids():
            sc = showcase.get(pid)
            self.assertIsNotNone(sc, f"پروفایل ویترین برای {pid} ثبت نشده (showcase.add در plugin.py)")
            self.assertGreaterEqual(len(sc.features), 3, pid)
            self.assertGreaterEqual(len(sc.details), 120, pid)
            self.assertTrue(sc.audiences and len(sc.steps) == 3, pid)

    def test_profile_links_are_valid(self):
        from core.help import GUIDES

        slugs = {g.slug for g in GUIDES}
        kb = {p.stem for p in (Path(settings.BASE_DIR) / "kb" / "content").rglob("*.md")}
        for pid in self._feature_ids() + ["assistant"]:
            sc = showcase.get(pid)
            for slug, _t in sc.guides:
                self.assertIn(slug, slugs, f"{pid}: راهنمای {slug} نیست")
            for slug, _t in sc.kb:
                self.assertIn(slug, kb, f"{pid}: مقاله‌ی {slug} نیست")
            if sc.video:
                self.assertIn(sc.video, slugs, pid)

    def test_every_plugin_has_images(self):
        """پلاگین صفحه‌دار ۲ تصویر رابط؛ پلاگین قابلیت (بدون صفحه‌ی مستقل) دست‌کم یک کاور."""
        for pid in self._feature_ids():
            need = 1 if pid.startswith("cap_") else 2
            self.assertGreaterEqual(len(showcase.images(pid)), need, f"{pid}: تصویر ویترین (static/market/{pid}) نیست")

    def test_admin_add_page_renders(self):
        from accounts.models import User

        self.client.force_login(User.objects.create_user(email="boss@example.com", password="x", is_staff=True, is_superuser=True))
        with self.settings(ADMIN_2FA_REQUIRED=False):
            r = self.client.get(reverse("admin:kernel_pluginshowcaseoverride_add"))
        self.assertContains(r, "ویژگی‌ها")

    def test_invalid_profile_rejected(self):
        with self.assertRaises(ValueError):
            showcase.Showcase(tagline="x", category="nope", features=("a", "b", "c")).validate()
        with self.assertRaises(ValueError):
            showcase.Showcase(tagline="x", category="data", features=("a",)).validate()


class PublicMarketTests(TestCase):
    def test_market_is_public_and_rich(self):
        r = self.client.get(reverse("plugins"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ورود فایل")
        self.assertContains(r, "/static/market/")  # تصویر واقعی، نه جای‌نگهدار خالی
        self.assertContains(r, "مناسب:")

    def test_detail_shows_steps_guides_and_jsonld(self):
        r = self.client.get(reverse("plugin_detail", args=["dbimport"]))
        self.assertContains(r, "در سه گام شروع کنید")
        self.assertContains(r, reverse("core:help_page", args=["import"]))
        self.assertContains(r, "SoftwareApplication")
        self.assertContains(r, "<video")

    def test_home_links_to_market(self):
        r = self.client.get(reverse("core:home"))
        self.assertContains(r, reverse("plugins"))
        self.assertContains(r, "بازارچه پلاگین")

    def test_sitemap_lists_market(self):
        r = self.client.get(reverse("core:sitemap"))
        self.assertContains(r, "/plugins/")
        self.assertContains(r, "/plugins/dbimport/")

    def test_system_plugin_without_profile_is_hidden(self):
        self.assertEqual(self.client.get(reverse("plugin_detail", args=["accounts"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("plugin_detail", args=["assistant"])).status_code, 200)  # همراه سکو


class AudiencePagesTests(TestCase):
    def test_every_audience_has_a_landing_page_with_plugins(self):
        for key, (title, _pitch) in showcase.AUDIENCE_PITCH.items():
            r = self.client.get(reverse("plugin_audience", args=[key]))
            self.assertEqual(r.status_code, 200, key)
            self.assertContains(r, title)
            self.assertContains(r, "data-lf-row", msg_prefix=key)  # هر مخاطب دست‌کم یک پلاگین دارد

    def test_audience_page_lists_only_matching_plugins_and_is_in_sitemap(self):
        r = self.client.get(reverse("plugin_audience", args=["edu"]))
        self.assertContains(r, "کلاس درس")
        self.assertNotContains(r, "REST API و فرم میدانی")
        self.assertEqual(self.client.get(reverse("plugin_audience", args=["nope"])).status_code, 404)
        self.assertContains(self.client.get(reverse("core:sitemap")), "/plugins/for/edu/")

    def test_pitch_covers_all_audiences(self):
        self.assertEqual(set(showcase.AUDIENCE_PITCH), {k for k, _l in showcase.AUDIENCES})


class PlanBundleTests(TestCase):
    def test_plan_page_and_home_show_bundled_plugins(self):
        from databases.models import Plan
        from kernel import entitlements
        from kernel.models import Entitlement, PluginState

        self.addCleanup(entitlements.invalidate)
        plan = Plan.objects.create(name="طلایی", slug="gold", is_public=True, is_free=False, price_toman=1000)
        st = PluginState.objects.create(plugin_id="survey", access="restricted")
        Entitlement.objects.create(state=st, kind=Entitlement.Kind.PLAN, subject="gold", source=Entitlement.Source.PLAN)
        out = showcase.bundled_with_plan(["gold"])
        self.assertEqual([x["id"] for x in out["gold"]], ["survey"])
        self.assertContains(self.client.get(reverse("core:home")), "پلاگین‌های همراه")
        self.assertEqual(plan.slug, "gold")


class ShowcaseOverrideTests(TestCase):
    def setUp(self):
        self.addCleanup(showcase.invalidate)
        showcase.invalidate()

    def test_override_wins_only_where_filled_and_hidden_removes_from_market(self):
        from kernel.models import PluginShowcaseOverride

        base = showcase.code_profile("dbimport")
        PluginShowcaseOverride.objects.create(plugin_id="dbimport", tagline="شعار تازه از پنل", features=["الف", "ب", "ج"])
        sc = showcase.get("dbimport")
        self.assertEqual((sc.tagline, sc.features), ("شعار تازه از پنل", ("الف", "ب", "ج")))
        self.assertEqual(sc.details, base.details)  # فیلد خالی = پیش‌فرض کد
        self.assertContains(self.client.get(reverse("plugin_detail", args=["dbimport"])), "شعار تازه از پنل")
        PluginShowcaseOverride.objects.filter(plugin_id="dbimport").update(hidden=True)
        showcase.invalidate()
        self.assertNotContains(self.client.get(reverse("plugins")), 'href="/plugins/dbimport/"')
        self.assertEqual(self.client.get(reverse("plugin_detail", args=["dbimport"])).status_code, 404)

    def test_featured_override_controls_home(self):
        from kernel.models import PluginShowcaseOverride

        PluginShowcaseOverride.objects.create(plugin_id="dbimport", featured=0)
        self.assertNotIn("dbimport", [r["id"] for r in showcase.home_picks(9)])

    def test_admin_form_validates_features(self):
        from kernel.admin import ShowcaseOverrideForm

        f = ShowcaseOverrideForm(data={"plugin_id": "dbimport", "features_text": "فقط یکی", "tagline": "", "details": ""})
        self.assertFalse(f.is_valid())
        f = ShowcaseOverrideForm(data={"plugin_id": "dbimport", "features_text": "الف\nب\nج", "tagline": "", "details": ""})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.save().features, ["الف", "ب", "ج"])
