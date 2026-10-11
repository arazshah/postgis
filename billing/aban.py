"""
اتصال به آبان گیت وی.

بر اساس نمونه منتشرشده در سایت آبان گیت وی:
    invoice = aban.invoices.create(amount_rial=..., order_id=..., callback_url=...)
    redirect(invoice.pay_url)

آدرس API و مسیرها از «تنظیمات سایت» خوانده می‌شود تا با مستندات نهایی تطبیق داده شود.
امنیت: نتیجه پرداخت هرگز از پارامترهای برگشتی یا بدنه webhook پذیرفته نمی‌شود؛
همیشه وضعیت فاکتور مستقیماً از API آبان استعلام می‌شود.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from core.models import SiteSettings

log = logging.getLogger(__name__)

PAID_STATUSES = {"paid", "confirmed", "completed", "success", "succeeded", "verified", "settled"}
FAILED_STATUSES = {"expired", "cancelled", "canceled", "failed", "rejected"}


class AbanError(Exception):
    pass


@dataclass
class AbanInvoice:
    id: str
    pay_url: str
    status: str
    paid_rial: int | None = None


def _dig(data: dict, *keys):
    """خواندن فیلد از پاسخ؛ هم در ریشه و هم داخل data/invoice/result."""
    containers = [data]
    for k in ("data", "invoice", "result"):
        if isinstance(data.get(k), dict):
            containers.append(data[k])
    for c in containers:
        for key in keys:
            if c.get(key) not in (None, ""):
                return c[key]
    return None


def _parse(data: dict) -> AbanInvoice:
    inv_id = _dig(data, "id", "invoice_id", "uuid", "token")
    pay_url = _dig(data, "pay_url", "payment_url", "url", "link")
    status = str(_dig(data, "status", "state") or "").lower()
    paid = _dig(data, "paid_amount_rial", "paid_rial", "paid_amount")
    try:
        paid = int(paid) if paid is not None else None
    except (TypeError, ValueError):
        paid = None
    return AbanInvoice(id=str(inv_id or ""), pay_url=str(pay_url or ""), status=status, paid_rial=paid)


class AbanClient:
    timeout = 15

    def __init__(self, conf: SiteSettings | None = None):
        self.conf = conf or SiteSettings.get()
        if not self.conf.aban_api_base or not self.conf.aban_api_key_encrypted:
            raise AbanError("آدرس API یا کلید آبان گیت وی در تنظیمات سایت وارد نشده است.")
        self.base = self.conf.aban_api_base.rstrip("/")
        self.key = self.conf.get_aban_api_key()

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = self.base + "/" + path.lstrip("/")
        req = urllib.request.Request(
            url, method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={
                "Authorization": f"Bearer {self.key}",
                "X-API-KEY": self.key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode() or "{}"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            raise AbanError(f"آبان گیت وی HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AbanError(f"اتصال به آبان گیت وی ممکن نشد: {exc}") from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AbanError("پاسخ آبان گیت وی قابل خواندن نبود.") from exc
        if not isinstance(data, dict):
            raise AbanError("پاسخ آبان گیت وی ساختار مورد انتظار را ندارد.")
        return data

    def create(self, *, amount_rial: int, order_id: str, callback_url: str, description: str = "") -> AbanInvoice:
        data = self._request("POST", self.conf.aban_create_path, {
            "amount_rial": int(amount_rial),
            "order_id": order_id,
            "callback_url": callback_url,
            "description": description,
        })
        inv = _parse(data)
        if not inv.id or not inv.pay_url.startswith("https://"):
            log.warning("unexpected aban create response: %s", str(data)[:500])
            raise AbanError("پاسخ ساخت فاکتور آبان گیت وی کامل نبود (شناسه یا لینک پرداخت ندارد).")
        return inv

    def get(self, invoice_id: str) -> AbanInvoice:
        path = self.conf.aban_status_path.replace("{id}", urllib.request.quote(str(invoice_id), safe=""))
        inv = _parse(self._request("GET", path))
        if not inv.id:
            inv.id = str(invoice_id)
        return inv
