"""
تنظیمات پروژه ژئوپایگاه.
همه مقادیر حساس از متغیرهای محیطی خوانده می‌شوند (مناسب Coolify).
"""
import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG or os.environ.get("DJANGO_TESTING"):
        SECRET_KEY = "dev-insecure-secret-key-change-me"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set in production")

# کلید رمزنگاری گذرواژه‌های ادمین سرورهای دیتابیس (Fernet).
# اگر خالی باشد از SECRET_KEY مشتق می‌شود؛ در تولید حتماً جدا تنظیم شود.
CREDENTIALS_ENCRYPTION_KEY = os.environ.get("CREDENTIALS_ENCRYPTION_KEY", "")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

SITE_NAME = os.environ.get("SITE_NAME", "ژئوپایگاه")
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000")
SUPPORT_TELEGRAM = os.environ.get("SUPPORT_TELEGRAM", "")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "accounts",
    "core",
    "databases",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# دیتابیس خود پنل (نه دیتابیس‌های مشتریان). در Coolify با DATABASE_URL تنظیم می‌شود.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
    )
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "databases:dashboard"
LOGOUT_REDIRECT_URL = "core:home"

LANGUAGE_CODE = "fa-ir"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or os.environ.get("DJANGO_TESTING")
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ایمیل (اختیاری). اگر EMAIL_HOST خالی باشد ایمیل‌ها در لاگ چاپ می‌شوند.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "no-reply@postgis.ir")

# پشت پراکسی Coolify (Traefik/Caddy)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
if not DEBUG and not os.environ.get("DJANGO_TESTING"):
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

# محدودیت تعداد دیتابیس برای هر کاربر عادی
MAX_DATABASES_PER_USER = int(os.environ.get("MAX_DATABASES_PER_USER", "1"))
# پیشوند نام نقش/دیتابیس مشتریان روی سرور دیتابیس
TENANT_PREFIX = os.environ.get("TENANT_PREFIX", "gp_")

# ---------------- پیامک و رمز یک‌بار مصرف ----------------
# SMS_BACKEND: "smsir" در تولید، "console" در توسعه (کد در لاگ چاپ می‌شود)
SMS_BACKEND = os.environ.get("SMS_BACKEND", "console" if (DEBUG or os.environ.get("DJANGO_TESTING")) else "smsir")
SMSIR_API_KEY = os.environ.get("SMSIR_API_KEY", "")
SMSIR_TEMPLATE_ID = os.environ.get("SMSIR_TEMPLATE_ID", "")
SMSIR_CODE_PARAM = os.environ.get("SMSIR_CODE_PARAM", "CODE")
SMSIR_LINE_NUMBER = os.environ.get("SMSIR_LINE_NUMBER", "")  # اختیاری، برای پیامک‌های اطلاع‌رسانی
SMS_TIMEOUT = int(os.environ.get("SMS_TIMEOUT", "10"))

OTP_LENGTH = int(os.environ.get("OTP_LENGTH", "5"))
OTP_TTL_SECONDS = int(os.environ.get("OTP_TTL_SECONDS", "120"))
OTP_RESEND_SECONDS = int(os.environ.get("OTP_RESEND_SECONDS", "60"))
OTP_MAX_ATTEMPTS = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))
OTP_MAX_PER_PHONE_HOUR = int(os.environ.get("OTP_MAX_PER_PHONE_HOUR", "5"))
OTP_MAX_PER_IP_HOUR = int(os.environ.get("OTP_MAX_PER_IP_HOUR", "20"))
# تعداد پراکسی‌های قابل اعتماد جلوی برنامه (Traefik در Coolify = ۱)
TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "1"))
# در حالت console و DEBUG کد روی صفحه هم نمایش داده شود (فقط برای توسعه)
OTP_SHOW_IN_DEBUG = DEBUG and SMS_BACKEND == "console"
