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
            # هیچ دیتابیسی روی این سرور نباید برای همه (PUBLIC) باز باشد؛ نقش‌های فقط‌خواندنی QGIS Server
            # (عضو pg_read_all_data) فقط به دیتابیسی وصل می‌شوند که صریحاً CONNECT گرفته‌اند.
            public_dbs = [r[0] for r in cur.execute(
                "SELECT datname FROM pg_database WHERE datallowconn AND (datacl IS NULL OR "
                "EXISTS (SELECT 1 FROM aclexplode(datacl) a WHERE a.grantee = 0 AND a.privilege_type = 'CONNECT'))"
            ).fetchall()]
            for db in sorted(set(public_dbs) | ({"postgres", "template1", self.admin_db} & set(
                    r[0] for r in cur.execute("SELECT datname FROM pg_database").fetchall()))):
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
    def create_tenant(self, db_name: str, role_name: str, password: str, extensions: list[str],
                      limits: TenantLimits) -> list[str]:
        """
        نقش (کاربر) و دیتابیس را می‌سازد، محدودیت‌ها را اعمال و افزونه‌ها را نصب می‌کند.
        نام نقش و دیتابیس می‌تواند متفاوت باشد. در صورت خطا همه چیز برگردانده می‌شود.
        خروجی: فهرست افزونه‌های نصب‌شده.
        """
        _check_ident(db_name)
        _check_ident(role_name)
        exts = [_check_ext(e) for e in extensions]
        db_ident, role_ident = sql.Identifier(db_name), sql.Identifier(role_name)
        created_role = created_db = False
        try:
            with self.connect() as conn:
                cur = conn.cursor()
                if cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role_name,)).fetchone():
                    raise ProvisionError("کاربری با این نام از قبل روی سرور وجود دارد.")
                if cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db_name,)).fetchone():
                    raise ProvisionError("دیتابیسی با این نام از قبل روی سرور وجود دارد.")

                cur.execute(sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
                    "NOBYPASSRLS INHERIT CONNECTION LIMIT {} PASSWORD {}"
                ).format(role_ident, sql.Literal(int(limits.connection_limit)),
                         sql.Literal(scram_sha256_verifier(password))))
                created_role = True

                cur.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0")
                            .format(db_ident, role_ident))
                created_db = True

                cur.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db_ident))
                cur.execute(sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}").format(db_ident, role_ident))
                self._apply_role_limits(cur, role_name, limits)

            installed = []
            with self.connect(dbname=db_name) as conn:
                cur = conn.cursor()
                cur.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(role_ident))
                cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                for ext in exts:
                    cur.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {} CASCADE").format(sql.Identifier(ext)))
                    installed.append(ext)
                # جدول مختصات PostGIS: اجازه افزودن سیستم مختصات سفارشی به مالک
                if cur.execute("SELECT to_regclass('public.spatial_ref_sys')").fetchone()[0]:
                    cur.execute(sql.SQL(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON public.spatial_ref_sys TO {}").format(role_ident))
            return installed
        except Exception as exc:
            log.exception("create_tenant failed for %s", db_name)
            self._rollback(db_name, role_name, created_db, created_role)
            if isinstance(exc, ProvisionError):
                raise
            raise ProvisionError(f"ساخت پایگاه داده ناموفق بود: {exc}") from exc

    def _rollback(self, db_name: str, role_name: str, drop_db: bool, drop_role: bool):
        try:
            with self.connect() as conn:
                cur = conn.cursor()
                if drop_db:
                    cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db_name)))
                if drop_role:
                    cur.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role_name)))
        except Exception:  # noqa: BLE001
            log.exception("rollback failed for %s", db_name)

    # ------------------------------------------------------------------ نقش مرورگر (نمایش در پنل)
    @staticmethod
    def browser_role_name(role_name: str) -> str:
        return role_name[:59] + "_web"

    @staticmethod
    def ows_role_name(role_name: str) -> str:
        return role_name[:59] + "_ows"

    @classmethod
    def helper_roles(cls, role_name: str) -> list[str]:
        """نقش‌های داخلی هر پایگاه داده: مرورگر پنل و QGIS Server."""
        return [cls.browser_role_name(role_name), cls.ows_role_name(role_name)]

    def ensure_ows_role(self, db_name: str, role_name: str, password: str) -> str:
        """
        نقش فقط‌خواندنی برای QGIS Server (WMS/WFS): فقط به دیتابیس همین کاربر وصل می‌شود، تراکنش‌هایش
        فقط‌خواندنی است و در PostgreSQL 14+ فقط عضو pg_read_all_data است (هیچ حق نوشتنی ندارد).
        """
        _check_ident(db_name)
        _check_ident(role_name)
        ows = self.ows_role_name(role_name)
        ident = sql.Identifier(ows)
        with self.connect() as conn:
            cur = conn.cursor()
            verifier = sql.Literal(scram_sha256_verifier(password))
            if cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (ows,)).fetchone():
                cur.execute(sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(ident, verifier))
            else:
                cur.execute(sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
                    "INHERIT CONNECTION LIMIT 8 PASSWORD {}").format(ident, verifier))
            if int(cur.execute("SHOW server_version_num").fetchone()[0]) >= 140000:
                cur.execute(sql.SQL("GRANT pg_read_all_data TO {}").format(ident))
            else:
                cur.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(role_name), ident))
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db_name), ident))
            for key, value in (("default_transaction_read_only", "on"), ("statement_timeout", "30s"),
                               ("idle_in_transaction_session_timeout", "30s"), ("temp_file_limit", "256MB")):
                cur.execute(sql.SQL("ALTER ROLE {} SET {} = {}").format(ident, sql.Identifier(key),
                                                                     sql.Literal(value)))
        return ows

    def ensure_browser_role(self, db_name: str, role_name: str, password: str) -> str:
        """
        نقش محدود برای «مرورگر پایگاه داده» پنل: عضو نقش کاربر است (همان دسترسی‌ها)،
        superuser نیست و فقط به دیتابیس همان کاربر وصل می‌شود. رمزش را پنل رمزنگاری‌شده نگه می‌دارد.
        """
        _check_ident(db_name)
        _check_ident(role_name)
        web = self.browser_role_name(role_name)
        web_ident, role_ident = sql.Identifier(web), sql.Identifier(role_name)
        with self.connect() as conn:
            cur = conn.cursor()
            exists = cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (web,)).fetchone()
            verifier = sql.Literal(scram_sha256_verifier(password))
            if exists:
                cur.execute(sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(web_ident, verifier))
            else:
                cur.execute(sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
                    "INHERIT CONNECTION LIMIT 3 PASSWORD {}").format(web_ident, verifier))
            cur.execute(sql.SQL("GRANT {} TO {}").format(role_ident, web_ident))
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db_name), web_ident))
            for key, value in (("statement_timeout", "20s"), ("idle_in_transaction_session_timeout", "30s"),
                               ("temp_file_limit", "256MB")):
                cur.execute(sql.SQL("ALTER ROLE {} SET {} = {}").format(web_ident, sql.Identifier(key),
                                                                     sql.Literal(value)))
        return web

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

    def terminate_sessions(self, db_name: str | None = None, role_name: str | None = None):
        """قطع اتصال‌های یک دیتابیس و/یا یک کاربر (و نقش مرورگرش)."""
        with self.connect() as conn:
            if db_name:
                _check_ident(db_name)
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()", (db_name,))
            if role_name:
                _check_ident(role_name)
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE usename = ANY(%s) AND pid <> pg_backend_pid()",
                    ([role_name, *self.helper_roles(role_name)],))

    def set_readonly(self, name: str, readonly: bool):
        _check_ident(name)
        ident = sql.Identifier(name)
        with self.connect() as conn:
            if readonly:
                conn.execute(sql.SQL("ALTER DATABASE {} SET default_transaction_read_only = on").format(ident))
            else:
                conn.execute(sql.SQL("ALTER DATABASE {} RESET default_transaction_read_only").format(ident))
        self.terminate_sessions(db_name=name)

    def set_login(self, name: str, enabled: bool):
        """تعلیق/فعال‌سازی ورود کاربر."""
        _check_ident(name)
        with self.connect() as conn:
            for role in (name, *self.helper_roles(name)):
                if conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                    conn.execute(sql.SQL("ALTER ROLE {} " + ("LOGIN" if enabled else "NOLOGIN"))
                                 .format(sql.Identifier(role)))
        if not enabled:
            self.terminate_sessions(role_name=name)

    def drop_tenant(self, db_name: str, role_name: str | None = None):
        _check_ident(db_name)
        role_name = role_name or db_name
        _check_ident(role_name)
        with self.connect() as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db_name)))
            for role in (*self.helper_roles(role_name), role_name):
                conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))

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

    # ------------------------------------------------------------------ مالکیت و بازگردانی
    def reassign_browser_objects(self, db_name: str, role_name: str) -> None:
        """اشیایی که نقش مرورگر ساخته (نسخه‌های قدیمی کنسول SQL) را به مالکیت نقش کاربر برمی‌گرداند."""
        _check_ident(db_name)
        _check_ident(role_name)
        web = self.browser_role_name(role_name)
        with self.connect(dbname=db_name) as conn:
            if conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (web,)).fetchone():
                conn.execute(sql.SQL("REASSIGN OWNED BY {} TO {}").format(sql.Identifier(web),
                                                                          sql.Identifier(role_name)))

    def _give_to_role(self, cur, role_name: str) -> None:
        """همه اشیای کاربری (نه اشیای افزونه‌ها) در دیتابیس فعلی را به نقش کاربر می‌دهد."""
        role = sql.Identifier(role_name)
        rows = cur.execute("""
            SELECT n.nspname, c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r','p','v','m','S','f')
              AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg\\_%%'
              AND pg_get_userbyid(c.relowner) <> %s
              AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e')
        """, (role_name,)).fetchall()
        kinds = {"r": "TABLE", "p": "TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW", "S": "SEQUENCE",
                 "f": "FOREIGN TABLE"}
        for nsp, rel, kind in rows:
            if kind == "S" and cur.execute(
                    "SELECT 1 FROM pg_depend d JOIN pg_class s ON s.oid=d.objid JOIN pg_namespace n ON "
                    "n.oid=s.relnamespace WHERE n.nspname=%s AND s.relname=%s AND d.deptype IN ('a','i')",
                    (nsp, rel)).fetchone():
                continue  # دنباله وابسته به ستون همراه جدولش منتقل می‌شود
            cur.execute(sql.SQL("ALTER {} {} OWNER TO {}").format(sql.SQL(kinds[kind]),
                                                                 sql.Identifier(nsp, rel), role))
        for (nsp,) in cur.execute("""
            SELECT n.nspname FROM pg_namespace n
            WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg\\_%%'
              AND pg_get_userbyid(n.nspowner) <> %s
              AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = n.oid AND d.deptype = 'e')
        """, (role_name,)).fetchall():
            cur.execute(sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(sql.Identifier(nsp), role))
        for (fid,) in cur.execute("""
            SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg\\_%%'
              AND pg_get_userbyid(p.proowner) <> %s
              AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')
        """, (role_name,)).fetchall():
            kw = "PROCEDURE" if cur.execute("SELECT prokind FROM pg_proc WHERE oid=%s::regprocedure",
                                            (fid,)).fetchone()[0] == "p" else "FUNCTION"
            cur.execute(sql.SQL("ALTER {} {} OWNER TO {}").format(sql.SQL(kw), sql.SQL(fid), role))

    def create_scratch_database(self, scratch: str, role_name: str) -> None:
        _check_ident(scratch)
        _check_ident(role_name)
        with self.connect() as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch)))
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(scratch), sql.Identifier(role_name)))
            conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(scratch)))

    def drop_database(self, db_name: str) -> None:
        _check_ident(db_name)
        with self.connect() as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db_name)))

    def finish_restore(self, scratch: str, role_name: str) -> dict:
        """بعد از pg_restore در دیتابیس موقت: مالکیت به کاربر، شمارش جدول‌ها برای بررسی سلامت."""
        with self.connect(dbname=scratch) as conn:
            cur = conn.cursor()
            self._give_to_role(cur, role_name)
            cur.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(role_name)))
            cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            if cur.execute("SELECT to_regclass('public.spatial_ref_sys')").fetchone()[0]:
                cur.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON public.spatial_ref_sys TO {}").format(
                    sql.Identifier(role_name)))
            tables = cur.execute("""
                SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE c.relkind IN ('r','p') AND n.nspname NOT IN ('pg_catalog','information_schema')
                  AND n.nspname NOT LIKE 'pg\\_%%'
                  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e')
            """).fetchone()[0]
        return {"tables": tables}

    def swap_in_restored(self, db_name: str, scratch: str, role_name: str) -> str:
        """دیتابیس بازگردانی‌شده را جای دیتابیس فعلی می‌گذارد؛ نسخه قبلی با پسوند _old نگه داشته می‌شود."""
        _check_ident(db_name)
        _check_ident(scratch)
        _check_ident(role_name)
        old = (db_name[:54] + "_old_rst")
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(old)))
            cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = ANY(%s) "
                        "AND pid <> pg_backend_pid()", ([db_name, scratch],))
            cur.execute(sql.SQL("ALTER DATABASE {} RENAME TO {}").format(sql.Identifier(db_name), sql.Identifier(old)))
            cur.execute(sql.SQL("ALTER DATABASE {} RENAME TO {}").format(sql.Identifier(scratch),
                                                                       sql.Identifier(db_name)))
            db = sql.Identifier(db_name)
            cur.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db))
            cur.execute(sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}").format(db, sql.Identifier(role_name)))
            for helper in self.helper_roles(role_name):
                if cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (helper,)).fetchone():
                    cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db, sql.Identifier(helper)))
        return old

