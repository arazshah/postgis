"""زبانه‌ی «مدل زبانی» صفحه‌ی پروفایل: کلید شخصی کاربر برای پرسش فارسی؛ در plugin.py ثبت می‌شود."""
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from kernel import llm

from .models import LlmConfig

URL = "accounts:profile"


def _cfg(request):
    return LlmConfig.objects.filter(user=request.user).first()


def context(request) -> dict:
    return {"cfg": _cfg(request)}


def has_key(request) -> bool:
    return _cfg(request) is not None


def handle(request, action: str, next_url: str):
    tab = f"{reverse(URL)}#ai"
    if action == "llm_save":
        try:
            llm.save(request.user, request.POST.get("base_url", ""), request.POST.get("model", ""),
                               request.POST.get("api_key", ""))
        except llm.LlmConfigError as exc:
            messages.error(request, str(exc))
            return redirect(tab)
        messages.success(request, "تنظیم مدل زبانی ذخیره شد.")
        return redirect(next_url or tab)
    if action == "llm_delete":
        cfg = _cfg(request)
        if cfg:
            cfg.delete()
            messages.success(request, "کلید مدل زبانی حذف شد.")
        return redirect(tab)
    return None
