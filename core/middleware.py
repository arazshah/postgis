from django.conf import settings
from django.db import connection
from django.http import HttpResponsePermanentRedirect, JsonResponse
from django.middleware.gzip import GZipMiddleware


class HealthCheckMiddleware:
    """
    پاسخ /healthz پیش از بررسی ALLOWED_HOSTS، تا health check داخلی کانتینر
    (که با Host=127.0.0.1 می‌آید) رد نشود.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/healthz":
            try:
                with connection.cursor() as cur:
                    cur.execute("SELECT 1")
                return JsonResponse({"status": "ok"})
            except Exception:  # noqa: BLE001
                return JsonResponse({"status": "db-error"}, status=503)
        return self.get_response(request)


class CanonicalHostMiddleware:
    """
    درخواست‌های GET روی دامنه‌های فرعی (www.postgis.ir، postgis.araz.me) با 301 به دامنه اصلی می‌روند.
    هر دو دامنه کار می‌کنند، ولی گوگل فقط یک نسخه از هر صفحه را می‌بیند.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.hosts = {h.lower() for h in settings.CANONICAL_REDIRECT_HOSTS}
        self.target = settings.CANONICAL_URL

    def __call__(self, request):
        if self.hosts and request.method in ("GET", "HEAD"):
            host = request.META.get("HTTP_HOST", "").split(":", 1)[0].lower()
            if host in self.hosts:
                return HttpResponsePermanentRedirect(self.target + request.get_full_path())
        return self.get_response(request)


class SafeGZipMiddleware(GZipMiddleware):
    """فشرده‌سازی gzip فقط برای پاسخ‌های متنی و کاشی برداری.
    پاسخ‌های استریم (SSE دستیار، رله NTRIP، دانلود فایل) و فایل‌های از پیش فشرده (zip، تصویر) دست نمی‌خورند."""

    TYPES = ("text/", "application/json", "application/geo+json", "application/xml", "application/javascript",
             "application/x-ndjson", "application/vnd.mapbox-vector-tile", "image/svg+xml")

    def process_response(self, request, response):
        if response.streaming:
            return response
        ctype = response.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if ctype == "text/event-stream" or not ctype.startswith(self.TYPES):
            return response
        return super().process_response(request, response)


class SecurityHeadersMiddleware:
    """هدرهای امنیتی افزوده: Permissions-Policy و Content-Security-Policy.

    CSP با CSP_MODE کنترل می‌شود: report (پیش‌فرض، فقط گزارش به /csp-report/ بدون مسدودسازی)، enforce یا off.
    هر نما می‌تواند هدر خودش را بگذارد؛ اینجا فقط اگر هدر نبود افزوده می‌شود.
    """

    PERMISSIONS = "geolocation=(self), camera=(), microphone=(), payment=(), usb=(), interest-cohort=()"

    def __init__(self, get_response):
        self.get_response = get_response
        mode = settings.CSP_MODE
        self.csp_header = {"report": "Content-Security-Policy-Report-Only",
                           "enforce": "Content-Security-Policy"}.get(mode)
        self.csp = self._policy()

    @staticmethod
    def _policy() -> str:
        scripts = " ".join(settings.CSP_SCRIPT_HOSTS)
        parts = [
            "default-src 'self'",
            f"script-src 'self' 'unsafe-inline' {scripts}".strip(),
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob: https:",
            "font-src 'self' data:",
            "connect-src 'self' https: blob:",
            "worker-src 'self' blob:",
            "frame-src 'self' https:",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self' https:",
            "report-uri /csp-report/",
        ]
        return "; ".join(parts)

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", self.PERMISSIONS)
        if self.csp_header and not response.streaming and self.csp_header not in response.headers:
            response.headers[self.csp_header] = self.csp
        return response
