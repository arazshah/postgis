from django.db.models import F
from django.http import Http404, HttpResponseRedirect
from django.utils import timezone
from django.views.decorators.http import require_GET

from . import classify as cl
from .models import TrackedLink


@require_GET
def go(request, slug):
    """کلیک را می‌شمارد و با UTM به مقصد می‌فرستد؛ میدلور آمار در صفحه مقصد منبع را ثبت می‌کند."""
    link = TrackedLink.objects.filter(slug=slug, is_active=True).first()
    if link is None:
        raise Http404
    if not cl.is_bot(request.META.get("HTTP_USER_AGENT", "")):  # پیش‌نمایش‌گر لینک در تلگرام کلیک نیست
        TrackedLink.objects.filter(pk=link.pk).update(clicks=F("clicks") + 1, last_click_at=timezone.now())
    response = HttpResponseRedirect(link.target_path())
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
