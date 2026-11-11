"""اتصال‌دهنده‌ی پایگاه داده‌ی مشتری برای هسته (kernel.tenantdb): نقش محدود «<user>_web» روی سرور PostGIS.

برای هر پایگاه داده یک نقش محدود ساخته می‌شود که عضو نقش همان کاربر است، superuser نیست و فقط به دیتابیس خودش
دسترسی دارد؛ رمز آن رمزنگاری‌شده در پنل می‌ماند. هرگز با کاربر ادمین سرور به داده‌ی مشتری وصل نمی‌شویم.
"""
from kernel import tenantdb

from . import crypto
from .provisioner import Provisioner, ProvisionError


def ensure_role(db, force: bool = False) -> str:
    """رمز نقش محدود این پایگاه؛ اگر نیست (یا force) نقش را می‌سازد و رمز تازه ذخیره می‌کند."""
    if db.browser_password_encrypted and not force:
        return crypto.decrypt(db.browser_password_encrypted)
    password = crypto.generate_password(28)
    try:
        Provisioner.for_server(db.server).ensure_browser_role(db.db_name, db.role_name, password)
    except ProvisionError as exc:
        raise tenantdb.TenantError(f"آماده‌سازی دسترسی مرورگر ممکن نشد: {exc}") from exc
    db.browser_password_encrypted = crypto.encrypt(password)
    db.save(update_fields=["browser_password_encrypted"])
    return password


class PostgisConnector(tenantdb.Connector):
    def params(self, ws, force: bool = False) -> dict:
        server = ws.server
        return {
            "host": server.host, "port": server.port, "dbname": ws.db_name,
            "user": Provisioner.browser_role_name(ws.role_name), "password": ensure_role(ws, force),
            "sslmode": server.sslmode, "connect_timeout": 8, "application_name": "geopaygah-explorer",
        }

    def owner_role(self, ws) -> str:
        return ws.role_name
