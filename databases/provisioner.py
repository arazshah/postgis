"""
لایه ارتباط با سرور PostgreSQL/PostGIS.

اصول امنیتی:
- همه نام‌ها با sql.Identifier نقل‌قول می‌شوند و قبل از آن با الگوی سخت‌گیرانه اعتبارسنجی می‌شوند.
- رمز کاربر به‌صورت verifier از نوع SCRAM ارسال می‌شود تا رمز خام در لاگ سرور ثبت نشود.
- افزونه‌ها فقط از فهرست سفید (مدل Extension) نصب می‌شوند.
"""
from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass, field

import psycopg
from psycopg import sql

from .crypto import scram_sha256_verifier

log = logging.getLogger(__name__)

_IDENT = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
_EXT = re.compile(r"^[a-z0-9_\-]{2,63}$")


class ProvisionError(Exception):
    """خطای قابل نمایش به ادمین/کاربر."""


def _check_ident(name: str) -> str:
    if not _IDENT.match(name or ""):
        raise ProvisionError(f"شناسه نامعتبر: {name!r}")
    return name


def _check_ext(name: str) -> str:
    if not _EXT.match(name or ""):
        raise ProvisionError(f"نام افزونه نامعتبر: {name!r}")
    return name


@dataclass
class TenantLimits:
    connection_limit: int = 5
    statement_timeout_s: int = 60
    idle_tx_timeout_s: int = 300
    temp_file_limit_mb: int = 2048
    extra: dict = field(default_factory=dict)


@dataclass
class ServerInfo:
    ok: bool
    message: str = ""
    server_version: str = ""
    postgis_version: str = ""
    is_superuser: bool = False
    can_create_db: bool = False
    can_create_role: bool = False
    available_extensions: list[str] = field(default_factory=list)
    password_encryption: str = ""
    ssl_enabled: bool = False
    hardened: bool = False


class Provisioner:
    def __init__(self, conn_kwargs: dict):
        self.conn_kwargs = dict(conn_kwargs)
        self.admin_db = self.conn_kwargs.get("dbname", "postgres")

    @classmethod
    def for_server(cls, server) -> Provisioner:
        return cls(server.connection_kwargs())

    @contextmanager
    def connect(self, dbname: str | None = None):
        kwargs = dict(self.conn_kwargs)
        if dbname:
            kwargs["dbname"] = dbname
        try:
            conn = psycopg.connect(autocommit=True, **kwargs)
        except psycopg.OperationalError as exc:
            raise ProvisionError(f"اتصال به سرور دیتابیس ممکن نشد: {exc}".strip()) from exc
        except (UnicodeError, ValueError, OSError, psycopg.Error) as exc:
            # مثلاً آدرس نامعتبر در فیلد host؛ هرگز نباید به خطای 500 برسد
            raise ProvisionError(f"آدرس یا تنظیمات اتصال نامعتبر است: {exc}") from exc
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ بررسی سرور
    def check(self) -> ServerInfo:
        try:
            with self.connect() as conn:
                cur = conn.cursor()
                version = cur.execute("SHOW server_version").fetchone()[0]
                row = cur.execute(
                    "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user"
                ).fetchone()
                exts = [r[0] for r in cur.execute(
                    "SELECT name FROM pg_available_extensions ORDER BY name").fetchall()]
                pg_row = cur.execute(
                    "SELECT default_version FROM pg_available_extensions WHERE name='postgis'").fetchone()
                pwenc = cur.execute("SHOW password_encryption").fetchone()[0]
                ssl_on = cur.execute("SHOW ssl").fetchone()[0] == "on"
                public_can_connect = cur.execute(
                    "SELECT has_database_privilege('public', %s, 'CONNECT')", (self.admin_db,)).fetchone()[0]
        except ProvisionError as exc:
            return ServerInfo(ok=False, message=str(exc))
        info = ServerInfo(
            ok=True,
            server_version=version,
            postgis_version=pg_row[0] if pg_row else "",
            is_superuser=bool(row and row[0]),
            can_create_db=bool(row and (row[0] or row[1])),
            can_create_role=bool(row and (row[0] or row[2])),
            available_extensions=exts,
            password_encryption=pwenc,
            ssl_enabled=ssl_on,
            hardened=not public_can_connect,
        )
        problems = []
        if not info.postgis_version:
            problems.append("PostGIS روی این سرور نصب نیست")
        if not info.is_superuser:
            problems.append("کاربر ادمین superuser نیست؛ نصب PostGIS و اعمال محدودیت‌ها ممکن است شکست بخورد")
        if pwenc != "scram-sha-256":
            problems.append("password_encryption روی scram-sha-256 نیست")
        if not ssl_on:
            problems.append("SSL روی سرور فعال نیست؛ حالت SSL کاربران را روی prefer یا disable بگذارید یا SSL را فعال کنید")
        if not info.hardened:
            problems.append("دسترسی عمومی به دیتابیس‌های سیستمی هنوز بسته نشده (اقدام «ایمن‌سازی سرور» را اجرا کنید)")
        info.message = "اتصال برقرار است." + (" هشدار: " + "؛ ".join(problems) if problems else "")
        return info

    def harden(self) -> list[str]:
        """
        ایمن‌سازی سرور تازه: کاربران مشتری نباید به دیتابیس‌های سیستمی وصل شوند یا در آن‌ها چیزی بسازند.
        چندباره اجراشدنی است.
        """
        done = []
        with self.connect() as conn:
            cur = conn.cursor()
            for db in ("postgres", "template1", self.admin_db):
                if cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db,)).fetchone():
                    cur.execute(sql.SQL("REVOKE CONNECT, TEMPORARY ON DATABASE {} FROM PUBLIC").format(sql.Identifier(db)))
                    done.append(f"REVOKE CONNECT ON {db}")
            if cur.execute("SHOW password_encryption").fetchone()[0] != "scram-sha-256":
                cur.execute("ALTER SYSTEM SET password_encryption = 'scram-sha-256'")
                cur.execute("SELECT pg_reload_conf()")
                done.append("password_encryption=scram-sha-256")
        for db in {"postgres", self.admin_db}:
            try:
                with self.connect(dbname=db) as conn:
                    conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                    done.append(f"REVOKE CREATE ON {db}.public")
            except ProvisionError:
                pass
        return done

    # ------------------------------------------------------------------ ساخت
    def create_tenant(self, name: str, password: str, extensions: list[str], limits: TenantLimits) -> list[str]:
        """
        نقش و دیتابیس هم‌نام می‌سازد (برای pg_hba با sameuser)، محدودیت‌ها را اعمال و افزونه‌ها را نصب می‌کند.
        در صورت خطا همه چیز را برمی‌گرداند. خروجی: فهرست افزونه‌های نصب‌شده.
        """
        _check_ident(name)
        exts = [_check_ext(e) for e in extensions]
        ident = sql.Identifier(name)
        created_role = created_db = False
        try:
            with self.connect() as conn:
                cur = conn.cursor()
                if cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (name,)).fetchone():
                    raise ProvisionError("نقشی با این نام از قبل روی سرور وجود دارد.")
                if cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
                    raise ProvisionError("دیتابیسی با این نام از قبل روی سرور وجود دارد.")

                cur.execute(sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
                    "NOBYPASSRLS INHERIT CONNECTION LIMIT {} PASSWORD {}"
                ).format(ident, sql.Literal(int(limits.connection_limit)),
                         sql.Literal(scram_sha256_verifier(password))))
                created_role = True

                cur.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0")
                            .format(ident, ident))
                created_db = True

                cur.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(ident))
                cur.execute(sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}").format(ident, ident))
                self._apply_role_limits(cur, name, limits)

            installed = []
            with self.connect(dbname=name) as conn:
                cur = conn.cursor()
                cur.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(ident))
                cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                for ext in exts:
                    cur.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {} CASCADE").format(sql.Identifier(ext)))
                    installed.append(ext)
                # جدول مختصات PostGIS: اجازه افزودن سیستم مختصات سفارشی به مالک
                if cur.execute("SELECT to_regclass('public.spatial_ref_sys')").fetchone()[0]:
                    cur.execute(sql.SQL(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON public.spatial_ref_sys TO {}").format(ident))
            return installed
        except Exception as exc:
            log.exception("create_tenant failed for %s", name)
            self._rollback(name, created_db, created_role)
            if isinstance(exc, ProvisionError):
                raise
            raise ProvisionError(f"ساخت پایگاه داده ناموفق بود: {exc}") from exc

    def _rollback(self, name: str, drop_db: bool, drop_role: bool):
        try:
            with self.connect() as conn:
                cur = conn.cursor()
                if drop_db:
                    cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
                if drop_role:
                    cur.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))
        except Exception:  # noqa: BLE001
            log.exception("rollback failed for %s", name)

    def _apply_role_limits(self, cur, name: str, limits: TenantLimits):
        ident = sql.Identifier(name)
        settings_map = {
            "statement_timeout": f"{int(limits.statement_timeout_s)}s",
            "idle_in_transaction_session_timeout": f"{int(limits.idle_tx_timeout_s)}s",
            "temp_file_limit": f"{int(limits.temp_file_limit_mb)}MB",
            **limits.extra,
        }
        for key, value in settings_map.items():
            if not re.match(r"^[a-z_]+$", key):
                raise ProvisionError(f"تنظیم نامعتبر: {key}")
            cur.execute(sql.SQL("ALTER ROLE {} SET {} = {}").format(ident, sql.Identifier(key), sql.Literal(value)))
        cur.execute(sql.SQL("ALTER ROLE {} CONNECTION LIMIT {}").format(ident, sql.Literal(int(limits.connection_limit))))

    def apply_limits(self, name: str, limits: TenantLimits):
        _check_ident(name)
        with self.connect() as conn:
            self._apply_role_limits(conn.cursor(), name, limits)

    # ------------------------------------------------------------------ عملیات
    def set_password(self, name: str, password: str):
        _check_ident(name)
        with self.connect() as conn:
            conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                sql.Identifier(name), sql.Literal(scram_sha256_verifier(password))))

    def install_extension(self, name: str, ext: str):
        _check_ident(name)
        _check_ext(ext)
        with self.connect(dbname=name) as conn:
            conn.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {} CASCADE").format(sql.Identifier(ext)))

    def installed_extensions(self, name: str) -> list[str]:
        _check_ident(name)
        with self.connect(dbname=name) as conn:
            return [r[0] for r in conn.execute("SELECT extname FROM pg_extension ORDER BY extname").fetchall()]

    def terminate_sessions(self, name: str):
        _check_ident(name)
        with self.connect() as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()", (name,))

    def set_readonly(self, name: str, readonly: bool):
        _check_ident(name)
        ident = sql.Identifier(name)
        with self.connect() as conn:
            if readonly:
                conn.execute(sql.SQL("ALTER DATABASE {} SET default_transaction_read_only = on").format(ident))
            else:
                conn.execute(sql.SQL("ALTER DATABASE {} RESET default_transaction_read_only").format(ident))
        self.terminate_sessions(name)

    def set_login(self, name: str, enabled: bool):
        """تعلیق/فعال‌سازی ورود کاربر."""
        _check_ident(name)
        with self.connect() as conn:
            conn.execute(sql.SQL("ALTER ROLE {} " + ("LOGIN" if enabled else "NOLOGIN")).format(sql.Identifier(name)))
        if not enabled:
            self.terminate_sessions(name)

    def drop_tenant(self, name: str):
        _check_ident(name)
        ident = sql.Identifier(name)
        with self.connect() as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(ident))
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(ident))

    def database_sizes(self, names: list[str]) -> dict[str, int]:
        names = [_check_ident(n) for n in names]
        if not names:
            return {}
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT datname, pg_database_size(datname) FROM pg_database WHERE datname = ANY(%s)",
                (names,)).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def active_connections(self, name: str) -> int:
        _check_ident(name)
        with self.connect() as conn:
            return conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (name,)).fetchone()[0]
