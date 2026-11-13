"""اعلان چندکاناله: پیام‌رسان‌های سازگار با Bot API (بله، تلگرام) + پشتیبان پیامک/ایمیل. ADR-0009.

- فقط به **آدرس تأییدشده‌ی همان کاربر** می‌فرستد. پیوند حساب با کد یک‌بارمصرف (فقط هش ذخیره می‌شود) و
  poll با `getUpdates` در worker است؛ webhook عمومی نداریم. poll فقط وقتی پیوند در انتظار هست انجام می‌شود.
- متن ساده (بدون parse_mode)، کوتاه‌شده؛ توکن هرگز در لاگ/خطا نمی‌آید.
- تلگرام از ایران فیلتر است: مدیر `api_base` را روی رله‌ی سرور خارجی می‌گذارد (Bot API-سازگار).
- شکست کانال هیچ‌وقت کار فراخوان (مثلاً tick هشدار) را نمی‌شکند.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request

from django.utils import timezone

from . import caps, crypto

log = logging.getLogger(__name__)

CHANNELS = {
    "bale": {"label": "بله", "base": "https://tapi.bale.ai", "link": "https://ble.ir/{bot}?start={code}"},
    "telegram": {"label": "تلگرام", "base": "https://api.telegram.org", "link": "https://t.me/{bot}?start={code}"},
}
MAX_TEXT, TIMEOUT, MAX_RESP = 1000, 8, 64 * 1024
RATE_PER_HOUR, DEDUPE_HOURS, CODE_MINUTES, LOG_DAYS = 30, 24, 15, 30
SEVERITIES = ("normal", "critical")


class NotifyError(Exception):
    pass


def clean_base(raw: str) -> str:
    raw = (raw or "").strip().rstrip("/")
    if not raw:
        return ""
    p = urllib.parse.urlparse(raw)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("نشانی پایه باید http(s) بدون نام‌کاربری و پارامتر باشد.")
    return raw


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def _http(url: str, payload: dict) -> dict:
    """POST JSON؛ جداشده تا آزمون mock کند. خطا = NotifyError با متن بدون توکن."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 - نشانی را مدیر می‌دهد
            data = json.loads(r.read(MAX_RESP) or b"{}")
    except urllib.error.HTTPError as exc:
        raise NotifyError(f"کد پاسخ {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError):
        raise NotifyError("اتصال به سرویس پیام‌رسان برقرار نشد.") from None
    if not isinstance(data, dict) or not data.get("ok"):
        raise NotifyError("سرویس پیام‌رسان درخواست را نپذیرفت.")
    return data


def _call(ch, method: str, payload: dict) -> dict:
    token = crypto.decrypt(ch.token_enc)
    if not token:
        raise NotifyError("توکن ربات تنظیم نشده است.")
    base = ch.api_base or CHANNELS[ch.key]["base"]
    return _http(f"{base}/bot{token}/{method}", payload)


def save_channel(key: str, *, enabled: bool, token: str = "", bot_username: str = "", api_base: str = ""):
    from .models import NotifyChannel

    if key not in CHANNELS:
        raise ValueError("کانال ناشناخته است.")
    ch, _ = NotifyChannel.objects.get_or_create(key=key)
    ch.api_base = clean_base(api_base)
    ch.bot_username = bot_username.strip().lstrip("@")[:64]
    if token.strip():
        ch.token_enc, ch.token_hint = crypto.encrypt(token.strip()), token.strip()[-4:]
    ch.enabled = bool(enabled and ch.token_enc)
    ch.save()
    return ch


def test_channel(key: str) -> tuple[bool, str]:
    from .models import NotifyChannel

    ch = NotifyChannel.objects.filter(key=key).first()
    if ch is None or not ch.token_enc:
        return False, "توکن ربات تنظیم نشده است."
    try:
        info = _call(ch, "getMe", {})
        name = (info.get("result") or {}).get("username", "")
        if name and not ch.bot_username:
            ch.bot_username = name
        ch.last_ok, ch.last_error = timezone.now(), ""
        ch.save()
        return True, f"اتصال برقرار است (ربات {name or 'نامشخص'})."
    except NotifyError as exc:
        ch.last_error = str(exc)[:200]
        ch.save(update_fields=["last_error"])
        return False, str(exc)


def active_channels() -> list:
    from .models import NotifyChannel

    return [c for c in NotifyChannel.objects.filter(enabled=True) if c.key in CHANNELS and c.token_enc]


# ---------------------------------------------------------------- پیوند حساب
def begin_link(user, key: str) -> dict:
    """کد یک‌بارمصرف می‌سازد (۱۵ دقیقه). برمی‌گرداند {code, url}؛ کد خام جای دیگر ذخیره نمی‌شود."""
    from .models import NotifyAddress, NotifyChannel

    ch = NotifyChannel.objects.filter(key=key, enabled=True).first()
    if ch is None or not caps.allowed("notify", user=user):
        raise NotifyError("این کانال فعال نیست.")
    code = secrets.token_hex(4).upper()
    NotifyAddress.objects.update_or_create(user=user, channel=key, defaults={
        "chat_id": "", "code_hash": _hash(code), "code_expires": timezone.now() + datetime.timedelta(minutes=CODE_MINUTES)})
    url = CHANNELS[key]["link"].format(bot=ch.bot_username, code=code) if ch.bot_username else ""
    return {"code": code, "url": url}


def unlink(user, key: str) -> None:
    from .models import NotifyAddress

    NotifyAddress.objects.filter(user=user, channel=key).delete()


def _code_from(text: str) -> str:
    parts = (text or "").strip().split()
    if len(parts) == 2 and parts[0].lower() in ("/start", "/link"):
        return parts[1]
    return parts[0] if len(parts) == 1 and 6 <= len(parts[0]) <= 12 else ""


def poll(now=None) -> dict:
    """tick: پیام‌های تازه‌ی ربات را فقط وقتی پیوندی در انتظار است می‌خواند و کد را تطبیق می‌دهد."""
    from .models import NotifyAddress

    now = now or timezone.now()
    NotifyAddress.objects.filter(chat_id="", code_expires__lt=now).delete()
    linked = 0
    for ch in active_channels():
        if not NotifyAddress.objects.filter(channel=ch.key, chat_id="", code_expires__gte=now).exists():
            continue
        try:
            res = _call(ch, "getUpdates", {"offset": ch.update_offset, "timeout": 0, "limit": 50,
                                           "allowed_updates": ["message"]}).get("result") or []
        except NotifyError as exc:
            ch.last_error = str(exc)[:200]
            ch.save(update_fields=["last_error"])
            continue
        for upd in res:
            ch.update_offset = max(ch.update_offset, int(upd.get("update_id", 0)) + 1)
            msg = upd.get("message") or {}
            chat = msg.get("chat") or {}
            code = _code_from(msg.get("text", ""))
            if not code or chat.get("type", "private") != "private" or not chat.get("id"):
                continue
            addr = NotifyAddress.objects.filter(channel=ch.key, chat_id="", code_hash=_hash(code), code_expires__gte=now).first()
            if addr is None:
                continue
            addr.chat_id, addr.code_hash, addr.code_expires = str(chat["id"]), "", None
            addr.save()
            linked += 1
            try:
                _call(ch, "sendMessage", {"chat_id": addr.chat_id, "text": "اتصال برقرار شد. هشدارها از این پس اینجا می‌رسند."})
            except NotifyError:
                pass
        ch.last_ok, ch.last_error = now, ""
        ch.save()
    return {"linked": linked}


# ---------------------------------------------------------------- ارسال
def _quiet(pref, now) -> bool:
    if pref is None or pref.quiet_from is None or pref.quiet_to is None or pref.quiet_from == pref.quiet_to:
        return False
    h = timezone.localtime(now).hour
    a, b = pref.quiet_from, pref.quiet_to
    return a <= h < b if a < b else (h >= a or h < b)


def _log(user, channel, key, ok, error=""):
    from .models import NotifyLog

    NotifyLog.objects.create(user=user, channel=channel, key=key[:80], ok=ok, error=error[:200])


def deliver(user, subject: str, body: str, *, severity: str = "normal", key: str = "", now=None) -> dict:
    """پیام را به کانال‌های تأییدشده‌ی کاربر می‌فرستد؛ اگر هیچ‌کدام نرسید و کاربر اجازه داده، پیامک/ایمیل.

    برمی‌گرداند {sent: [کانال…], fallback: bool, skipped: ""|"dup"|"rate"}. هرگز استثنا نمی‌دهد.
    """
    from . import workspace
    from .models import NotifyAddress, NotifyLog, NotifyPref

    now = now or timezone.now()
    out = {"sent": [], "fallback": False, "skipped": ""}
    try:
        crit = severity == "critical"
        recent = NotifyLog.objects.filter(user=user, created_at__gte=now - datetime.timedelta(hours=DEDUPE_HOURS))
        if key and recent.filter(key=key, ok=True).exists():
            return {**out, "skipped": "dup"}
        if not crit and recent.filter(created_at__gte=now - datetime.timedelta(hours=1)).count() >= RATE_PER_HOUR:
            return {**out, "skipped": "rate"}
        pref = NotifyPref.objects.filter(user=user).first()
        quiet = not crit and _quiet(pref, now)
        text = f"{subject}\n{body}".strip()[:MAX_TEXT] if body and body != subject else subject[:MAX_TEXT]
        active = {c.key: c for c in active_channels()} if caps.allowed("notify", user=user) else {}  # پلاگین خاموش/بی‌مجوز: فقط پیامک/ایمیل
        for addr in NotifyAddress.objects.filter(user=user).exclude(chat_id=""):
            ch = active.get(addr.channel)
            if ch is None:
                continue
            try:
                _call(ch, "sendMessage", {"chat_id": addr.chat_id, "text": text, "disable_notification": quiet})
                out["sent"].append(ch.key)
                _log(user, ch.key, key, True)
            except NotifyError as exc:
                _log(user, ch.key, key, False, str(exc))
        want_fallback = pref.fallback if pref else True
        if want_fallback and not quiet and (crit or not out["sent"]):
            workspace.notify_user(user, subject, body or subject)
            out["fallback"] = True
            if not out["sent"]:
                _log(user, "sms", key, True)
    except Exception:  # noqa: BLE001 - اعلان نباید فراخوان را بشکند
        log.exception("notify.deliver failed")
    return out


def tick(now=None) -> dict:
    from .models import NotifyLog

    now = now or timezone.now()
    NotifyLog.objects.filter(created_at__lt=now - datetime.timedelta(days=LOG_DAYS)).delete()
    return poll(now)
