"""امضای درخواست‌ها میان پنل و دروازه: HMAC-SHA256 روی زمان، روش، مسیر و چکیده‌ی بدنه.

علت رد شدن دقیق گزارش می‌شود (check): نبود امضا، اختلاف ساعت، کلید متفاوت یا امضای ناسازگار؛
تا مدیر به‌جای حدس زدن بداند کدام را باید درست کند.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import NamedTuple

SKEW_S = 120
H_TIME, H_SIG, H_KID = "X-Sat-Time", "X-Sat-Sig", "X-Sat-Kid"


class Check(NamedTuple):
    ok: bool
    reason: str      # ok | no_secret | missing | skew | key | signature
    skew_s: int = 0  # مثبت: ساعت فرستنده جلوتر از گیرنده است


def key_id(secret: str) -> str:
    """اثر انگشت کوتاه و نمکی کلید؛ فقط برای مقایسه‌ی «آیا کلیدها یکی‌اند» (چیزی از کلید فاش نمی‌کند)."""
    return hashlib.sha256(b"satgate-kid:" + secret.encode()).hexdigest()[:8]


def _msg(ts: int | str, method: str, target: str, body: bytes) -> bytes:
    return f"{ts}\n{method.upper()}\n{target}\n{hashlib.sha256(body or b'').hexdigest()}".encode()


def sign(secret: str, method: str, target: str, body: bytes = b"", ts: int | None = None) -> dict[str, str]:
    ts = int(time.time()) if ts is None else int(ts)
    sig = hmac.new(secret.encode(), _msg(ts, method, target, body), hashlib.sha256).hexdigest()
    return {H_TIME: str(ts), H_SIG: sig, H_KID: key_id(secret)}


def check(secret: str, method: str, target: str, body: bytes, ts, sig, kid: str | None = None,
          now: float | None = None) -> Check:
    if not secret:
        return Check(False, "no_secret")
    if not sig or ts in (None, ""):
        return Check(False, "missing")
    try:
        ts_i = int(ts)
    except (TypeError, ValueError):
        return Check(False, "missing")
    skew = ts_i - int(time.time() if now is None else now)
    if abs(skew) > SKEW_S:
        return Check(False, "skew", skew)
    if kid and not hmac.compare_digest(str(kid), key_id(secret)):
        return Check(False, "key", skew)
    good = hmac.new(secret.encode(), _msg(ts_i, method, target, body), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, str(sig)):
        return Check(False, "signature", skew)
    return Check(True, "ok", skew)


def verify(secret: str, method: str, target: str, body: bytes, ts, sig, now: float | None = None,
           kid: str | None = None) -> bool:
    return check(secret, method, target, body, ts, sig, kid, now).ok
