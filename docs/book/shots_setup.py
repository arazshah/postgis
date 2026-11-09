"""آماده‌سازی محیط نمایشی برای تصویرهای کتاب: نام سایت عمومی (نه نام تجاری) و پلن کامل."""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "docs" / "help-video"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()
from core.models import SiteSettings  # noqa: E402

s = SiteSettings.get()
s.site_name = "پایگاه داده مکانی ابری"
s.save()
import demo  # noqa: E402

demo.plan("pro")  # همه‌ی امکانات (برداشت، سازمانی، تیم) در تصویرها دیده شوند
print("site_name:", SiteSettings.get().site_name)

from databases.models import DatabaseServer  # noqa: E402

DatabaseServer.objects.update(public_host="db.example.com")  # نشانی نمونه در تصویرها، نه دامنه‌ی واقعی
