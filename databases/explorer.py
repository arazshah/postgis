"""
مرورگر ساده پایگاه داده برای کاربران (چیزی شبیه pgAdmin، خیلی ساده‌تر).

امنیت:
- هرگز با کاربر ادمین سرور وصل نمی‌شود. برای هر پایگاه داده یک نقش محدود «<user>_web» ساخته می‌شود
  که عضو نقش همان کاربر است، superuser نیست و فقط به دیتابیس خودش دسترسی دارد.
- نام schema و جدول فقط بعد از پیدا شدن در کاتالوگ استفاده می‌شود و همیشه با sql.Identifier نقل‌قول می‌شود.
- کنسول SQL با prepare=True اجرا می‌شود؛ یعنی دقیقاً یک دستور در هر اجرا (چند دستور با ; رد می‌شود).
"""
from __future__ import annotations

import json
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
SQL_MAP_BYTES = 4_000_000
GEOM_TEXT_MAX = 80


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
    def geo_kind(self) -> str:
        """نوع هندسه برای آیکون: point | line | polygon | geo (نامشخص) | '' (غیرمکانی)."""
        if not self.geometry:
            return ""
        t = (self.geometry[0].get("type") or "").upper()
        if "POINT" in t:
            return "point"
        if "LINE" in t:
            return "line"
        if "POLYGON" in t or "SURFACE" in t:
            return "polygon"
        return "geo"

    @property
    def geo_title(self) -> str:
        return " · ".join(f"{g['column']} {g['type']} {g['srid']}" for g in self.geometry)

    @property
    def srid(self):
        return self.geometry[0]["srid"] if self.geometry and self.geometry[0].get("srid") else None

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
                       pg_get_expr(d.adbin, d.adrelid), t.typname, a.attidentity, a.attgenerated
                FROM pg_attribute a
                JOIN pg_type t ON t.oid = a.atttypid
                LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped
                ORDER BY a.attnum""", (table.oid,)).fetchall()
        return [{"name": n, "type": t, "not_null": nn, "default": d or "", "pk": n in pk,
                 "spatial": base in ("geometry", "geography"), "base": base,
                 "identity": ident, "generated": bool(gen)}
                for n, t, nn, d, base, ident, gen in rows]

    def _select_list(self, cols: list[dict]):
        parts = []
        for c in cols:
            ident = sql.Identifier(c["name"])
            if c["spatial"]:
                parts.append(sql.SQL("left(ST_AsText({c}::geometry), 120)").format(c=ident))
            else:
                parts.append(sql.SQL("{}::text").format(ident))
        return sql.SQL(", ").join(parts)

    @staticmethod
    def _key_select(cols: list[dict]):
        """نسخه‌ی سطر (md5 متن سطر) و کلید اصلی؛ برای تشخیص تغییر هم‌زمان در حالت ویرایش."""
        pks = [c for c in cols if c["pk"]]
        pk_json = sql.SQL("json_build_object({})").format(sql.SQL(", ").join(
            sql.SQL("{}, t.{}::text").format(sql.Literal(c["name"]), sql.Identifier(c["name"])) for c in pks))
        return sql.SQL("md5(t::text), {}").format(pk_json)

    def rows(self, table: TableRef, page: int = 1, with_keys: bool = False) -> dict:
        cols = self.columns(table)
        page = max(page, 1)
        rel = sql.Identifier(table.schema, table.name)
        pks = [c for c in cols if c["pk"]]
        order = (sql.SQL(" ORDER BY ") + sql.SQL(", ").join(sql.Identifier(c["name"]) for c in pks)) if pks else sql.SQL("")
        keys_sql = (sql.SQL(", ") + self._key_select(cols)) if with_keys and pks else sql.SQL("")
        with self.connect() as conn:
            exact = None
            if table.rows_estimate < 200_000:
                exact = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(rel)).fetchone()[0]
            data = conn.execute(sql.SQL("SELECT {}{} FROM {} AS t{} LIMIT {} OFFSET {}").format(
                self._select_list(cols), keys_sql, rel, order, sql.Literal(PAGE_SIZE),
                sql.Literal((page - 1) * PAGE_SIZE))).fetchall()
        total = exact if exact is not None else table.rows_estimate
        keys = []
        if with_keys and pks:
            keys = [{"v": r[-2], "pk": r[-1]} for r in data]
            data = [r[:-2] for r in data]
        return {
            "columns": cols,
            "rows": [[_cell(v) for v in r] for r in data],
            "keys": keys,
            "page": page,
            "offset": (page - 1) * PAGE_SIZE,
            "pages": max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
            "total": total,
            "total_exact": exact is not None,
        }

    # ------------------------------------------------------------------ نقشه و خروجی
    def geojson(self, table: TableRef, geom_column: str | None = None, limit: int = MAP_LIMIT,
                with_keys: bool = False) -> str:
        if not table.geometry:
            raise ExplorerError("این جدول ستون مکانی ندارد.")
        names = [g["column"] for g in table.geometry]
        geom_column = geom_column if geom_column in names else names[0]
        all_cols = self.columns(table)
        cols = [c for c in all_cols if not c["spatial"]]
        g = sql.Identifier(geom_column)
        props = sql.SQL(", ").join(sql.SQL("t.{}").format(sql.Identifier(c["name"])) for c in cols)
        extra = sql.SQL("")
        if with_keys and any(c["pk"] for c in all_cols):
            extra = sql.SQL(", md5(t::text) AS __v, json_build_object({}) AS __pk").format(
                sql.SQL(", ").join(sql.SQL("{}, t.{}::text").format(sql.Literal(c["name"]), sql.Identifier(c["name"]))
                                   for c in all_cols if c["pk"]))
        inner = sql.SQL(
            "SELECT {props}{comma} CASE WHEN ST_SRID(t.{g}::geometry) IN (0, 4326) THEN t.{g}::geometry "
            "ELSE ST_Transform(t.{g}::geometry, 4326) END AS __geom{extra} "
            "FROM {rel} AS t WHERE t.{g} IS NOT NULL LIMIT {lim}"
        ).format(props=props, comma=sql.SQL(",") if cols else sql.SQL(""), g=g, extra=extra,
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

    # عنوان کوتاه و پیامد هر نوع مشکل برای گروه‌بندی صفحه‌ی سلامت داده
    FIX_INFO = {
        "fix_owner": ("مالکیت جدول با شما نیست", "در QGIS و پایتون خطای دسترسی می‌دهد."),
        "set_srid": ("سیستم مختصات (SRID) مشخص نیست", "روی نقشه نمایش داده نمی‌شود؛ خودتان باید سیستم درست را انتخاب کنید."),
        "add_pk": ("کلید اصلی ندارد", "QGIS نمی‌تواند ویرایش کند، ویرایش و حذف در REST API ممکن نیست و GeoServer کند می‌شود."),
        "add_index": ("نمایه‌ی مکانی ندارد", "نقشه و کوئری‌های مکانی کند می‌شوند."),
        "make_valid": ("هندسه‌ی نامعتبر دارد", "تحلیل‌هایی مثل تقاطع و مساحت خطا می‌دهند."),
        "analyze": ("آمار جدول به‌روز نیست", "تعداد سطرها تقریبی و برنامه‌ریزی کوئری‌ها ضعیف است."),
    }
    LEVEL_RANK = {"error": 0, "warning": 1, "info": 2}

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

    def single_pk_tables(self) -> set[tuple[str, str]]:
        """جدول‌هایی که کلید اصلی تک‌ستونی دارند (شرط ویرایش و حذف در REST API)."""
        with self.connect() as conn:
            return {(n, r) for n, r in conn.execute("""
                SELECT n.nspname, c.relname FROM pg_index i
                JOIN pg_class c ON c.oid = i.indrelid JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE i.indisprimary AND i.indnkeyatts = 1 AND c.relkind IN ('r','p')""")}

    def fix_group(self, kind: str) -> tuple[list[str], list[str]]:
        """یک نوع مشکل را روی همه‌ی جدول‌هایی که دارند اصلاح می‌کند (تعیین SRID به انتخاب کاربر نیاز دارد و شامل نیست)."""
        if kind not in self.FIXES or kind == "set_srid":
            raise ExplorerError("این نوع اصلاح گروهی ندارد.")
        done, failed = [], []
        for i in [x for x in self.health() if x["fix"] == kind]:
            try:
                done.append(f"{i['table']}: {self.fix(kind, i['schema'], i['table'], i.get('column'))}")
            except ExplorerError as exc:
                failed.append(f"{i['table']}: {exc}")
            if kind == "fix_owner":
                break  # یک‌بار مالکیت همه‌ی جدول‌ها را برمی‌گرداند
        return done, failed

    # ------------------------------------------------------------------ حذف جدول
    def drop_table(self, table: TableRef) -> None:
        """جدول (یا نما) را با نقش خود کاربر حذف می‌کند؛ بدون CASCADE تا چیز دیگری بی‌خبر پاک نشود."""
        kinds = {"r": "TABLE", "p": "TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW", "f": "FOREIGN TABLE"}
        if table.kind not in kinds:
            raise ExplorerError("این شیء قابل حذف نیست.")
        stmt = sql.SQL("DROP {} {}").format(sql.SQL(kinds[table.kind]), sql.Identifier(table.schema, table.name))
        with self.connect(read_only=False) as conn:
            try:
                conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self.db.role_name)))
                conn.execute(sql.SQL("SET LOCAL lock_timeout = '5s'"))
                conn.execute(stmt)
                conn.commit()
            except psycopg.errors.DependentObjectsStillExist as exc:
                conn.rollback()
                raise ExplorerError("نما یا جدول دیگری به این جدول وابسته است؛ اول آن‌ها را حذف کنید.") from exc
            except psycopg.errors.InsufficientPrivilege as exc:
                conn.rollback()
                raise ExplorerError("اجازه حذف این جدول را ندارید.") from exc
            except psycopg.errors.LockNotAvailable as exc:
                conn.rollback()
                raise ExplorerError("جدول در حال استفاده است؛ چند لحظه بعد دوباره تلاش کنید.") from exc
            except psycopg.Error as exc:
                conn.rollback()
                raise ExplorerError(f"خطا: {getattr(exc.diag, 'message_primary', None) or exc}") from exc

    def indexes(self, table: TableRef) -> list[dict]:
        """ایندکس‌های جدول: نام، ستون‌ها، روش، یکتا، کلید اصلی، پشتوانه‌ی قید و حجم."""
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT i.relname, ix.indisunique, ix.indisprimary, am.amname, pg_get_indexdef(ix.indexrelid),
                       pg_relation_size(ix.indexrelid),
                       EXISTS(SELECT 1 FROM pg_constraint c WHERE c.conindid = ix.indexrelid),
                       ARRAY(SELECT a.attname FROM unnest(ix.indkey) WITH ORDINALITY k(attnum, ord)
                             JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = k.attnum ORDER BY k.ord)
                FROM pg_index ix JOIN pg_class i ON i.oid = ix.indexrelid JOIN pg_am am ON am.oid = i.relam
                WHERE ix.indrelid = %s ORDER BY i.relname""", (table.oid,)).fetchall()
        return [{"name": n, "unique": u, "primary": pk, "method": m, "definition": d, "size": sz, "constraint": con,
                 "columns": list(cols)} for n, u, pk, m, d, sz, con, cols in rows]

    def alter_table(self, plan) -> None:
        """دستورهای تغییر ساختار را با نقش خود کاربر و در یک تراکنش اجرا می‌کند (همه‌یاهیچ)."""
        with self.connect(read_only=False) as conn:
            try:
                conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self.db.role_name)))
                conn.execute(sql.SQL("SET LOCAL lock_timeout = '10s'"))
                conn.execute(sql.SQL("SET LOCAL statement_timeout = '120s'"))
                for stmt in plan.statements:
                    conn.execute(stmt)
                conn.commit()
            except psycopg.Error as exc:
                conn.rollback()
                raise ExplorerError(_alter_message(exc)) from exc

    def writable_schemas(self) -> list[str]:
        """schemaهایی که نقش خود کاربر در آن‌ها اجازه‌ی ساخت جدول دارد (public همیشه اول)."""
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT nspname FROM pg_namespace
                WHERE nspname NOT LIKE 'pg\\_%%' AND nspname <> ALL(%s)
                  AND has_schema_privilege(%s, oid, 'CREATE')
                ORDER BY nspname <> 'public', nspname""", (sorted(HIDDEN_SCHEMAS), self.db.role_name)).fetchall()
        return [r[0] for r in rows]

    def search_srid(self, query: str, limit: int = 20) -> list[dict]:
        """جستجوی سامانه‌ی مختصات در spatial_ref_sys (با کد یا بخشی از نام)."""
        q = (query or "").strip()[:60]
        if not q:
            return []
        with self.connect() as conn:
            if q.isdigit():
                cond, args = sql.SQL("srid = %s"), (int(q),)
            else:
                cond, args = sql.SQL("srtext ILIKE %s"), ("%" + q.replace("%", "").replace("_", r"\_") + "%",)
            rows = conn.execute(sql.SQL(
                "SELECT srid, auth_name, split_part(srtext, '\"', 2) FROM spatial_ref_sys WHERE {} "
                "ORDER BY srid LIMIT %s").format(cond), (*args, limit)).fetchall()
        return [{"srid": r[0], "auth": r[1], "name": r[2]} for r in rows]

    def create_table(self, plan) -> None:
        """جدول را با نقش خود کاربر و در یک تراکنش می‌سازد؛ یا همه‌چیز ساخته می‌شود یا هیچ."""
        spec = plan.spec
        with self.connect(read_only=False) as conn:
            try:
                conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self.db.role_name)))
                conn.execute(sql.SQL("SET LOCAL lock_timeout = '5s'"))
                conn.execute(sql.SQL("SET LOCAL statement_timeout = '30s'"))
                if not conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (spec["schema"],)).fetchone():
                    raise ExplorerError("این schema وجود ندارد.")
                g = spec["geometry"]
                if g and not conn.execute("SELECT 1 FROM spatial_ref_sys WHERE srid = %s", (g["srid"],)).fetchone():
                    raise ExplorerError(f"سامانه‌ی مختصات با کد {g['srid']} پیدا نشد.")
                for stmt in plan.statements:
                    conn.execute(stmt)
                conn.commit()
            except psycopg.errors.DuplicateTable as exc:
                conn.rollback()
                raise ExplorerError("جدولی با این نام از قبل وجود دارد؛ نام دیگری انتخاب کنید.") from exc
            except psycopg.errors.InsufficientPrivilege as exc:
                conn.rollback()
                raise ExplorerError("اجازه ساخت جدول در این schema را ندارید.") from exc
            except psycopg.errors.UndefinedObject as exc:
                conn.rollback()
                raise ExplorerError("امکانات مورد نیاز (مثل PostGIS) روی این پایگاه داده فعال نیست.") from exc
            except psycopg.errors.QueryCanceled as exc:
                conn.rollback()
                raise ExplorerError("ساخت جدول بیش از حد طول کشید؛ دوباره تلاش کنید.") from exc
            except psycopg.errors.LockNotAvailable as exc:
                conn.rollback()
                raise ExplorerError("پایگاه داده در حال استفاده است؛ چند لحظه بعد دوباره تلاش کنید.") from exc
            except ExplorerError:
                conn.rollback()
                raise
            except psycopg.Error as exc:
                conn.rollback()
                raise ExplorerError(f"خطا: {getattr(exc.diag, 'message_primary', None) or exc}") from exc

    # ------------------------------------------------------------------ کنسول SQL
    @staticmethod
    def _geo_columns(conn, description) -> list[int]:
        oids = {r[0] for r in conn.execute(
            "SELECT oid FROM pg_type WHERE typname IN ('geometry', 'geography')").fetchall()}
        return [i for i, d in enumerate(description) if d.type_code in oids]

    @staticmethod
    def _geo_summaries(conn, geo_idx: list[int], data: list, cells: list) -> None:
        """خانه‌های هندسه در جدول نتیجه به‌جای EWKB هگز، متن کوتاه WKT می‌شوند (مثل POINT(51.1 35.2))."""
        for idx in geo_idx:
            try:
                with conn.transaction():
                    rows = conn.execute(
                        # text[] و نه geometry[]: جداکننده آرایه geometry در PostGIS «:» است، نه «,»
                        "SELECT CASE WHEN length(t) > %s THEN left(t, %s) || '…' ELSE t END "
                        "FROM (SELECT n, ST_AsText(h::geometry, 6) AS t FROM unnest(%s::text[]) WITH ORDINALITY u(h, n)) s "
                        "ORDER BY n", (GEOM_TEXT_MAX, GEOM_TEXT_MAX,
                                       [None if r[idx] is None else str(r[idx]) for r in data])).fetchall()
            except psycopg.Error:
                continue  # همان متن خام می‌ماند
            for row, (text,) in zip(cells, rows, strict=True):
                row[idx] = text or ""

    @staticmethod
    def _result_map(conn, description, data: list, cells: list, geo_idx: list[int]) -> dict:
        """اگر نتیجه ستون هندسه دارد، GeoJSON (WGS84) همان ردیف‌ها برای نقشه زیر نتیجه.

        مقدار خام هندسه (EWKB هگز) دوباره به PostGIS داده می‌شود تا GeoJSON شود؛ کوئری کاربر دوباره اجرا نمی‌شود.
        هر خطایی (نوع ناشناخته، SRID بی‌تبدیل) فقط نقشه را حذف می‌کند، نه نتیجه را."""
        if not data or not geo_idx:
            return {}
        idx = geo_idx[0]
        try:
            with conn.transaction():
                shapes = conn.execute(
                    "SELECT ST_AsGeoJSON(CASE WHEN ST_SRID(g) IN (0, 4326) THEN g ELSE ST_Transform(g, 4326) END, 6) "
                    "FROM unnest(%s::text[]) WITH ORDINALITY u(h, n), LATERAL (SELECT h::geometry AS g) x ORDER BY n",
                    ([None if r[idx] is None else str(r[idx]) for r in data],)).fetchall()
        except (psycopg.Error, ValueError):
            return {"map_note": "هندسه نتیجه برای نمایش روی نقشه قابل تبدیل نبود."}
        names = [d.name for d in description]
        features, size = [], 0
        for (shape,), row in zip(shapes, cells, strict=True):
            if not shape:
                continue
            size += len(shape)
            if size > SQL_MAP_BYTES:
                return {"map_note": "هندسه‌های نتیجه برای نمایش روی نقشه بیش از حد بزرگ‌اند؛ کمترشان کنید یا ST_Simplify بزنید."}
            props = {n: v for i, (n, v) in enumerate(zip(names, row, strict=True)) if i not in geo_idx}
            features.append({"type": "Feature", "geometry": json.loads(shape), "properties": props})
        if not features:
            return {}
        return {"geojson": {"type": "FeatureCollection", "features": features}, "geom_column": names[idx]}

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
                    data = data[:SQL_MAX_ROWS]
                    result["rows"] = [[_cell(v) for v in r] for r in data]
                    if data:
                        try:
                            with conn.transaction():
                                geo_idx = self._geo_columns(conn, cur.description)
                        except psycopg.Error:
                            geo_idx = []
                        result.update(self._result_map(conn, cur.description, data, result["rows"], geo_idx))
                        self._geo_summaries(conn, geo_idx, data, result["rows"])
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


def _alter_message(exc: psycopg.Error) -> str:
    """پیام فارسی و کوتاه برای خطاهای رایج تغییر ساختار؛ متن PostgreSQL در پایان می‌آید."""
    E = psycopg.errors
    raw = getattr(exc.diag, "message_primary", None) or str(exc)
    for cls, msg in (
        (E.DuplicateColumn, "ستونی با این نام از قبل هست."),
        (E.DuplicateTable, "جدول یا ایندکسی با این نام از قبل هست."),
        (E.DuplicateObject, "شیئی با این نام از قبل هست."),
        (E.NotNullViolation, "برخی سطرها در این ستون خالی‌اند؛ اول آن‌ها را پر کنید (یا مقدار پیش‌فرض بدهید)."),
        (E.UniqueViolation, "مقدار تکراری در داده‌ها هست؛ ایندکس یکتا ساخته نشد."),
        (E.DependentObjectsStillExist, "نما یا شیء دیگری به این ستون یا جدول وابسته است؛ اول آن را حذف کنید."),
        (E.InsufficientPrivilege, "اجازه‌ی تغییر این جدول را ندارید."),
        (E.LockNotAvailable, "جدول در حال استفاده است؛ چند لحظه بعد دوباره تلاش کنید."),
        (E.QueryCanceled, "تغییر بیش از حد طول کشید و لغو شد؛ برای جدول‌های بزرگ از کنسول SQL در ساعت کم‌کار استفاده کنید."),
        (E.InvalidTextRepresentation, "برخی مقدارها به نوع تازه تبدیل نمی‌شوند"),
        (E.DatatypeMismatch, "این تبدیل نوع ممکن نیست"),
        (E.CannotCoerce, "این تبدیل نوع ممکن نیست"),
        (E.NumericValueOutOfRange, "برخی مقدارها در بازه‌ی نوع تازه نمی‌گنجند"),
        (E.StringDataRightTruncation, "برخی متن‌ها از سقف طول تازه بلندترند"),
        (E.InvalidDatetimeFormat, "برخی مقدارها به تاریخ یا زمان تبدیل نمی‌شوند"),
        (E.DatetimeFieldOverflow, "برخی مقدارها به تاریخ یا زمان تبدیل نمی‌شوند"),
        (E.CheckViolation, "برخی سطرها قید جدول را رعایت نمی‌کنند"),
    ):
        if isinstance(exc, cls):
            return f"{msg}" + ("" if msg.endswith(".") else f" ({raw})")
    return f"خطا: {raw}"
