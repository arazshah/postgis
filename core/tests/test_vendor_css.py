"""CSSهای کتابخانه‌ای باید از پردازش ManifestStaticFilesStorage سالم بگذرند.

این storage هر ‎url(...)‎ را بازنویسی می‌کند، حتی ‎url(%23id)‎ درون SVGهای data:
آیکون‌های نوار ابزار ترسیم (Geoman) در محیط اصلی به این شکل خالی می‌شدند.
داخل data URI پرانتزهای url باید ‎%28/%29‎ باشند.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

VENDOR = Path(settings.BASE_DIR) / "static/vendor"


class VendorCssDataUriTests(SimpleTestCase):
    def test_no_nested_url_inside_data_uris(self):
        for css_path in VENDOR.rglob("*.css"):
            css = css_path.read_text(encoding="utf-8")
            for _, data in re.findall(r"url\(\s*(['\"])(data:.*?)\1\s*\)", css):
                with self.subTest(css=css_path.name):
                    self.assertNotIn("url(", data)
