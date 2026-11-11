"""رمز یک‌بارمصرف زمانی (TOTP، RFC 6238) برای ورود دومرحله‌ی پنل مدیریت؛ بدون وابستگی بیرونی.

SHA-1، ۶ رقم، گام ۳۰ ثانیه (سازگار با Google Authenticator، Authy، Aegis و …). رمز هر گام فقط یک‌بار پذیرفته می‌شود.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6
WINDOW = 1  # یک گام قبل و بعد (اختلاف ساعت)
RECOVERY_COUNT = 8


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))


def hotp(secret: str, counter: int, digits: int = DIGITS) -> str:
    mac = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    return f"{(struct.unpack('>I', mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits:0{digits}d}"


def step_at(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP)


def code_at(secret: str, now: float | None = None) -> str:
    return hotp(secret, step_at(now))


def verify(secret: str, code: str, last_step: int = 0, now: float | None = None) -> int | None:
    """گام تطبیق‌یافته را برمی‌گرداند یا None؛ گامی که قبلاً پذیرفته شده (≤ last_step) رد می‌شود (بازپخش)."""
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == DIGITS):
        return None
    now_step, hit = step_at(now), None
    for step in range(now_step - WINDOW, now_step + WINDOW + 1):
        if hmac.compare_digest(hotp(secret, step), code) and hit is None:  # همه‌ی گام‌ها را می‌سنجیم (زمان ثابت)
            hit = step
    return hit if hit is not None and hit > last_step else None


def otpauth_uri(account: str, secret: str, issuer: str = "ژئوپایگاه") -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP}&algorithm=SHA1"


def pretty(secret: str) -> str:
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


# ---------------------------------------------------------------------- کدهای بازیابی
def new_recovery_codes() -> list[str]:
    out = []
    for _ in range(RECOVERY_COUNT):
        raw = base64.b32encode(secrets.token_bytes(7)).decode().rstrip("=").lower()[:10]
        out.append(f"{raw[:5]}-{raw[5:]}")
    return out


def recovery_hash(code: str) -> str:
    return hashlib.sha256((code or "").strip().lower().replace("-", "").replace(" ", "").encode()).hexdigest()
