from django.test import override_settings
from django.urls import reverse

from databases import services
from databases.models import UserDatabase
from databases.tests.test_services import BaseCase

STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


@override_settings(STORAGES=STORAGES)
class DashboardTests(BaseCase):
    def test_empty_state_guides_first_step(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:dashboard"))
        self.assertContains(r, "اولین پایگاه داده مکانی")
        self.assertContains(r, reverse("databases:create"))

    def test_every_shortcut_explains_itself(self):
        db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:dashboard"))
        for name in ("explore", "explore_sql", "import", "backups", "usage", "team"):
            self.assertContains(r, reverse(f"databases:{name}", args=[db.pk]))
        self.assertContains(r, reverse("analysis:page", args=[db.pk]))
        self.assertContains(r, reverse("publish:manage", args=[db.pk]))
        self.assertContains(r, "اطلاعات اتصال")
        self.assertContains(r, "هنوز بکاپی نگرفته")  # هشدار بکاپ

    def test_full_database_shows_upgrade_alert(self):
        db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])
        UserDatabase.objects.filter(pk=db.pk).update(size_bytes=db.plan.quota_bytes, status=UserDatabase.Status.READONLY)
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:dashboard"))
        self.assertContains(r, "فقط‌خواندنی است")
        self.assertContains(r, reverse("billing:plans"))

    def test_inactive_database_hides_work_shortcuts(self):
        db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])
        UserDatabase.objects.filter(pk=db.pk).update(status=UserDatabase.Status.SUSPENDED)
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:dashboard"))
        self.assertNotContains(r, reverse("databases:explore_sql", args=[db.pk]))
