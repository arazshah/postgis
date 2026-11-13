"""پلاگین‌های نمونه‌ی «هواشناسی آنلاین» و «شناسنامه باغات»: مشخصات معتبر، نصب رایگان و دکمه‌ی پنل."""
import tomllib
from datetime import UTC
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from kernel import entitlements, pagekit, pkg, samples, sources
from kernel.models import PluginRelease, PluginState


class SpecTests(SimpleTestCase):
    def page(self, pid):
        return pagekit.parse_page(pid, tomllib.loads(samples.page_text(pid)))

    def test_weather_covers_variables_models_and_modes(self):
        p = self.page(samples.WEATHER_ID)
        fc, hist = p.sources
        self.assertEqual((fc.host, fc.mode, fc.cursor, hist.host, hist.mode), ("api.open-meteo.com", "replace", "t", "archive-api.open-meteo.com", "append"))
        self.assertGreaterEqual(len(samples.WEATHER_VARS), 20)
        self.assertGreaterEqual(len(samples.WEATHER_MODELS), 30)
        ins = {i.name: i for i in fc.inputs}
        self.assertEqual((ins["variables"].kind, ins["model"].kind, ins["days"].kind), ("multi", "choice", "choice"))
        self.assertEqual(len(ins["model"].choices), len(samples.WEATHER_MODELS))
        self.assertEqual({c for c, _i in fc.consts}, {"lat", "lon", "model"})
        self.assertEqual(len(fc.optional), len(samples.WEATHER_VARS))  # هر متغیر اختیاری است
        self.assertEqual(len(p.tables), 2)
        self.assertEqual(len(p.reports), 1)

    def test_weather_request_uses_selected_variables_and_model(self):
        fc = self.page(samples.WEATHER_ID).sources[0]
        from datetime import datetime
        st = mock.Mock(inputs={"lat": "36.3", "lon": "59.6", "variables": ["wind_speed_10m", "temperature_2m", "bogus"], "model": "ecmwf_ifs025", "days": "3"}, cursor="", secret_enc="")
        with self.assertRaises(sources.SourceError):  # متغیر ناشناخته رد می‌شود (تزریق به query ممکن نیست)
            sources.build_request(fc, st, datetime.now(UTC))
        st.inputs["variables"] = ["wind_speed_10m", "temperature_2m"]
        target, _h = sources.build_request(fc, st, datetime.now(UTC))
        self.assertIn("hourly=temperature_2m%2Cwind_speed_10m", target)  # ترتیب پایدار
        self.assertIn("models=ecmwf_ifs025", target)
        self.assertIn("forecast_days=3", target)
        st.inputs["model"] = "x&evil=1"
        with self.assertRaises(sources.SourceError):
            sources.build_request(fc, st, datetime.now(UTC))

    def test_orchard_registry(self):
        p = self.page(samples.ORCHARD_ID)
        self.assertEqual((len(p.forms), len(p.records), len(p.reports), len(p.tables)), (1, 1, 1, 1))
        self.assertIn("geometry", {f.kind for f in p.forms[0].fields})
        self.assertEqual({f.name for f in p.records[0].fields}, {f.name for f in p.forms[0].fields})


class InstallTests(TestCase):
    def setUp(self):
        self.addCleanup(entitlements.invalidate)
        self.admin = get_user_model().objects.create_superuser(username="adm", phone="09120000300", password="x")

    def test_install_publishes_both_free_and_open(self):
        out = samples.install(self.admin)
        self.assertEqual([o["id"] for o in out], [samples.WEATHER_ID, samples.ORCHARD_ID])
        self.assertTrue(all(o["active"] for o in out), out)
        for pid in (samples.WEATHER_ID, samples.ORCHARD_ID):
            self.assertEqual(PluginRelease.objects.get(plugin_id=pid).status, PluginRelease.Status.ACTIVE)
            self.assertEqual(PluginState.objects.get(plugin_id=pid).access, "open")
        self.assertIsNotNone(pagekit.get(samples.WEATHER_ID, samples.WEATHER_KEY))
        self.assertIsNotNone(pagekit.get(samples.ORCHARD_ID, samples.ORCHARD_KEY))
        again = samples.install(self.admin)
        self.assertTrue(all(o["active"] for o in again), again)
        self.assertEqual(PluginRelease.objects.filter(plugin_id=samples.WEATHER_ID).count(), 2)
        pkg.sync()

    def test_install_single(self):
        out = samples.install(self.admin, samples.ORCHARD_ID)
        self.assertEqual(len(out), 1)


class ViewTests(TestCase):
    def setUp(self):
        self.addCleanup(entitlements.invalidate)
        self.admin = get_user_model().objects.create_superuser(username="adm2", phone="09120000301", password="x")
        self.client.force_login(self.admin)

    def test_button_installs_and_get_does_not(self):
        self.assertEqual(self.client.get(reverse("plugin_sample")).status_code, 302)
        self.assertFalse(PluginRelease.objects.exists())
        r = self.client.post(reverse("plugin_sample"), follow=True)
        self.assertContains(r, "هواشناسی آنلاین")
        self.assertContains(r, "شناسنامه باغات")
        self.assertEqual(PluginRelease.objects.filter(status=PluginRelease.Status.ACTIVE).count(), 2)
        self.assertContains(self.client.get(reverse("plugin_hub") + "?tab=create"), "نصب نمونه‌ها")

    def test_staff_without_permission_is_denied(self):
        staff = get_user_model().objects.create_user(username="st", phone="09120000302", password="x", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.post(reverse("plugin_sample")).status_code, 403)
