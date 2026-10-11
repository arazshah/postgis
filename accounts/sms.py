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

from core.models import SiteSettings

log = logging.getLogger(__name__)

SMSIR_API = "https://api.sms.ir/v1"


class SMSError(Exception):
    pass


def _api_key() -> str:
    return SiteSettings.get().get_smsir_api_key()


def _smsir_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{SMSIR_API}/{path}",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-KEY": _api_key(),
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
    conf = SiteSettings.get()
    if conf.sms_backend == "console":
        log.warning("OTP for %s: %s", phone, code)
        return
    if conf.sms_backend == "smsir":
        if not conf.has_smsir_api_key or not conf.smsir_template_id:
            raise SMSError("کلید API یا شناسه قالب sms.ir در تنظیمات سایت وارد نشده است")
        try:
            template_id = int(conf.smsir_template_id)
        except ValueError as exc:
            raise SMSError("شناسه قالب sms.ir باید عدد باشد") from exc
        _smsir_post("send/verify", {
            "mobile": _smsir_mobile(phone),
            "templateId": template_id,
            "parameters": [{"name": conf.smsir_code_param, "value": code}],
        })
        return
    raise SMSError(f"سرویس پیامک ناشناخته: {conf.sms_backend}")


def send_text(phone: str, text: str) -> bool:
    """اطلاع‌رسانی متنی (انقضا، حجم). اگر خط اختصاصی تنظیم نشده باشد بی‌صدا رد می‌شود."""
    conf = SiteSettings.get()
    if not phone:
        return False
    if conf.sms_backend == "console":
        log.info("SMS to %s: %s", phone, text)
        return True
    if conf.sms_backend == "smsir" and conf.smsir_line_number and conf.has_smsir_api_key:
        try:
            _smsir_post("send/bulk", {
                "lineNumber": int(conf.smsir_line_number),
                "messageText": text,
                "mobiles": [_smsir_mobile(phone)],
            })
            return True
        except (SMSError, ValueError):
            log.exception("sms send_text failed")
    return False


def get_credit() -> float | None:
    """اعتبار باقی‌مانده پنل sms.ir؛ None یعنی نامشخص."""
    conf = SiteSettings.get()
    if conf.sms_backend != "smsir" or not conf.has_smsir_api_key:
        return None
    req = urllib.request.Request(f"{SMSIR_API}/credit", headers={"X-API-KEY": _api_key(),
                                                                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=settings.SMS_TIMEOUT) as resp:
            return json.loads(resp.read().decode()).get("data")
    except Exception:  # noqa: BLE001
        log.exception("sms credit check failed")
        return None
