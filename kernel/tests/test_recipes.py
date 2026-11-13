"""دستورهای آماده و ساخت پلاگین در استودیو (ADR-0010 مرحله‌ی ۱۱)."""
import json

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from kernel import blueprint, entitlements, recipes, wizard
from kernel.models import PluginDraft


class RecipeTests(SimpleTestCase):
    def test_every_recipe_is_valid_and_compiles(self):
        for key in recipes.BY_KEY:
            if key == "blank":  # خالی: عمداً بدون صفحه
                continue
            spec = recipes.build(key, "demo")
            rep = blueprint.analyze(spec, "demo")
            self.assertFalse([i for i in rep["issues"] if i["scope"] != "market"], (key, rep["issues"]))
            self.assertTrue(wizard.compile_pages("demo", spec), key)


@override_settings(ADMIN_2FA_REQUIRED=False)
class NewViewTests(TestCase):
    def setUp(self):
        self.addCleanup(entitlements.invalidate)
        self.client.force_login(get_user_model().objects.create_superuser("newroot", "Str0ng-Admin-Pass"))

    def create(self, **kw):
        return self.client.post(reverse("admin:kernel_plugindraft_new"), {"name": "ناوگان من", "plugin_id": "myfleet", "recipe": "fleet", **kw})

    def test_page_renders_all_recipes(self):
        r = self.client.get(reverse("admin:kernel_plugindraft_new"))
        for rec in recipes.RECIPES:
            self.assertContains(r, rec.title)

    def test_create_from_recipe_redirects_to_designer(self):
        r = self.create()
        d = PluginDraft.objects.get(plugin_id="myfleet")
        self.assertRedirects(r, reverse("admin:kernel_plugindraft_designer", args=[d.pk]), fetch_redirect_response=False)
        self.assertTrue(d.wizard["tables"] and d.wizard["pages"])
        self.assertEqual(self.client.get(reverse("admin:kernel_plugindraft_designer", args=[d.pk])).status_code, 200)

    def test_bad_input_creates_nothing(self):
        self.create(plugin_id="Bad Id")
        self.create(recipe="nope")
        self.assertFalse(PluginDraft.objects.exists())
        self.create()
        self.create()  # شناسه‌ی تکراری
        self.assertEqual(PluginDraft.objects.count(), 1)

    def test_old_wizard_and_studio_urls_redirect(self):
        r = self.client.get(reverse("admin:kernel_plugindraft_wizard_new"))
        self.assertRedirects(r, reverse("admin:kernel_plugindraft_new"), fetch_redirect_response=False)
        self.create()
        d = PluginDraft.objects.get(plugin_id="myfleet")
        for name, args in (("kernel_plugindraft_wizard", [d.pk, 3]), ("kernel_plugindraft_studio", [d.pk])):
            r = self.client.get(reverse(f"admin:{name}", args=args))
            self.assertRedirects(r, reverse("admin:kernel_plugindraft_designer", args=[d.pk]), fetch_redirect_response=False)

    def test_files_api_lists_package_files(self):
        self.create()
        d = PluginDraft.objects.get(plugin_id="myfleet")
        r = self.client.get(reverse("admin:kernel_plugindraft_api_files", args=[d.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("plugin.toml", json.dumps(r.json()))
