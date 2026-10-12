from django.conf import settings
from django.db import connection
from django.http import HttpResponsePermanentRedirect, JsonResponse


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
