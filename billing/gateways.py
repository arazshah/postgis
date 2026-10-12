"""
درگاه‌های پرداخت اینترنتی (شاپرکی) با تأیید خودکار: زرین‌پال و زیبال.

جریان هر دو یکی است:
    request(amount_rial, callback_url, ...) -> token, pay_url   (خریدار به درگاه هدایت می‌شود)
    خریدار برمی‌گردد به callback_url با token در query string
    verify(token, amount_rial) -> نتیجه قطعی                     (فقط سمت سرور)

امنیت: نتیجه پرداخت فقط از پاسخ verify سمت سرور پذیرفته می‌شود، نه از پارامترهای برگشتی.
اگر verify انجام نشود، درگاه پول را خودکار به خریدار برمی‌گرداند.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from core.models import SiteSettings

log = logging.getLogger(__name__)

TIMEOUT = 15


class GatewayError(Exception):
    def __init__(self, message: str, code: str | int = ""):
        super().__init__(message)
        self.code = code


@dataclass
class PayRequest:
    token: str
    pay_url: str


@dataclass
class VerifyResult:
    paid: bool
    already: bool = False
    ref_id: str = ""
    card: str = ""
    amount_rial: int | None = None
    message: str = ""


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "postgis.ir/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode() or "{}"
    except urllib.error.HTTPError as exc:
        # زرین‌پال خطاها را با کد HTTP غیر ۲۰۰ و بدنه JSON برمی‌گرداند
        body = exc.read().decode(errors="replace")
        if not body.strip().startswith("{"):
            raise GatewayError(f"HTTP {exc.code}: {body[:200]}", exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GatewayError(f"اتصال به درگاه ممکن نشد: {exc}", "network") from exc
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise GatewayError(f"پاسخ درگاه قابل خواندن نبود: {body[:200]}") from exc
    if not isinstance(data, dict):
        raise GatewayError("پاسخ درگاه ساختار مورد انتظار را ندارد.")
    return data


def _last4(card: str) -> str:
    digits = "".join(ch for ch in str(card or "") if ch.isdigit())
    return digits[-4:]


# ---------------------------------------------------------------------- زرین‌پال (API v4)
class Zarinpal:
    name = "zarinpal"
    title = "زرین‌پال"
    token_param = "Authority"
    MESSAGES = {
        -9: "اطلاعات ارسالی نامعتبر است.",
        -10: "مرچنت کد یا IP پذیرنده نامعتبر است.",
        -11: "مرچنت کد فعال نیست؛ با زرین‌پال تماس بگیرید.",
        -12: "تلاش بیش از حد؛ کمی بعد دوباره تلاش کنید.",
        -15: "درگاه پرداخت معلق شده است.",
        -16: "سطح تأیید پذیرنده پایین‌تر از سطح نقره‌ای است.",
        -50: "مبلغ پرداخت‌شده با مبلغ فاکتور برابر نیست.",
        -51: "پرداخت ناموفق یا انجام‌نشده.",
        -54: "شناسه پرداخت (Authority) نامعتبر است.",
        101: "این پرداخت قبلاً تأیید شده است.",
    }

    def __init__(self, merchant: str, sandbox: bool = False):
        self.merchant = merchant
        host = "sandbox.zarinpal.com" if sandbox else "payment.zarinpal.com"
        self.api = f"https://{host}/pg/v4/payment"
        self.start = f"https://{host}/pg/StartPay/"

    def _error(self, data: dict) -> GatewayError:
        errors = data.get("errors") or {}
        if isinstance(errors, list):
            errors = errors[0] if errors else {}
        code = errors.get("code", "") if isinstance(errors, dict) else ""
        msg = self.MESSAGES.get(code) or (errors.get("message") if isinstance(errors, dict) else "") or "خطای درگاه"
        return GatewayError(f"زرین‌پال {code}: {msg}", code)

    def request(self, *, amount_rial: int, callback_url: str, description: str, order_id: str,
                mobile: str = "", email: str = "") -> PayRequest:
        meta = {"order_id": order_id}
        if mobile:
            meta["mobile"] = mobile
        if email:
            meta["email"] = email
        data = _post(f"{self.api}/request.json", {
            "merchant_id": self.merchant, "amount": int(amount_rial), "currency": "IRR",
            "callback_url": callback_url, "description": description[:500], "metadata": meta})
        d = data.get("data") or {}
        if isinstance(d, dict) and d.get("code") == 100 and d.get("authority"):
            return PayRequest(token=d["authority"], pay_url=self.start + d["authority"])
        raise self._error(data)

    def verify(self, token: str, amount_rial: int) -> VerifyResult:
        data = _post(f"{self.api}/verify.json", {"merchant_id": self.merchant, "amount": int(amount_rial),
                                                 "authority": token})
        d = data.get("data") or {}
        if isinstance(d, dict) and d.get("code") in (100, 101):
            return VerifyResult(paid=True, already=d.get("code") == 101, ref_id=str(d.get("ref_id") or ""),
                                card=_last4(d.get("card_pan")), amount_rial=int(amount_rial))
        err = self._error(data)
        if err.code in (-51, -54, -50):  # پرداخت نشده / ناموفق / مبلغ نابرابر
            return VerifyResult(paid=False, message=str(err))
        raise err

    @staticmethod
    def callback_ok(params) -> bool:
        return params.get("Status") == "OK"


# ---------------------------------------------------------------------- زیبال
class Zibal:
    name = "zibal"
    title = "زیبال"
    token_param = "trackId"
    API = "https://gateway.zibal.ir/v1"
    START = "https://gateway.zibal.ir/start/"
    MESSAGES = {
        102: "merchant یافت نشد.",
        103: "merchant غیرفعال است.",
        104: "merchant نامعتبر است.",
        105: "مبلغ باید بیشتر از ۱٬۰۰۰ ریال باشد.",
        106: "callbackUrl نامعتبر است.",
        113: "مبلغ تراکنش از سقف مجاز بیشتر است.",
        201: "این پرداخت قبلاً تأیید شده است.",
        202: "سفارش پرداخت نشده یا ناموفق بوده است.",
        203: "trackId نامعتبر است.",
    }

    def __init__(self, merchant: str, sandbox: bool = False):
        # در زیبال حالت آزمایشی با merchant ثابت «zibal» انجام می‌شود
        self.merchant = "zibal" if sandbox else merchant

    def _error(self, data: dict) -> GatewayError:
        code = data.get("result", "")
        return GatewayError(f"زیبال {code}: {self.MESSAGES.get(code) or data.get('message') or 'خطای درگاه'}", code)

    def request(self, *, amount_rial: int, callback_url: str, description: str, order_id: str,
                mobile: str = "", email: str = "") -> PayRequest:
        payload = {"merchant": self.merchant, "amount": int(amount_rial), "callbackUrl": callback_url,
                   "description": description[:500], "orderId": order_id}
        if mobile:
            payload["mobile"] = mobile
        data = _post(f"{self.API}/request", payload)
        if data.get("result") == 100 and data.get("trackId"):
            token = str(data["trackId"])
            return PayRequest(token=token, pay_url=self.START + token)
        raise self._error(data)

    def verify(self, token: str, amount_rial: int) -> VerifyResult:
        data = _post(f"{self.API}/verify", {"merchant": self.merchant, "trackId": int(token)})
        result = data.get("result")
        if result in (100, 201):
            amount = data.get("amount")
            if amount is None and result == 201:
                inq = _post(f"{self.API}/inquiry", {"merchant": self.merchant, "trackId": int(token)})
                amount = inq.get("amount")
            amount = int(amount) if amount is not None else None
            if amount is not None and amount != int(amount_rial):
                return VerifyResult(paid=False, amount_rial=amount,
                                    message=f"مبلغ پرداخت‌شده ({amount} ریال) با فاکتور برابر نیست.")
            return VerifyResult(paid=True, already=result == 201, ref_id=str(data.get("refNumber") or ""),
                                card=_last4(data.get("cardNumber")), amount_rial=amount)
        if result in (202, 203):
            return VerifyResult(paid=False, message=str(self._error(data)))
        raise self._error(data)

    @staticmethod
    def callback_ok(params) -> bool:
        return params.get("success") == "1"


PROVIDERS = {Zarinpal.name: Zarinpal, Zibal.name: Zibal}
CHOICES = [(Zarinpal.name, "زرین‌پال"), (Zibal.name, "زیبال")]


def get_gateway(conf: SiteSettings | None = None, name: str | None = None):
    conf = conf or SiteSettings.get()
    cls = PROVIDERS.get(name or conf.gateway_provider)
    if cls is None:
        raise GatewayError("درگاه پرداخت انتخاب نشده است.")
    merchant = conf.get_gateway_merchant()
    if not merchant and not conf.gateway_sandbox:
        raise GatewayError("مرچنت کد درگاه در تنظیمات سایت وارد نشده است.")
    if not merchant and cls is Zarinpal:
        merchant = "00000000-0000-0000-0000-000000000000"  # سندباکس زرین‌پال هر UUID را می‌پذیرد
    return cls(merchant, sandbox=conf.gateway_sandbox)
