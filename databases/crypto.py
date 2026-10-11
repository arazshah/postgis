"""رمزنگاری گذرواژه‌های حساس و ساخت verifier از نوع SCRAM برای PostgreSQL."""
import base64
import hashlib
import hmac
import os
import secrets
import string

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


def scram_sha256_verifier(password: str, iterations: int = 4096) -> str:
    """
    همان فرمتی که PostgreSQL برای password_encryption=scram-sha-256 ذخیره می‌کند.
    با ارسال verifier به‌جای رمز خام، رمز کاربر هیچ‌وقت در لاگ‌های سرور دیتابیس ثبت نمی‌شود.
    """
    salt = os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def generate_password(length: int = 20) -> str:
    """رمز تصادفی بدون کاراکترهای دردسرساز در رشته اتصال."""
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return pw
