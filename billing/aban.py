"""
اتصال به آبان گیت وی — مطابق مستندات API (https://abangateway.ir/api/v1).

    POST /invoices                      ساخت فاکتور  -> invoice_id, payment_url, payable_rial
    GET  /invoices/{id}                 استعلام وضعیت (pending/partially_paid/paid/expired/cancelled)
    POST /invoices/{id}/verify          تأیید یک‌بارمصرف (۲۰۰ verified / ۴۰۹ already_verified)
    POST /invoices/{id}/cancel          لغو فاکتور پرداخت‌نشده
    POST /invoices/{id}/simulate-payment فقط با توکن ag_test_

احراز هویت: Authorization: Bearer ag_live_... یا ag_test_...
امنیت: نتیجه پرداخت هرگز از پارامترهای برگشتی یا بدنه وب‌هوک پذیرفته نمی‌شود؛
همیشه وضعیت از API استعلام و سپس verify می‌شود.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from core.models import SiteSettings

log = logging.getLogger(__name__)

DEFAULT_BASE = "https://abangateway.ir/api/v1"
KEY_RE = re.compile(r"^ag_(live|test)_[A-Za-z0-9]{48}$")

PAID_STATUSES = {"paid"}
FAILED_STATUSES = {"expired", "cancelled", "canceled"}

ERROR_HINTS = {
    "unauthorized": "کلید API آبان نامعتبر است. کلید را دوباره از پنل آبان بسازید و در تنظیمات سایت وارد کنید.",
    "insufficient_fee_wallet": "کیف پول کارمزد آبان خالی است؛ از پنل آبان آن را شارژ کنید.",
    "no_card_registered": "هیچ کارت فعالی در حساب آبان ثبت نشده است؛ کارت را در پنل یا اپ آبان اضافه و فعال کنید.",
    "capacity_full": "ظرفیت همزمان کارت پر است؛ کمی بعد تلاش کنید یا کارت دوم ثبت کنید.",
    "amount_not_allowed": "مبلغ خارج از حد مجاز آبان است (حداقل/حداکثر مبلغ را در پنل آبان ببینید).",
    "unsafe_callback_url": "آدرس بازگشت (callback) را آبان نپذیرفت؛ سایت باید روی https در دسترس باشد.",
    "invalid_request": "درخواست ناقص بود.",
    "invoice_not_found": "فاکتور در آبان پیدا نشد (یا با کلید دیگری ساخته شده است).",
    "rate_limited": "تعداد درخواست‌ها زیاد بوده؛ کمی بعد تلاش کنید.",
    "network": "سرور به abangateway.ir دسترسی ندارد (شبکه/DNS/فایروال سرور را بررسی کنید).",
}


class AbanError(Exception):
    def __init__(self, message: str, *, code: str = "", http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status

    @property
    def hint(self) -> str:
        return ERROR_HINTS.get(self.code, "")


@dataclass
class AbanInvoice:
    id: str
    pay_url: str
    status: str
    amount_rial: int | None = None
    payable_rial: int | None = None


@dataclass
class AbanVerify:
    verified: bool
    already: bool = False
    amount_rial: int | None = None


def normalize_base(base: str) -> str:
    base = (base or "").strip().rstrip("/")
    if base.endswith("/invoices"):
        base = base[: -len("/invoices")]
    if not base:
        return DEFAULT_BASE
    if "/api/" in base + "/":
        return base
    parts = urllib.parse.urlsplit(base if "://" in base else "https://" + base)
    return f"{parts.scheme or 'https'}://{parts.netloc}/api/v1"


def key_mode(key: str) -> str:
    """'live'، 'test' یا '' اگر قالب کلید شناخته‌شده نیست."""
    m = KEY_RE.match(key or "")
    return m.group(1) if m else ""


def _int(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _parse(data: dict) -> AbanInvoice:
    if isinstance(data.get("data"), dict):
        data = data["data"]
    return AbanInvoice(
        id=str(data.get("invoice_id") or data.get("id") or ""),
        pay_url=str(data.get("payment_url") or data.get("pay_url") or ""),
        status=str(data.get("status") or "").lower(),
        amount_rial=_int(data.get("amount_rial")),
        payable_rial=_int(data.get("payable_rial")),
    )


class AbanClient:
    timeout = 15

    def __init__(self, conf: SiteSettings | None = None):
        self.conf = conf or SiteSettings.get()
        self.key = self.conf.get_aban_api_key().strip() if self.conf.aban_api_key_encrypted else ""
        if not self.key:
            raise AbanError("کلید API آبان گیت وی در تنظیمات سایت وارد نشده است.", code="unauthorized")
        self.base = normalize_base(self.conf.aban_api_base)
        self.mode = key_mode(self.key)

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = self.base + "/" + path.lstrip("/")
        req = urllib.request.Request(
            url, method=method,
            data=json.dumps(payload).encode() if payload is not None else (b"" if method == "POST" else None),
            headers={
                "Authorization": f"Bearer {self.key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "postgis.ir/1.0",
            })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode() or "{}"
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")[:500]
            code, msg = "", raw
            try:
                err = json.loads(raw).get("error") or {}
                code, msg = err.get("code", ""), err.get("message", raw)
            except (json.JSONDecodeError, AttributeError):
                pass
            if not code and exc.code == 401:
                code = "unauthorized"
            if not code and exc.code == 429:
                code = "rate_limited"
            raise AbanError(f"آبان گیت وی HTTP {exc.code} {code}: {msg}", code=code, http_status=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AbanError(f"اتصال به {url} ممکن نشد: {exc}", code="network") from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AbanError(f"پاسخ آبان گیت وی JSON نبود (آدرس API را بررسی کنید): {body[:200]}") from exc
        if not isinstance(data, dict):
            raise AbanError("پاسخ آبان گیت وی ساختار مورد انتظار را ندارد.")
        return data

    @staticmethod
    def _id(invoice_id: str) -> str:
        return urllib.parse.quote(str(invoice_id), safe="")

    def create(self, *, amount_rial: int, order_id: str, callback_url: str, description: str = "",
               expiry_minutes: int | None = None, metadata: dict | None = None) -> AbanInvoice:
        payload = {"amount_rial": int(amount_rial), "order_id": order_id[:128], "callback_url": callback_url,
                   "description": description[:1000]}
        if expiry_minutes:
            payload["expiry_minutes"] = max(1, min(int(expiry_minutes), 1440))
        if metadata:
            payload["metadata"] = metadata
        data = self._request("POST", "/invoices", payload)
        inv = _parse(data)
        if not inv.id or not inv.pay_url.startswith("https://"):
            log.warning("unexpected aban create response: %s", str(data)[:500])
            raise AbanError("پاسخ ساخت فاکتور آبان گیت وی کامل نبود (شناسه یا لینک پرداخت ندارد).")
        return inv

    def get(self, invoice_id: str) -> AbanInvoice:
        inv = _parse(self._request("GET", f"/invoices/{self._id(invoice_id)}"))
        if not inv.id:
            inv.id = str(invoice_id)
        return inv

    def verify(self, invoice_id: str) -> AbanVerify:
        try:
            data = self._request("POST", f"/invoices/{self._id(invoice_id)}/verify")
        except AbanError as exc:
            if exc.code == "already_verified":
                return AbanVerify(verified=True, already=True)
            if exc.code == "not_yet_paid":
                return AbanVerify(verified=False)
            raise
        if isinstance(data.get("data"), dict):
            data = data["data"]
        return AbanVerify(verified=data.get("verified") is True, amount_rial=_int(data.get("amount_rial")))

    def cancel(self, invoice_id: str) -> None:
        self._request("POST", f"/invoices/{self._id(invoice_id)}/cancel")

    def simulate_payment(self, invoice_id: str) -> None:
        self._request("POST", f"/invoices/{self._id(invoice_id)}/simulate-payment")

    def ping(self) -> str:
        """آزمایش کلید و دسترسی: فاکتور ناموجود را استعلام می‌کند؛ ۴۰۴ یعنی همه‌چیز درست است."""
        try:
            self._request("GET", "/invoices/inv_connection_test")
        except AbanError as exc:
            if exc.code == "invoice_not_found":
                return self.mode or "unknown"
            raise
        return self.mode or "unknown"
