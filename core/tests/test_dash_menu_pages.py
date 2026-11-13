"""منوی «⋯» داشبورد با صفحه‌ی پلاگینِ کیت صفحه (آدرس‌هایی با آرگومان اضافه: پلاگین و کلید صفحه) نباید ۵۰۰ بدهد."""
from django.test import override_settings
from django.urls import reverse

from databases import services
from databases.tests.test_services import BaseCase
from kernel import entitlements, pagekit
from kernel.plugins import registry
from kernel.tests.test_pagekit import STORAGES

PAGE = {"key": "lab", "title": "آزمایشگاه", "group": "data", "need": "viewer", "blocks": [{"kind": "text", "text": "x"}]}


@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class DashMenuPluginPageTests(BaseCase):
    def test_dashboard_renders_with_a_plugin_page_in_the_menu(self):
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        self.addCleanup(entitlements.invalidate)
        pagekit.register("demo", pagekit.parse_page("demo", PAGE))
        db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse("kernel:page", args=[db.pk, "demo", "lab"]))
