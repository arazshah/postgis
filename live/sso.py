"""ورود متمرکز Live با نشست مستقل و بلیت کوتاه‌عمر یک‌بارمصرف."""
import hashlib
import secrets
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user, login, logout
from django.contrib.sessions.backends.db import SessionStore
from django.db import transaction
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST

from accounts.decorators import site_user_required
from kernel import entitlements, workspace

from .models import LiveTicket

PARENT_SESSION = "live_parent_session"


def main_url(name="databases:dashboard", **kwargs):
    return settings.LIVE_MAIN_ORIGIN + reverse(name, kwargs=kwargs or None)


def _host(request, origin):
    return request.get_host().lower() == urlsplit(origin).netloc


def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _parent_user(key):
    if not isinstance(key, str) or not key:
        return None
    session = SessionStore(session_key=key)
    user = get_user(SimpleNamespace(session=session))
    return user if user.is_authenticated and user.is_active and not user.is_staff else None


def _workspace(request, pk):
    db = workspace.get(request, pk, "viewer")
    if not db.is_live or not entitlements.allowed("maps", user=request.user, ws=db):
        raise Http404
    return db


@site_user_required
@require_POST
@csrf_protect
@never_cache
def launch(request, pk):
    if not settings.LIVE_SSO_ENABLED:
        _workspace(request, pk)
        return redirect("live:projects", pk=pk)
    if not _host(request, settings.LIVE_MAIN_ORIGIN):
        raise Http404
    _workspace(request, pk)
    key = request.session.session_key
    if not key or _parent_user(key) is None:
        return redirect(main_url())
    token = secrets.token_urlsafe(32)
    now = timezone.now()
    LiveTicket.objects.filter(expires_at__lte=now).delete()
    LiveTicket.objects.create(digest=_digest(token), main_session=key, user_id=request.user.pk,
                              workspace_id=pk, expires_at=now + timedelta(seconds=60))
    response = render(request, "live/handoff.html", {"ticket": token,
                      "destination": settings.LIVE_ORIGIN + reverse("live:exchange")})
    response["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@csrf_exempt  # نشست Live هنوز ساخته نشده؛ مبدأ ثابت + بلیت یک‌بارمصرف جایگزین CSRF این فرم انتقال است.
@require_POST
@never_cache
def exchange(request):
    if not settings.LIVE_SSO_ENABLED or not _host(request, settings.LIVE_ORIGIN):
        raise Http404
    if request.headers.get("Origin") != settings.LIVE_MAIN_ORIGIN:
        return HttpResponseForbidden("مبدأ انتقال معتبر نیست.")
    token = request.POST.get("ticket", "")
    if not token or len(token) > 128:
        return redirect(main_url())
    with transaction.atomic():
        ticket = LiveTicket.objects.filter(digest=_digest(token), expires_at__gt=timezone.now()).first()
        if ticket is None or not LiveTicket.objects.filter(pk=ticket.pk).delete()[0]:
            return redirect(main_url())
    user = _parent_user(ticket.main_session)
    if user is None or user.pk != ticket.user_id:
        return redirect(main_url())
    request.user = user
    _workspace(request, ticket.workspace_id)
    # نشست قبلی Live جدا از نشست اصلی است؛ اطلاعات قبلی مرورگر را به کاربر تازه منتقل نکن.
    request.session.flush()
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session[PARENT_SESSION] = ticket.main_session
    return redirect("live:projects", pk=ticket.workspace_id)


@require_POST
@never_cache
def leave(request):
    if not _host(request, settings.LIVE_ORIGIN):
        raise Http404
    logout(request)
    return redirect(main_url())


class LiveSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.LIVE_SSO_ENABLED:
            return self.get_response(request)
        path = request.path_info
        if _host(request, settings.LIVE_ORIGIN):
            if path == reverse("live:exchange"):
                return self.get_response(request)
            parent = _parent_user(request.session.get(PARENT_SESSION))
            if parent is None or not request.user.is_authenticated or parent.pk != request.user.pk:
                if request.session.session_key:
                    logout(request)
                return redirect(main_url())
            if path == reverse("accounts:logout") and request.method == "POST":
                return self.get_response(request)
            if path.startswith(("/accounts/", "/admin/", "/manage/")):
                return redirect(main_url())
            if path == "/":
                return redirect("live:index")
        elif path.startswith("/live/") and not path.startswith("/live/launch/"):
            return redirect(main_url())
        return self.get_response(request)
