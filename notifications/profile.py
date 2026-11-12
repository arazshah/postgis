"""زبانه‌ی «کانال‌های هشدار» پروفایل: اتصال بله/تلگرام، ساعت سکوت و پیامک پشتیبان."""
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from kernel import notify
from kernel.models import NotifyAddress, NotifyPref

URL = "accounts:profile"


def context(request) -> dict:
    addrs = {a.channel: a for a in NotifyAddress.objects.filter(user=request.user)}
    rows = [{"key": c.key, "label": notify.CHANNELS[c.key]["label"], "addr": addrs.get(c.key)} for c in notify.active_channels()]
    return {"rows": rows, "pref": NotifyPref.objects.filter(user=request.user).first(), "hours": range(24),
            "link": request.session.pop("notify_link", None)}


def has_channel(request) -> bool:
    return NotifyAddress.objects.filter(user=request.user).exclude(chat_id="").exists()


def handle(request, action: str, next_url: str):
    tab = f"{reverse(URL)}#alerts"
    post = request.POST
    if action == "notify_link":
        try:
            info = notify.begin_link(request.user, post.get("channel", ""))
            request.session["notify_link"] = {"channel": post.get("channel", ""), **info}
        except notify.NotifyError as exc:
            messages.error(request, str(exc))
    elif action == "notify_unlink":
        notify.unlink(request.user, post.get("channel", ""))
        messages.success(request, "اتصال حذف شد.")
    elif action == "notify_test":
        out = notify.deliver(request.user, "پیام آزمایشی ژئوپایگاه", "اگر این پیام را می‌بینید، کانال هشدار شما درست کار می‌کند.", severity="critical")
        if out["sent"]:
            messages.success(request, "پیام آزمایشی به " + "، ".join(notify.CHANNELS[k]["label"] for k in out["sent"]) + " فرستاده شد.")
        elif out["fallback"]:
            messages.warning(request, "کانال پیام‌رسانی متصل نیست یا نرسید؛ پیام با پیامک/ایمیل فرستاده شد.")
        else:
            messages.error(request, "پیامی فرستاده نشد؛ کانال یا پیامک/ایمیل را بررسی کنید.")
    elif action == "notify_pref":
        def hour(name):
            v = post.get(name, "")
            return int(v) if v.isdigit() and 0 <= int(v) <= 23 else None
        NotifyPref.objects.update_or_create(user=request.user, defaults={
            "quiet_from": hour("quiet_from"), "quiet_to": hour("quiet_to"), "fallback": post.get("fallback") == "1"})
        messages.success(request, "تنظیم ذخیره شد.")
    return redirect(tab)
