"""
ارسال پیامک.

- console: کد در لاگ چاپ می‌شود (توسعه و تست)
- smsir:   سرویس sms.ir نسخه v1
    * کد تأیید با قالب (send/verify): هدر X-API-KEY و بدنه
      {"mobile": "...", "templateId": 123, "parameters": [{"name": "CODE", "value": "12345"}]}
    * پیام متنی ساده (send/bulk) فقط اگر SMSIR_LINE_NUMBER تنظیم شده باشد
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger(__name__)

SMSIR_API = "https://api.sms.ir/v1"


class SMSError(Exception):
    pass


def _smsir_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{SMSIR_API}/{path}",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-KEY": settings.SMSIR_API_KEY,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.SMS_TIMEOUT) as resp:
            body = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise SMSError(f"sms.ir HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SMSError(f"sms.ir unreachable: {exc}") from exc
    if body.get("status") != 1:
        raise SMSError(f"sms.ir status {body.get('status')}: {body.get('message')}")
    return body


def _smsir_mobile(phone: str) -> str:
    # 09121234567 -> 9121234567 (قالب نمونه‌های مستندات sms.ir)
    return phone[1:] if phone.startswith("0") else phone


def send_otp(phone: str, code: str) -> None:
    backend = settings.SMS_BACKEND
    if backend == "console":
        log.warning("OTP for %s: %s", phone, code)
        return
    if backend == "smsir":
        if not settings.SMSIR_API_KEY or not settings.SMSIR_TEMPLATE_ID:
            raise SMSError("SMSIR_API_KEY یا SMSIR_TEMPLATE_ID تنظیم نشده است")
        _smsir_post("send/verify", {
            "mobile": _smsir_mobile(phone),
            "templateId": int(settings.SMSIR_TEMPLATE_ID),
            "parameters": [{"name": settings.SMSIR_CODE_PARAM, "value": code}],
        })
        return
    raise SMSError(f"SMS_BACKEND ناشناخته: {backend}")


def send_text(phone: str, text: str) -> bool:
    """اطلاع‌رسانی متنی (انقضا، حجم). اگر خط اختصاصی تنظیم نشده باشد بی‌صدا رد می‌شود."""
    backend = settings.SMS_BACKEND
    if backend == "console":
        log.info("SMS to %s: %s", phone, text)
        return True
    if backend == "smsir" and settings.SMSIR_LINE_NUMBER:
        try:
            _smsir_post("send/bulk", {
                "lineNumber": int(settings.SMSIR_LINE_NUMBER),
                "messageText": text,
                "mobiles": [_smsir_mobile(phone)],
            })
            return True
        except SMSError:
            log.exception("sms send_text failed")
    return False


def get_credit() -> float | None:
    if settings.SMS_BACKEND != "smsir" or not settings.SMSIR_API_KEY:
        return None
    req = urllib.request.Request(f"{SMSIR_API}/credit", headers={"X-API-KEY": settings.SMSIR_API_KEY,
                                                                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=settings.SMS_TIMEOUT) as resp:
            return json.loads(resp.read().decode()).get("data")
    except Exception:  # noqa: BLE001
        log.exception("sms credit check failed")
        return None
