"""لینک کوتاه پیامک `/r/<code>/` (ردیابی و ورود امن) و لغو یک‌ضربه‌ای `/r/<code>/stop/`."""
from urllib.parse import urlencode

from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from . import services
from .models import Message


def _msg(code: str) -> Message:
    m = Message.objects.filter(code=code).exclude(status=Message.Status.CONTROL).select_related("user").first()
    if m is None:
        raise Http404
    return m


@require_http_methods(["GET", "HEAD"])
def go(request, code):
    """ثبت کلیک، هدیه، و رساندن به صفحه‌ی درست. حالت امن: ورود با کد تأیید روی شماره‌ی از‌پیش‌پرشده (بدون ورود خودکار)."""
    from accounts.views import SESSION_PHONE

    m = _msg(code)
    if request.method == "GET" and m.clicked_at is None:
        m.clicked_at = timezone.now()
        m.save(update_fields=["clicked_at"])
    if request.method == "GET":
        services.grant_gift(m)
    utm = {"utm_source": "sms", "utm_medium": "winback", "utm_campaign": m.route_key}
    if request.user.is_authenticated:
        return redirect(f"{m.dest}?{urlencode(utm)}")
    request.session[SESSION_PHONE] = m.phone
    return redirect(f"{reverse('accounts:login')}?{urlencode({'next': m.dest, **utm})}")


@require_http_methods(["GET", "POST"])
def stop(request, code):
    """GET فقط صفحه‌ی تأیید است (پیش‌نمایش پیام‌رسان‌ها نباید کسی را لغو کند)؛ POST لغو می‌کند."""
    m = _msg(code)
    done = False
    if request.method == "POST":
        services.set_pref(m.user, False)
        done = True
    return render(request, "winback/stop.html", {"done": done})
