"""اتصال‌دهنده‌ی داده‌ی مشتری (kernel.tenantdb) و ارائه‌دهنده‌ی دسترسی فضای کار (kernel.workspace) از پلاگین پایگاه داده.

اتصال‌دهنده: نقش محدود «<user>_web» روی سرور PostGIS.

برای هر پایگاه داده یک نقش محدود ساخته می‌شود که عضو نقش همان کاربر است، superuser نیست و فقط به دیتابیس خودش
دسترسی دارد؛ رمز آن رمزنگاری‌شده در پنل می‌ماند. هرگز با کاربر ادمین سرور به داده‌ی مشتری وصل نمی‌شویم.
"""
from kernel import dataio, tenantdb, workspace

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


class TeamProvider(workspace.Provider):
    """قرارداد دسترسی فضای کار روی تیم و مالکیت پایگاه (databases/team.py)."""

    def get(self, request, pk, need="owner", qs=None):
        from . import team

        return team.get_db(request, pk, need, qs)

    def level(self, user, ws):
        from . import team

        return team.level(user, ws)

    def shared_with(self, user):
        from . import team

        return team.shared_with(user)

    def extra_role_name(self, ws, suffix):
        from . import team

        return team.role_name_for(ws, suffix)

    # ---- میزبانی و چرخه‌ی عمر
    def host(self, ws):
        from . import services

        return services.provisioner_for(ws.server)

    def role_name(self, ws, kind):
        if kind == "browser":
            return Provisioner.browser_role_name(ws.role_name)
        if kind == "ows":
            return Provisioner.ows_role_name(ws.role_name)
        raise ValueError(kind)

    def limits(self, plan):
        from . import services

        return services.limits_for(plan)

    def create_database(self, user, label, password, extensions, **kw):
        from . import services

        return services.create_database(user, label, password, extensions, **kw)

    def log_event(self, action, message="", *, user=None, database=None, success=True):
        from . import services

        services.logevent(action, message, user=user, database=database, success=success)

    def notify_user(self, user, subject, body):
        from . import services

        services._notify(user, subject, body)

    def plan_default(self, name, default=None):
        from .defaults import FREE_PLAN

        return FREE_PLAN.get(name, default)


class GdalProvider(dataio.Provider):
    """ورود و خروج داده با GDAL (databases/gdal.py)."""

    def import_layer(self, ws, path, layer, encoding):
        from . import gdal

        gdal.import_layer(ws, path, layer, encoding)

    def run_gdal(self, tool, args, *, env=None, timeout=None):
        from . import gdal

        kw = {"timeout": timeout} if timeout else {}
        return gdal._run([gdal._bin(tool), *args], env=env or gdal._env(), **kw)

    def pg_target(self, ws):
        from . import gdal

        return gdal.target(ws)
