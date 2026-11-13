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

    def test_non_capability_plugins_have_screenshots(self):
        for pid in self._feature_ids():
            if not pid.startswith("cap_"):
                self.assertGreaterEqual(len(showcase.images(pid)), 2, f"{pid}: تصویر ویترین (static/market/{pid}) نیست")

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
