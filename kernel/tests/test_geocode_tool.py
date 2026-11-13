"""ابزار مشتری «ژئوکدر فارسی» (پلاگین cap_geocoder): دسترسی، اجرا، CSV، سقف و خاموشی."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from databases import services
from databases.tests.test_services import BaseCase
from kernel import caps, entitlements, geocode
from kernel.models import PluginState, PluginUsage
from kernel.tests.test_geocode import gaz
from kernel.tests.test_pagekit import STORAGES


class UploadTests(SimpleTestCase):
    def test_columns_and_headers(self):
        f = geocode.lines_from_upload
        self.assertEqual(f("آدرس,نام\nخیابان ولیعصر,الف\n,\nتجریش,ب\n".encode()), ["خیابان ولیعصر", "تجریش"])
        self.assertEqual(f("name,loc\nالف,ولیعصر\n".encode(), "loc"), ["ولیعصر"])
        self.assertEqual(f("ولیعصر\nتجریش\n".encode()), ["ولیعصر", "تجریش"])  # بدون سرستون: ستون اول
        self.assertEqual(f(b""), [])
        with self.assertRaises(geocode.GeocodeError):
            f("سلام".encode("utf-16"))

    def test_csv_formula_injection_is_neutralised(self):
        r = geocode.Result("=cmd|' /C calc'!A0", note="+x")
        body = geocode.results_csv([r])
        self.assertIn("'=cmd", body)
        self.assertIn("'+x", body)


@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class ToolViewTests(BaseCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.addCleanup(entitlements.invalidate)
        self.db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        self.url = reverse("kernel:geocode", args=[self.db.pk])
        for target, val in (("kernel.geocode.cities", lambda ws: gaz().cities), ("kernel.geocode.load", lambda ws, city, radius=15: gaz())):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)

    def test_page_and_run_with_csv(self):
        r = self.client.get(self.url)
        self.assertContains(r, "ژئوکدر فارسی")
        self.assertContains(r, "تهران")  # فهرست شهرها
        self.assertContains(r, "سفارش پلاگین اختصاصی")
        r = self.client.post(self.url, {"city": "تهران", "radius": "15", "text": "خیابان ولیعصر\nتجریش\nناشناس"})
        self.assertContains(r, "نرخ تطبیق")
        self.assertEqual(r.context["stats"]["total"], 3)
        csv = self.client.get(self.url + f"?dl={r.context['token']}")
        self.assertEqual(csv["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("خیابان ولیعصر", csv.content.decode("utf-8-sig"))
        self.assertEqual(PluginUsage.objects.get(plugin_id="cap_geocoder", metric="geocode_rows").count, 3)

    def test_upload_and_validation(self):
        up = SimpleUploadedFile("a.csv", "آدرس\nخیابان ولیعصر\n".encode(), "text/csv")
        r = self.client.post(self.url, {"city": "تهران", "radius": "15", "file": up})
        self.assertEqual(r.context["stats"]["total"], 1)
        for bad in ({"city": "", "text": "الف"}, {"city": "تهران", "text": ""}, {"city": "تهران", "text": "\n".join(["الف"] * 301)}):
            r = self.client.post(self.url, {"radius": "15", **bad})
            self.assertNotContains(r, "نرخ تطبیق")

    def test_cap_off_is_404_and_rail_entry_hidden(self):
        PluginState.objects.create(plugin_id=caps.pid("geocoder"), enabled=False)
        entitlements.invalidate()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {"city": "x", "text": "y"}).status_code, 404)

    def test_other_users_workspace_denied_and_download_is_per_user(self):
        r = self.client.post(self.url, {"city": "تهران", "radius": "15", "text": "تجریش"})
        token = r.context["token"]
        other = get_user_model().objects.create_user(username="o9", phone="09120000999", password="x")
        self.client.force_login(other)
        self.assertIn(self.client.get(self.url).status_code, (403, 404))
        self.assertIn(self.client.get(self.url + f"?dl={token}").status_code, (403, 404))

    def test_missing_osm_data_shows_setup_message(self):
        with mock.patch("kernel.geocode.cities", side_effect=geocode.GeocodeError("جدول osm_places در این پایگاه نیست؛ اول «داده آماده ایران» را بیاورید.")):
            r = self.client.get(self.url)
        self.assertContains(r, "داده آماده ایران")

    def test_metering_cap_blocks(self):
        with mock.patch("kernel.metering.check", return_value=(False, 5, 5)):
            r = self.client.post(self.url, {"city": "تهران", "radius": "15", "text": "تجریش"})
        self.assertNotContains(r, "نرخ تطبیق")
        self.assertContains(r, "سقف ماهانه")
