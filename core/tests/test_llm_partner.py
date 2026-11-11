from django.test import TestCase, override_settings

from core.models import SiteSettings


@override_settings(ALLOWED_HOSTS=["testserver"])
class LlmPartnerSettingsTests(TestCase):
    def test_defaults_off(self):
        conf = SiteSettings.get()
        self.assertFalse(conf.llm_partner_enabled)
        self.assertEqual(conf.llm_partner_url, "")
        self.assertEqual(conf.llm_partner_name, "AvalAI")

    def test_admin_section_present(self):
        from django.contrib import admin

        from core.models import SiteSettings
        names = [f for _, o in admin.site._registry[SiteSettings].get_fieldsets(None) for f in o["fields"]]
        self.assertIn("llm_partner_url", names)
