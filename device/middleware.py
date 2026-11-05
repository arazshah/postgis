"""میان‌افزارهای دستگاه: اعتبارسنجی نام میزبان، مسدودسازی بخش‌های ابری، اجبار تغییر رمز."""
import ipaddress

from django.conf import settings
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect

from .models import DeviceProfile

# مسیرهایی که با «باید رمز را عوض کند» هم باز می‌مانند
PASSWORD_EXEMPT = ("/device/password/", "/accounts/logout/", "/static/", "/healthz", "/device/time/")


def host_allowed(host: str) -> bool:
    """نام تک‌کلمه‌ای (pgpro)، *.local، *.lan، *.home.arpa، هر IP، localhost و نام‌های اضافه‌ی PGPRO_EXTRA_HOSTS."""
    host = host.strip().lower()
    if host.startswith("["):  # IPv6 با کروشه
        host = host[1:].split("]", 1)[0]
    else:
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if "." not in host or host.endswith((".local", ".lan", ".home.arpa", ".localdomain")):
        return True
    return host in {h.lower() for h in settings.DEVICE_EXTRA_HOSTS}


class DeviceHostMiddleware:
    """جلوگیری از DNS rebinding: دستگاه فقط با نام یا IP شبکه‌ی محلی پاسخ می‌دهد."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not host_allowed(request.get_host()):
            return HttpResponseBadRequest("نام میزبان مجاز نیست.", content_type="text/plain; charset=utf-8")
        return self.get_response(request)


class DeviceGuardMiddleware:
    """بخش‌های ابری (پرداخت، پشتیبانی، کلاس، آمار، دستیار) ← 404؛ رمز پیش‌فرض/موقت ← صفحه‌ی تغییر رمز."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith(settings.DEVICE_BLOCKED_PREFIXES):
            from django.http import Http404

            raise Http404
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not path.startswith(PASSWORD_EXEMPT):
            if DeviceProfile.objects.filter(user_id=user.pk, must_change_password=True).exists():
                return redirect(f"/device/password/?next={path}" if request.method == "GET" else "/device/password/")
        return self.get_response(request)
