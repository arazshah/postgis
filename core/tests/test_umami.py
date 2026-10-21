from django.test import TestCase

from accounts.models import User
from core.admin import SiteSettingsForm
from core.models import SiteSettings

UA = "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36"
TAG = '<script defer src="https://stats.araz.me/script.js" data-website-id="3f9c1c52-1a2b-4c5d-8e9f-0a1b2c3d4e5f"></script>'


class UmamiTests(TestCase):
    def setUp(self):
        self.conf = SiteSettings.get()

    def test_off_by_default(self):
        self.assertNotContains(self.client.get("/", HTTP_USER_AGENT=UA), "data-website-id")

    def test_renders_for_visitors_not_staff(self):
        self.conf.umami_script_url = "https://stats.araz.me/script.js"
        self.conf.umami_website_id = "3f9c1c52-1a2b-4c5d-8e9f-0a1b2c3d4e5f"
        self.conf.save()
        r = self.client.get("/", HTTP_USER_AGENT=UA)
        self.assertContains(r, 'src="https://stats.araz.me/script.js"')
        self.assertContains(r, 'data-website-id="3f9c1c52-1a2b-4c5d-8e9f-0a1b2c3d4e5f"')
        self.assertContains(r, 'data-do-not-track="true"')
        self.client.force_login(User.objects.create_admin("root", "Str0ng-Admin-Pass"))
        self.assertNotContains(self.client.get("/", HTTP_USER_AGENT=UA), "data-website-id")

    def _form(self, **over):
        from django.forms.models import model_to_dict

        data = {k: v for k, v in model_to_dict(self.conf).items() if v is not None}
        data.update(over)
        return SiteSettingsForm(data, instance=self.conf)

    def test_pasting_whole_script_tag_fills_both_fields(self):
        f = self._form(umami_script_url=TAG, umami_website_id="")
        f.is_valid()
        self.assertNotIn("umami_script_url", f.errors)
        self.assertNotIn("umami_website_id", f.errors)
        self.assertEqual(f.cleaned_data["umami_script_url"], "https://stats.araz.me/script.js")
        self.assertEqual(f.cleaned_data["umami_website_id"], "3f9c1c52-1a2b-4c5d-8e9f-0a1b2c3d4e5f")

    def test_rejects_unsafe_values(self):
        for bad in ("http://stats.araz.me/script.js", 'https://x.com/a.js" onerror="x', "javascript:alert(1)"):
            self.assertIn("umami_script_url", self._form(umami_script_url=bad).errors, bad)
        self.assertIn("umami_website_id", self._form(umami_website_id='x" onload="y').errors)
