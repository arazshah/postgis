"""
مرورگر ساده پایگاه داده برای کاربران (چیزی شبیه pgAdmin، خیلی ساده‌تر).

امنیت:
- هرگز با کاربر ادمین سرور وصل نمی‌شود. برای هر پایگاه داده یک نقش محدود «<user>_web» ساخته می‌شود
  که عضو نقش همان کاربر است، superuser نیست و فقط به دیتابیس خودش دسترسی دارد.
- نام schema و جدول فقط بعد از پیدا شدن در کاتالوگ استفاده می‌شود و همیشه با sql.Identifier نقل‌قول می‌شود.
- کنسول SQL با prepare=True اجرا می‌شود؛ یعنی دقیقاً یک دستور در هر اجرا (چند دستور با ; رد می‌شود).
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import psycopg
from psycopg import sql

from . import crypto
from .provisioner import Provisioner, ProvisionError

HIDDEN_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast", "topology", "tiger", "tiger_data"}
HIDDEN_TABLES = {("public", t) for t in ("spatial_ref_sys", "geometry_columns", "geography_columns",
                                        "raster_columns", "raster_overviews")}
CELL_MAX = 200
PAGE_SIZE = 50
MAP_LIMIT = 2000
EXPORT_LIMIT = 100_000
SQL_MAX_ROWS = 500


class ExplorerError(Exception):
    pass


@dataclass
class TableRef:
    schema: str
    name: str
    oid: int
    kind: str  # r=table, v=view, m=materialized view, p=partitioned, f=foreign
    rows_estimate: int = 0
    size_bytes: int = 0
    geometry: list[dict] = field(default_factory=list)

    @property
    def kind_label(self) -> str:
        return {"r": "جدول", "p": "جدول", "v": "نما (view)", "m": "نمای ذخیره‌شده", "f": "جدول خارجی"}.get(
            self.kind, self.kind)

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}"


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<باینری {len(bytes(value))} بایت>"
    text = str(value)
    return text if len(text) <= CELL_MAX else text[:CELL_MAX] + "…"


class Explorer:
    def __init__(self, db):
        self.db = db
        self.server = db.server

    # ------------------------------------------------------------------ اتصال
    def _ensure_role(self, force: bool = False) -> str:
        if self.db.browser_password_encrypted and not force:
            return crypto.decrypt(self.db.browser_password_encrypted)
        password = crypto.generate_password(28)
        try:
            Provisioner.for_server(self.server).ensure_browser_role(self.db.db_name, self.db.role_name, password)
        except ProvisionError as exc:
            raise ExplorerError(f"آماده‌سازی دسترسی مرورگر ممکن نشد: {exc}") from exc
        self.db.browser_password_encrypted = crypto.encrypt(password)
        self.db.save(update_fields=["browser_password_encrypted"])
        return password

    def _kwargs(self, password: str) -> dict:
        return {
            "host": self.server.host, "port": self.server.port, "dbname": self.db.db_name,
            "user": Provisioner.browser_role_name(self.db.role_name), "password": password,
            "sslmode": self.server.sslmode, "connect_timeout": 8, "application_name": "geopaygah-explorer",
        }

    @contextmanager
    def connect(self, read_only: bool = True):
        try:
            conn = psycopg.connect(**self._kwargs(self._ensure_role()))
        except psycopg.OperationalError as exc:
            if "password authentication failed" in str(exc) or "does not exist" in str(exc):
                try:
                    conn = psycopg.connect(**self._kwargs(self._ensure_role(force=True)))
                except psycopg.Error as exc2:
                    raise ExplorerError(f"اتصال به پایگاه داده ممکن نشد: {exc2}") from exc2
            else:
                raise ExplorerError(f"اتصال به پایگاه داده ممکن نشد: {exc}") from exc
        conn.read_only = read_only
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ فهرست جدول‌ها
    def tables(self) -> list[TableRef]:
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT n.nspname, c.relname, c.oid, c.relkind,
                       GREATEST(c.reltuples, 0)::bigint,
                       CASE WHEN c.relkind IN ('r','m','p') THEN pg_total_relation_size(c.oid) ELSE 0 END
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r','v','m','p','f')
                  AND n.nspname NOT LIKE 'pg\\_temp%%' AND n.nspname NOT LIKE 'pg\\_toast%%'
                  AND NOT c.relispartition
                  AND has_table_privilege(c.oid, 'SELECT')
                ORDER BY n.nspname, c.relname
            """).fetchall()
            geoms = self._geometry_columns(conn)
            out = []
            exact_budget = 40  # جدول‌های کوچکِ تحلیل‌نشده را دقیق می‌شماریم
            for schema, name, oid, kind, est, size in rows:
                if schema in HIDDEN_SCHEMAS or (schema, name) in HIDDEN_TABLES:
                    continue
                if est <= 0 and kind in ("r", "p", "m") and size < 64 * 1024 * 1024 and exact_budget > 0:
                    exact_budget -= 1
                    try:
                        est = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(
                            sql.Identifier(schema, name))).fetchone()[0]
                    except psycopg.Error:
                        conn.rollback()
                out.append(TableRef(schema, name, oid, kind, est, size, geoms.get((schema, name), [])))
        return out

    @staticmethod
    def _geometry_columns(conn) -> dict[tuple[str, str], list[dict]]:
        result: dict[tuple[str, str], list[dict]] = {}
        if not conn.execute("SELECT to_regclass('public.geometry_columns')").fetchone()[0]:
            return result
        for schema, table, col, gtype, srid in conn.execute(
                "SELECT f_table_schema, f_table_name, f_geometry_column, type, srid FROM public.geometry_columns"):
            result.setdefault((schema, table), []).append(
                {"column": col, "type": gtype, "srid": srid, "geography": False})
        if conn.execute("SELECT to_regclass('public.geography_columns')").fetchone()[0]:
            for schema, table, col, gtype, srid in conn.execute(
                    "SELECT f_table_schema, f_table_name, f_geography_column, type, srid "
                    "FROM public.geography_columns"):
                result.setdefault((schema, table), []).append(
                    {"column": col, "type": gtype, "srid": srid, "geography": True})
        return result

    # ------------------------------------------------------------------ یک جدول
    def find(self, schema: str, name: str) -> TableRef:
        for t in self.tables():
            if t.schema == schema and t.name == name:
                return t
        raise ExplorerError("جدول پیدا نشد یا به آن دسترسی ندارید.")

    def columns(self, table: TableRef) -> list[dict]:
        with self.connect() as conn:
            pk = {r[0] for r in conn.execute("""
                SELECT a.attname FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = %s AND i.indisprimary""", (table.oid,))}
            rows = conn.execute("""
                SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                       pg_get_expr(d.adbin, d.adrelid), t.typname
                FROM pg_attribute a
                JOIN pg_type t ON t.oid = a.atttypid
                LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped
                ORDER BY a.attnum""", (table.oid,)).fetchall()
        return [{"name": n, "type": t, "not_null": nn, "default": d or "", "pk": n in pk,
                 "spatial": base in ("geometry", "geography"), "base": base}
                for n, t, nn, d, base in rows]

    def _select_list(self, cols: list[dict]):
        parts = []
        for c in cols:
            ident = sql.Identifier(c["name"])
            if c["spatial"]:
                parts.append(sql.SQL("left(ST_AsText({c}::geometry), 120)").format(c=ident))
            else:
                parts.append(sql.SQL("{}::text").format(ident))
        return sql.SQL(", ").join(parts)

    def rows(self, table: TableRef, page: int = 1) -> dict:
        cols = self.columns(table)
        page = max(page, 1)
        rel = sql.Identifier(table.schema, table.name)
        with self.connect() as conn:
            exact = None
            if table.rows_estimate < 200_000:
                exact = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(rel)).fetchone()[0]
            data = conn.execute(sql.SQL("SELECT {} FROM {} LIMIT {} OFFSET {}").format(
                self._select_list(cols), rel, sql.Literal(PAGE_SIZE), sql.Literal((page - 1) * PAGE_SIZE))).fetchall()
        total = exact if exact is not None else table.rows_estimate
        return {
            "columns": cols,
            "rows": [[_cell(v) for v in r] for r in data],
            "page": page,
            "offset": (page - 1) * PAGE_SIZE,
            "pages": max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
            "total": total,
            "total_exact": exact is not None,
        }

    # ------------------------------------------------------------------ نقشه و خروجی
    def geojson(self, table: TableRef, geom_column: str | None = None, limit: int = MAP_LIMIT) -> str:
        if not table.geometry:
            raise ExplorerError("این جدول ستون مکانی ندارد.")
        names = [g["column"] for g in table.geometry]
        geom_column = geom_column if geom_column in names else names[0]
        cols = [c for c in self.columns(table) if not c["spatial"]]
        g = sql.Identifier(geom_column)
        props = sql.SQL(", ").join(sql.Identifier(c["name"]) for c in cols)
        inner = sql.SQL(
            "SELECT {props}{comma} CASE WHEN ST_SRID({g}::geometry) IN (0, 4326) THEN {g}::geometry "
            "ELSE ST_Transform({g}::geometry, 4326) END AS __geom "
            "FROM {rel} WHERE {g} IS NOT NULL LIMIT {lim}"
        ).format(props=props, comma=sql.SQL(",") if cols else sql.SQL(""), g=g,
                 rel=sql.Identifier(table.schema, table.name), lim=sql.Literal(int(limit)))
        query = sql.SQL(
            "SELECT json_build_object('type','FeatureCollection','features', "
            "COALESCE(json_agg(ST_AsGeoJSON(sub.*, '__geom', 6)::json), '[]'::json))::text "
            "FROM ({}) sub").format(inner)
        with self.connect() as conn:
            return conn.execute(query).fetchone()[0]

    def export_rows(self, table: TableRef):
        """سطرها برای CSV؛ ستون‌های مکانی به WKT."""
        cols = self.columns(table)
        parts = [sql.SQL("ST_AsText({}::geometry)").format(sql.Identifier(c["name"])) if c["spatial"]
                 else sql.SQL("{}::text").format(sql.Identifier(c["name"])) for c in cols]
        query = sql.SQL("SELECT {} FROM {} LIMIT {}").format(
            sql.SQL(", ").join(parts), sql.Identifier(table.schema, table.name), sql.Literal(EXPORT_LIMIT))
        with self.connect() as conn:
            with conn.transaction():
                cur = conn.cursor(name="gp_export")
                cur.itersize = 2000
                cur.execute(query)
                yield [c["name"] for c in cols]
                for row in cur:
                    yield ["" if v is None else v for v in row]

    # ------------------------------------------------------------------ پزشک داده
    INVALID_CHECK_MAX_ROWS = 300_000
    FIXES = {
        "add_pk": "افزودن کلید اصلی",
        "add_index": "ساخت نمایه مکانی",
        "set_srid": "تعیین سیستم مختصات",
        "make_valid": "اصلاح هندسه‌های نامعتبر",
        "analyze": "به‌روزرسانی آمار",
        "fix_owner": "برگرداندن مالکیت به شما",
    }

    def health(self) -> list[dict]:
        """مشکلات رایج جدول‌ها که QGIS، GeoServer یا سرعت کوئری را خراب می‌کنند."""
        issues = []
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT n.nspname, c.relname, c.reltuples::bigint,
                       EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary),
                       pg_has_role(c.relowner, 'USAGE'), pg_get_userbyid(c.relowner)
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r','p') AND NOT c.relispartition
                  AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg\\_%%'
                  AND has_table_privilege(c.oid, 'SELECT')
                ORDER BY 1, 2
            """).fetchall()
            geoms = self._geometry_columns(conn)
            web = Provisioner.browser_role_name(self.db.role_name)
            for schema, name, est, has_pk, owned, owner in rows:
                if schema in HIDDEN_SCHEMAS or (schema, name) in HIDDEN_TABLES or not owned:
                    continue
                base = {"schema": schema, "table": name}
                if owner == web:
                    issues.append({**base, "fix": "fix_owner", "level": "error",
                                   "text": "این جدول با کنسول SQL قدیمی ساخته شده و مال شما نیست؛ "
                                           "در QGIS و پایتون خطای دسترسی می‌دهد."})
                    continue
                cols = [g for g in geoms.get((schema, name), []) if not g["geography"]]
                if not has_pk:
                    issues.append({**base, "fix": "add_pk", "level": "warning",
                                   "text": "کلید اصلی ندارد؛ QGIS نمی‌تواند آن را ویرایش کند و GeoServer کند می‌شود."})
                if est < 0:
                    issues.append({**base, "fix": "analyze", "level": "info",
                                   "text": "آمار جدول به‌روز نیست؛ تعداد سطرها تقریبی و برنامه‌ریزی کوئری‌ها ضعیف است."})
                for g in cols:
                    col = g["column"]
                    gbase = {**base, "column": col}
                    indexed = conn.execute("""
                        SELECT 1 FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid
                        JOIN pg_am am ON am.oid = ic.relam
                        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                        WHERE i.indrelid = %s::regclass AND a.attname = %s AND am.amname IN ('gist','spgist','brin')
                    """, (sql.Identifier(schema, name).as_string(conn), col)).fetchone()
                    if not indexed:
                        issues.append({**gbase, "fix": "add_index", "level": "warning",
                                       "text": f"ستون {col} نمایه مکانی ندارد؛ نقشه و کوئری‌های مکانی کند می‌شوند."})
                    if not g["srid"]:
                        issues.append({**gbase, "fix": "set_srid", "level": "error",
                                       "text": f"سیستم مختصات ستون {col} مشخص نیست (SRID 0)؛ روی نقشه نمایش داده نمی‌شود."})
                    if est <= self.INVALID_CHECK_MAX_ROWS:  # بدون آمار (-1) هم با سقف زمانی بررسی می‌شود
                        try:
                            with conn.transaction():
                                conn.execute("SET LOCAL statement_timeout = '15s'")
                                bad = conn.execute(sql.SQL(
                                    "SELECT count(*) FROM {} WHERE {} IS NOT NULL AND NOT ST_IsValid({})").format(
                                    sql.Identifier(schema, name), sql.Identifier(col), sql.Identifier(col))).fetchone()[0]
                        except psycopg.Error:
                            bad = 0
                        if bad:
                            issues.append({**gbase, "fix": "make_valid", "level": "warning", "count": bad,
                                           "text": f"{bad} هندسه نامعتبر در ستون {col} (مثلاً خودبرخوردی)؛ "
                                                   "تحلیل‌هایی مثل تقاطع و مساحت خطا می‌دهند."})
        return issues

    def fix(self, kind: str, schema: str, name: str, column: str | None = None, srid: int | None = None) -> str:
        table = self.find(schema, name)
        if kind == "fix_owner":
            try:
                Provisioner.for_server(self.server).reassign_browser_objects(self.db.db_name, self.db.role_name)
            except ProvisionError as exc:
                raise ExplorerError(f"اصلاح انجام نشد: {exc}") from exc
            return "مالکیت جدول‌ها به شما برگشت."
        rel = sql.Identifier(table.schema, table.name)
        geo = {g["column"]: g for g in table.geometry if not g["geography"]}
        if kind in ("add_index", "set_srid", "make_valid") and column not in geo:
            raise ExplorerError("ستون مکانی پیدا نشد.")
        col = sql.Identifier(column) if column else None
        if kind == "add_pk":
            existing = {c["name"] for c in self.columns(table)}
            pk = next(n for n in ("gid", "gp_id", "row_id") if n not in existing)
            stmt = sql.SQL("ALTER TABLE {} ADD COLUMN {} bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY").format(
                rel, sql.Identifier(pk))
            done = f"ستون {pk} به‌عنوان کلید اصلی اضافه شد."
        elif kind == "add_index":
            stmt = sql.SQL("CREATE INDEX ON {} USING gist ({})").format(rel, col)
            done = "نمایه مکانی ساخته شد."
        elif kind == "set_srid":
            if not srid or not (1000 <= int(srid) <= 999999):
                raise ExplorerError("SRID نامعتبر است.")
            stmt = sql.SQL("SELECT UpdateGeometrySRID({}, {}, {}, {})").format(
                sql.Literal(table.schema), sql.Literal(table.name), sql.Literal(column), sql.Literal(int(srid)))
            done = f"سیستم مختصات {int(srid)} تعیین شد (مختصات تغییر نکرد، فقط برچسب SRID)."
        elif kind == "make_valid":
            gtype = (geo[column]["type"] or "").upper()
            dim = 3 if "POLYGON" in gtype else 2 if "LINE" in gtype else 1 if "POINT" in gtype else None
            expr = sql.SQL("ST_MakeValid({})").format(col)
            pre = None
            done = "هندسه‌های نامعتبر اصلاح شدند."
            if dim:
                expr = sql.SQL("ST_Multi(ST_CollectionExtract({}, {}))").format(expr, sql.Literal(dim))
                if not gtype.startswith("MULTI"):
                    # اصلاح یک چندضلعی خودبرخورد معمولاً چندبخشی می‌شود؛ ستون باید Multi باشد
                    multi = {3: "MultiPolygon", 2: "MultiLineString", 1: "MultiPoint"}[dim]
                    pre = sql.SQL("ALTER TABLE {} ALTER COLUMN {} TYPE geometry({}, {}) USING ST_Multi({})").format(
                        rel, col, sql.SQL(multi), sql.Literal(int(geo[column]["srid"] or 0)), col)
                    done += f" نوع ستون به {multi} تبدیل شد."
            stmt = sql.SQL("UPDATE {} SET {} = {} WHERE {} IS NOT NULL AND NOT ST_IsValid({})").format(
                rel, col, expr, col, col)
        elif kind == "analyze":
            stmt = sql.SQL("ANALYZE {}").format(rel)
            done = "آمار جدول به‌روز شد."
        else:
            raise ExplorerError("اصلاح ناشناخته.")
        with self.connect(read_only=False) as conn:
            try:
                conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self.db.role_name)))
                conn.execute("SET LOCAL statement_timeout = '120s'")
                if kind == "make_valid" and pre is not None:
                    conn.execute(pre)
                conn.execute(stmt)
                conn.commit()
            except psycopg.Error as exc:
                conn.rollback()
                msg = getattr(exc.diag, "message_primary", None) or str(exc)
                raise ExplorerError(f"اصلاح انجام نشد: {msg}") from exc
        return done

    def fix_all(self) -> tuple[list[str], list[str]]:
        """همه اصلاح‌های بدون نیاز به انتخاب کاربر (همه جز تعیین SRID)."""
        done, failed = [], []
        for _ in range(2):  # بعد از برگرداندن مالکیت، بقیه اصلاح‌های همان جدول هم ممکن می‌شود
            issues = [i for i in self.health() if i["fix"] != "set_srid"]
            if not issues:
                break
            again = False
            for i in issues:
                try:
                    done.append(f"{i['table']}: {self.fix(i['fix'], i['schema'], i['table'], i.get('column'))}")
                    again = again or i["fix"] == "fix_owner"
                except ExplorerError as exc:
                    failed.append(f"{i['table']}: {exc}")
            if not again:
                break
        return done, failed

    # ------------------------------------------------------------------ کنسول SQL
    def run_sql(self, query: str, allow_write: bool = False) -> dict:
        query = (query or "").strip().rstrip(";").strip()
        if not query:
            raise ExplorerError("کوئری خالی است.")
        started = time.monotonic()
        with self.connect(read_only=not allow_write) as conn:
            cur = psycopg.RawCursor(conn)
            try:
                # جدول‌هایی که از این صفحه ساخته می‌شوند باید مال نقش خود کاربر باشند، نه نقش مرورگر؛
                # وگرنه کاربر در QGIS به آن‌ها دسترسی ندارد. نقش مرورگر عضو نقش کاربر است.
                conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self.db.role_name)))
                cur.execute(query, prepare=True)
                result = {"columns": [], "rows": [], "truncated": False,
                          "rowcount": cur.rowcount, "status": cur.statusmessage or ""}
                if cur.description:
                    result["columns"] = [d.name for d in cur.description]
                    data = cur.fetchmany(SQL_MAX_ROWS + 1)
                    result["truncated"] = len(data) > SQL_MAX_ROWS
                    result["rows"] = [[_cell(v) for v in r] for r in data[:SQL_MAX_ROWS]]
                conn.commit()
            except psycopg.errors.ReadOnlySqlTransaction as exc:
                conn.rollback()
                raise ExplorerError("این دستور داده را تغییر می‌دهد. برای اجرا، گزینه «اجازه تغییر داده» را بزنید.") from exc
            except psycopg.errors.SyntaxError as exc:
                conn.rollback()
                if "multiple commands" in str(exc):
                    raise ExplorerError("در هر اجرا فقط یک دستور SQL مجاز است.") from exc
                raise ExplorerError(f"خطای نگارشی: {exc.diag.message_primary or exc}") from exc
            except psycopg.errors.QueryCanceled as exc:
                conn.rollback()
                raise ExplorerError("اجرای کوئری بیش از حد طول کشید و متوقف شد (حداکثر ۲۰ ثانیه).") from exc
            except psycopg.Error as exc:
                conn.rollback()
                msg = getattr(exc.diag, "message_primary", None) or str(exc)
                raise ExplorerError(f"خطا: {msg}") from exc
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return result
