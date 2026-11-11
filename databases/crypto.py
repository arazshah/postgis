"""رمزنگاری گذرواژه‌های حساس و ساخت verifier از نوع SCRAM برای PostgreSQL."""
import base64
import hashlib
import hmac
import os

from kernel.crypto import (  # noqa: F401  رمزنگاری سرویس هسته است؛ اینجا برای سازگاری
    _fernet,
    decrypt,
    encrypt,
    generate_password,
)


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
