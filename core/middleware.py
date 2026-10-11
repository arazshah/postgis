from django.db import connection
from django.http import JsonResponse


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
