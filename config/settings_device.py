"""
تنظیمات «دستگاه pgpro» (ژئوپایگاه آفلاین روی NanoPi NEO3).

روی تنظیمات اصلی (`config/settings.py`) سوار می‌شود و فقط تفاوت‌ها را می‌گذارد:
فعال با DJANGO_SETTINGS_MODULE=config.settings_device. این فایل فقط در شاخه‌ی pgpro است.
"""
import os
import tempfile

from . import settings as _base
from .settings import *  # noqa: F401,F403

DEVICE_MODE = True
DEVICE_NAME = os.environ.get("PGPRO_HOSTNAME", "pgpro")
DEVICE_VERSION = os.environ.get("PGPRO_VERSION", "0.1.0")
# نشانی‌های اضافه‌ی مجاز (مثلاً نام DNS سازمان)، با ویرگول
DEVICE_EXTRA_HOSTS = _base.env_list("PGPRO_EXTRA_HOSTS", "")
# بخش‌هایی از رابط که در این نسخه نیستند (نام view ریل پایگاه)
DEVICE_HIDDEN_VIEWS = ("publish:ows", "publish:ows_detail", "enterprise:page", "iranmap:ready")
# مسیرهای سرویس ابری که روی دستگاه معنا ندارند
DEVICE_BLOCKED_PREFIXES = ("/billing/", "/support/", "/class/", "/go/", "/assistant/", "/manage/")

INSTALLED_APPS = [*_base.INSTALLED_APPS, "device"]  # noqa: F405

ROOT_URLCONF = "config.urls_device"

# دستگاه فقط در شبکه‌ی محلی است و نام آن (pgpro.local)، نام تک‌کلمه‌ای یا IP است؛
# اعتبارسنجی دقیق‌تر را DeviceHostMiddleware انجام می‌دهد (Django از IP-range پشتیبانی نمی‌کند).
ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = []
CANONICAL_URL = os.environ.get("SITE_URL", f"http://{DEVICE_NAME}.local").rstrip("/")
CANONICAL_REDIRECT_HOSTS = []
SITE_URL = CANONICAL_URL

_mw = list(_base.MIDDLEWARE)  # noqa: F405
_mw.remove("core.middleware.CanonicalHostMiddleware")
_mw.remove("analytics.middleware.AnalyticsMiddleware")
_mw.insert(1, "device.middleware.DeviceHostMiddleware")
_mw.insert(_mw.index("django.contrib.auth.middleware.AuthenticationMiddleware") + 1,
           "device.middleware.DeviceGuardMiddleware")
MIDDLEWARE = _mw

TEMPLATES = [{**_base.TEMPLATES[0], "OPTIONS": {  # noqa: F405
    **_base.TEMPLATES[0]["OPTIONS"],  # noqa: F405
    "context_processors": [*_base.TEMPLATES[0]["OPTIONS"]["context_processors"], "device.context.device"],  # noqa: F405
}}]

# فاز ۱: فقط HTTP روی LAN؛ HTTPS محلی در فاز ۲
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7
# رابط از منابع بیرونی چیزی نمی‌خواهد
CSP_SCRIPT_HOSTS: list[str] = []

# کش مشترک بین پردازه‌های gunicorn (شمارنده‌ی قفل ورود)؛ ذخیره روی فایل
CACHES = {"default": {
    "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
    "LOCATION": os.environ.get("PGPRO_CACHE_DIR", os.path.join(tempfile.gettempdir(), "pgpro-cache")),
}}

# بدون اینترنت: هیچ دانلود خودکاری، پیامکی و آماری
ANALYTICS_ENABLED = False
OSM_REFRESH_DAYS = 0
BASEMAP_REFRESH_DAYS = 0
SMS_BACKEND = "console"
IMPORT_MAX_MB = int(os.environ.get("IMPORT_MAX_MB", "100"))
