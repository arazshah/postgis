"""زبانه‌های پروفایل از رجیستری هسته می‌آیند: مدل زبانی را تحلیل می‌آورد، نه حساب."""
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from analysis.models import LlmConfig
from kernel import profile

STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


@override_settings(STORAGES=STORAGES)
class ProfileSectionsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone="09120001111")
        self.client.force_login(self.user)
        self.url = reverse("accounts:profile")

    def test_ai_tab_comes_from_analysis_plugin(self):
        self.assertEqual([s.key for s in profile.sections()], ["ai", "alerts", "winback", "invite"])
        self.assertEqual(profile.sections()[0].plugin, "analysis")
        self.assertEqual(profile.broken_paths(), [])
        r = self.client.get(self.url)
        self.assertContains(r, 'id="t-ai"')
        self.assertContains(r, 'id="p-ai"')
        self.assertContains(r, 'name="action" value="llm_save"')
        self.assertNotContains(r, "prof-ok")

    def test_save_and_delete_go_to_the_owning_plugin(self):
        r = self.client.post(self.url, {"action": "llm_save", "base_url": "http://x", "model": "m", "api_key": "k"})
        self.assertRedirects(r, f"{self.url}#ai", fetch_redirect_response=False)
        self.assertFalse(LlmConfig.objects.exists())
        r = self.client.post(self.url, {"action": "llm_save", "base_url": "https://api.example.ir/v1", "model": "m1",
                                        "api_key": "sk-test-1234567890", "next": "/dashboard/"})
        self.assertRedirects(r, "/dashboard/", fetch_redirect_response=False)
        cfg = LlmConfig.objects.get(user=self.user)
        self.assertEqual(cfg.model, "m1")
        self.assertContains(self.client.get(self.url), "prof-ok")
        self.assertRedirects(self.client.post(self.url, {"action": "llm_delete"}), f"{self.url}#ai",
                             fetch_redirect_response=False)
        self.assertFalse(LlmConfig.objects.exists())

    def test_unknown_action_just_shows_the_page(self):
        self.assertEqual(self.client.post(self.url, {"action": "nope"}).status_code, 200)

    def test_failing_section_is_dropped_not_fatal(self):
        from kernel.plugins import registry

        registry.add(profile.POINT, "zz", profile.Section("zz", "x", "analysis/_profile_ai.html", "analysis",
                                                          context="kernel.tests.test_kernel.boom"),
                     plugin="analysis", order=999)
        try:
            with self.assertLogs("kernel.profile", "ERROR"):
                r = self.client.get(self.url)
        finally:
            registry._points[profile.POINT].pop("zz")
        self.assertContains(r, 'id="t-ai"')
        self.assertNotContains(r, 'id="t-zz"')
