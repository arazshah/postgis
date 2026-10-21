import json

from django.http import JsonResponse, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from core.models import SiteSettings

from . import service
from .models import Usage

MAX_BODY = 20_000


def _json(data, status=200):
    resp = JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})
    resp["Cache-Control"] = "private, no-store"
    return resp


@require_GET
@ensure_csrf_cookie
@never_cache
def config(request):
    """تنظیم ویجت؛ توکن CSRF اینجا گرفته می‌شود تا صفحه‌های قابل‌کش توکن نداشته باشند."""
    conf = SiteSettings.get()
    if not service.visible_to(conf, request.user):
        return _json({"enabled": False})
    path = service.clean_text(request.GET.get("path"), 200)
    return _json({
        "enabled": True,
        "csrf": get_token(request),
        "welcome": conf.assistant_welcome,
        "suggestions": service.suggestions(path),
        "max_message": service.MAX_MESSAGE,
        "logged_in": request.user.is_authenticated,
    })


@require_POST
def ask(request):
    conf = SiteSettings.get()
    if not service.visible_to(conf, request.user):
        return _json({"error": "دستیار در دسترس نیست."}, 403)
    if len(request.body) > MAX_BODY:
        return _json({"error": "درخواست بیش‌ازحد بزرگ است."}, 413)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return _json({"error": "درخواست نامعتبر است."}, 400)
    if not isinstance(data, dict):
        return _json({"error": "درخواست نامعتبر است."}, 400)
    message = service.clean_text(data.get("message"), service.MAX_MESSAGE + 1)
    if len(message) < 2:
        return _json({"error": "سؤال را بنویسید."}, 400)
    if len(message) > service.MAX_MESSAGE:
        return _json({"error": f"سؤال بیش از {service.MAX_MESSAGE} نویسه است؛ کوتاه‌تر بنویسید."}, 400)
    limited = service.check_limits(conf, service.actor_for(request))
    if limited:
        return _json({"error": limited}, 429)
    path = service.clean_text(data.get("path"), 200)
    if not path.startswith("/") or path.startswith("//"):
        path = ""
    resp = StreamingHttpResponse(
        service.answer(request, conf, message, service.clean_history(data.get("history")), path,
                       service.clean_text(data.get("title"), 120)),
        content_type="text/event-stream; charset=utf-8")
    resp["Cache-Control"] = "no-cache, no-store"
    resp["X-Accel-Buffering"] = "no"
    return resp


@require_POST
def feedback(request):
    try:
        data = json.loads(request.body or b"{}")
        pk, token, helpful = int(data["id"]), str(data["token"]), data["helpful"]
    except (ValueError, KeyError, TypeError):
        return _json({"error": "درخواست نامعتبر است."}, 400)
    if not isinstance(helpful, bool):
        return _json({"error": "درخواست نامعتبر است."}, 400)
    updated = Usage.objects.filter(pk=pk, feedback_token=token, actor=service.actor_for(request)).update(helpful=helpful)
    return _json({"ok": bool(updated)})
