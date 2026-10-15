"""ساخت glyphهای نقشه برداری از قلم وزیرمتن در static/basemap/fonts (یک بار؛ خروجی در مخزن است)."""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from iranmap import glyphs

FONTS = Path(__file__).resolve().parents[2] / "fonts"


class Command(BaseCommand):
    help = "glyph PBF برای برچسب‌های فارسی نقشه پایه و نقشه‌های کاربران"

    def handle(self, *args, **opts):
        out = Path(settings.BASE_DIR) / "static" / "basemap" / "fonts"
        for name, stack in (("Vazirmatn-Regular.ttf", "Vazirmatn Regular"), ("Vazirmatn-Bold.ttf", "Vazirmatn Bold")):
            n = glyphs.build(str(FONTS / name), stack, out)
            self.stdout.write(f"{stack}: {n} glyph")
