"""دروازه‌ی آدرس پلاگین‌ها: پلاگین خاموش یا محدودِ بدون مجوز برای درخواست‌کننده «وجود ندارد» (۴۰۴، نه «دسترسی ندارید»).

- بررسی بر اساس ماژول نمای فعال انجام می‌شود (پلاگین صاحب نما)، پس پلاگین نمی‌تواند فراموش کند.
- مسیرهای فضای کار (`dashboard/<pk>/…`) با همان فضای کار سنجیده می‌شوند، یعنی مجوز فضای کار، پلن آن یا مالکش هم دیده می‌شود.
- مسیر محدود بدون کاربر وارد‌شده و بدون فضای کار پیش‌فرض بسته است؛ نمای عمومی عمداً با `@public` علامت می‌خورد
  (مثلاً دریافت داده‌ی دستگاه که احراز هویت خودش را دارد) و فقط شرط «روشن بودن» برایش بررسی می‌شود.
"""
from __future__ import annotations

from django.http import Http404

from . import entitlements, workspace
from .plugins import registry


def public(view):
    """نمایی از پلاگین محدود که بدون ورود کاربر هم کار می‌کند (احراز هویت را خود نما انجام می‌دهد)."""
    view.gate_public = True
    return view


def owner_plugin(view_func) -> str | None:
    target = getattr(view_func, "view_class", view_func)
    module = getattr(target, "__module__", "") or ""
    first = module.split(".", 1)[0]
    return first if first in registry.plugins else None


class PluginGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        entitlements.refresh()  # بسته‌ی تازه‌فعال‌شده پیش از ساخت منو در رجیستری باشد
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        pid = owner_plugin(view_func)
        if pid is None or registry.plugins[pid].kind == "system":
            return None
        st = entitlements.state(pid)
        if st is None:
            return None
        if not st.enabled:
            raise Http404
        if st.access == "open" or getattr(view_func, "gate_public", False):
            return None
        user = getattr(request, "user", None)
        ws = None
        match = request.resolver_match
        if match is not None and match.route.startswith("dashboard/") and "pk" in view_kwargs:
            ws = workspace.peek(view_kwargs["pk"])
        if not entitlements.allowed(pid, user=user, ws=ws):
            raise Http404
        return None
