"""صفحه‌ی یکپارچه‌ی «پلاگین‌ها» در پنل مدیریت (ADR-0008 مرحله‌ی ۱)."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core import admin_nav
from kernel import nav
from kernel.plugins import registry


@override_settings(ADMIN_2FA_REQUIRED=False)
class HubTests(TestCase):
    def setUp(self):
        self.su = get_user_model().objects.create_superuser("hubroot", "Str0ng-Admin-Pass")
        self.client.force_login(self.su)
        self.url = reverse("plugin_hub")
        registry.register("hub_t3", "مانیتورینگ نمونه", kind="custom", tier=3, version="2.1.0")
        self.addCleanup(registry.remove_plugin, "hub_t3")

    def test_all_tab_lists_plugins_with_kind_tier_version(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "مانیتورینگ نمونه")
        self.assertContains(r, "اختصاصی")
        self.assertContains(r, "کد درون‌پردازه")
        self.assertContains(r, "v2.1.0")
        self.assertContains(r, "پلاگین‌های سیستمی")  # بخش جمع‌شده‌ی سیستمی‌ها

    def test_tier3_without_grant_shows_restricted(self):
        self.assertContains(self.client.get(self.url), "محدود به دارندگان مجوز")

    def test_other_tabs_render(self):
        for tab in ("create", "sales", "advanced"):
            with self.subTest(tab=tab):
                self.assertEqual(self.client.get(self.url, {"tab": tab}).status_code, 200)
        self.assertContains(self.client.get(self.url, {"tab": "advanced"}), reverse("admin:kernel_pluginrelease_upload"))
        self.assertContains(self.client.get(self.url, {"tab": "sales"}), reverse("admin:billing_pluginaddon_changelist"))
        self.assertContains(self.client.get(self.url, {"tab": "create"}), reverse("admin:kernel_plugindraft_changelist"))
        self.assertEqual(self.client.get(self.url, {"tab": "bogus"}).status_code, 200)  # زبانه‌ی ناشناخته = همه

    def test_non_admin_is_denied(self):
        self.client.force_login(get_user_model().objects.create_user("09120009991"))
        self.assertIn(self.client.get(self.url).status_code, (302, 403))

    def test_sidebar_has_one_entry_and_hides_old_ones(self):
        class Req:
            path = "/manage/plugins/"
            user = self.su

            def has_perm(self, *a):
                return True

        groups = admin_nav.build(Req())
        platform = next(g for g in groups if g["key"] == "platform")
        titles = [i["title"] for i in platform["items"]]
        self.assertEqual(titles[0], "پلاگین‌ها")
        all_labels = {i["label"] for g in groups for i in g["items"]}
        for hidden in nav.admin_hidden():
            self.assertNotIn(hidden, all_labels, hidden)
        self.assertTrue(platform["on"])  # روی صفحه‌ی hub گروه فعال است

    def test_hidden_models_still_reachable_by_url(self):
        for name in ("admin:kernel_pluginstate_changelist", "admin:kernel_pluginrelease_changelist", "admin:kernel_publisherkey_changelist",
                     "admin:kernel_plugintrip_changelist", "admin:kernel_pluginusage_changelist", "admin:kernel_plugindraft_changelist",
                     "admin:billing_pluginaddon_changelist"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
