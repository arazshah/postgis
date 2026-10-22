from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from core.admin import SiteSettingsForm
from core.models import SiteSettings
from core.tests.test_footer_enamad import form_data


def png_bytes():
    buf = BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    return buf.getvalue()


class LogoTests(TestCase):
    def setUp(self):
        self.conf = SiteSettings.get()

    def submit(self, f=None, **extra):
        files = {"logo_file": f} if f else None
        form = SiteSettingsForm(form_data(self.conf, **extra), files, instance=self.conf)
        return form, form.is_valid()

    def test_no_logo_uses_default_and_404(self):
        self.assertIn("favicon.svg", self.conf.logo_url)
        self.assertEqual(self.client.get("/site-logo/").status_code, 404)

    def test_upload_and_serve(self):
        form, ok = self.submit(SimpleUploadedFile("l.png", png_bytes()))
        self.assertTrue(ok, form.errors)
        form.save()
        resp = self.client.get("/site-logo/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertIn("/site-logo/?v=1", SiteSettings.get().logo_url)
        self.assertContains(self.client.get("/"), "/site-logo/?v=1")

    def test_svg_ok_and_clear(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"></svg>'
        form, ok = self.submit(SimpleUploadedFile("l.svg", svg))
        self.assertTrue(ok, form.errors)
        form.save()
        self.assertEqual(self.client.get("/site-logo/")["Content-Type"], "image/svg+xml")
        form, ok = self.submit(clear_logo="on")
        self.assertTrue(ok)
        form.save()
        self.assertEqual(self.client.get("/site-logo/").status_code, 404)

    def test_rejects_non_image(self):
        form, ok = self.submit(SimpleUploadedFile("x.png", b"<html>not an image</html>"))
        self.assertFalse(ok)
        self.assertIn("logo_file", form.errors)

    def test_rejects_big(self):
        form, ok = self.submit(SimpleUploadedFile("x.png", png_bytes() + b"0" * 600_000))
        self.assertFalse(ok)
