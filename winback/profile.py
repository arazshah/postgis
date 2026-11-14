"""زبانه‌ی «پیام‌ها و پیشنهادها» در پروفایل: روشن/خاموش‌کردن پیام‌های بازگشت."""
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from . import services


def context(request) -> dict:
    return {"marketing": services.wants(request.user)}


def handle(request, action: str, next_url: str):
    if action == "winback_pref":
        services.set_pref(request.user, request.POST.get("marketing") == "1")
        messages.success(request, "ترجیح پیام‌ها ذخیره شد.")
        return redirect(next_url or f"{reverse('accounts:profile')}#winback")
    return None


def invite_context(request) -> dict:
    from . import referrals

    on = referrals.enabled() and bool(referrals.reward_text())
    ctx = {"on": on}
    if on:
        ctx.update(link=referrals.link(referrals.code_for(request.user).code), reward=referrals.reward_text(),
                   **referrals.stats(request.user))
    return ctx
