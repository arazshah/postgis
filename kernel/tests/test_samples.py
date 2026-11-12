"""نمونه‌ی «آزمایشگاه»: صفحه‌ی نمونه همه‌ی قابلیت‌های مراحل ۲ تا ۴ را دارد و بدون خطا منتشر می‌شود."""
import tomllib

from django.contrib.auth import get_user_model
from django.test import TestCase

from kernel import entitlements, pagekit, pkg, samples
from kernel.models import PluginRelease, PluginState


class SampleTests(TestCase):
    def test_sample_page_is_valid_and_covers_new_features(self):
        p = pagekit.parse_page(samples.PLUGIN_ID, tomllib.loads(samples.PAGE))
        self.assertEqual((len(p.tables), len(p.forms), len(p.records), len(p.sources), len(p.reports)), (2, 1, 1, 1, 1))
        self.assertEqual({f.kind for f in p.forms[0].fields}, {"text", "choice", "geometry"})
        self.assertEqual(p.sources[0].host, "api.open-meteo.com")
        self.assertEqual(p.reports[0].blocks, (1, 2, 3, 4))

    def test_install_publishes_open_plugin(self):
        self.addCleanup(entitlements.invalidate)
        u = get_user_model().objects.create_superuser(username="adm", phone="09120000300", password="x")
        out = samples.install(u)
        self.assertTrue(out["active"], out["message"])
        self.assertEqual(PluginRelease.objects.get(plugin_id=samples.PLUGIN_ID).status, PluginRelease.Status.ACTIVE)
        self.assertEqual(PluginState.objects.get(plugin_id=samples.PLUGIN_ID).access, "open")
        self.assertIsNotNone(pagekit.get(samples.PLUGIN_ID, samples.PAGE_KEY))
        again = samples.install(u)  # بار دوم: نسخه‌ی بالاتر
        self.assertTrue(again["active"], again["message"])
        self.assertEqual(PluginRelease.objects.filter(plugin_id=samples.PLUGIN_ID).count(), 2)
        pkg.sync()


class SampleViewTests(TestCase):
    def setUp(self):
        self.addCleanup(entitlements.invalidate)
        self.admin = get_user_model().objects.create_superuser(username="adm2", phone="09120000301", password="x")
        self.client.force_login(self.admin)

    def test_button_installs_and_get_does_not(self):
        from django.urls import reverse
        self.assertEqual(self.client.get(reverse("plugin_sample")).status_code, 302)
        self.assertFalse(PluginRelease.objects.exists())
        r = self.client.post(reverse("plugin_sample"), follow=True)
        self.assertContains(r, "آزمایشگاه ژئوپایگاه")
        self.assertTrue(PluginRelease.objects.filter(plugin_id=samples.PLUGIN_ID, status=PluginRelease.Status.ACTIVE).exists())
        self.assertContains(self.client.get(reverse("plugin_hub") + "?tab=create"), "ساخت و انتشار نمونه")

    def test_staff_without_permission_is_denied(self):
        from django.urls import reverse
        staff = get_user_model().objects.create_user(username="st", phone="09120000302", password="x", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.post(reverse("plugin_sample")).status_code, 403)
