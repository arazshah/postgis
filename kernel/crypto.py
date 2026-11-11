"""رمزنگاری مقدارهای حساس ذخیره‌شده (رمز ادمین سرورها، کلیدهای API) با کلید استقرار؛ سرویس هسته."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    key = settings.CREDENTIALS_ENCRYPTION_KEY
    if key:
        try:
            return Fernet(key.encode())
        except (ValueError, TypeError):
            pass  # کلید دلخواه؛ از آن مشتق می‌کنیم
        raw = key
    else:
        raw = settings.SECRET_KEY
    derived = base64.urlsafe_b64encode(hashlib.sha256(("geopaygah:" + raw).encode()).digest())
    return Fernet(derived)


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("رمزگشایی ممکن نیست؛ کلید رمزنگاری تغییر کرده است.") from exc
