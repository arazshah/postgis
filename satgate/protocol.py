"""امضای درخواست‌ها میان پنل و دروازه: HMAC-SHA256 روی زمان، روش، مسیر و چکیده‌ی بدنه."""
from __future__ import annotations

import hashlib
import hmac
import time

SKEW_S = 120
H_TIME, H_SIG = "X-Sat-Time", "X-Sat-Sig"


def _msg(ts: int | str, method: str, target: str, body: bytes) -> bytes:
    return f"{ts}\n{method.upper()}\n{target}\n{hashlib.sha256(body or b'').hexdigest()}".encode()


def sign(secret: str, method: str, target: str, body: bytes = b"", ts: int | None = None) -> dict[str, str]:
    ts = int(time.time()) if ts is None else int(ts)
    sig = hmac.new(secret.encode(), _msg(ts, method, target, body), hashlib.sha256).hexdigest()
    return {H_TIME: str(ts), H_SIG: sig}


def verify(secret: str, method: str, target: str, body: bytes, ts, sig, now: float | None = None) -> bool:
    if not secret or not sig:
        return False
    try:
        ts_i = int(ts)
    except (TypeError, ValueError):
        return False
    if abs((time.time() if now is None else now) - ts_i) > SKEW_S:
        return False
    good = hmac.new(secret.encode(), _msg(ts_i, method, target, body), hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, str(sig))
