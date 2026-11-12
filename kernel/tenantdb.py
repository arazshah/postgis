"""دروازه‌ی پایگاه داده‌ی مشتری: تنها راه اتصال پلاگین‌ها به داده‌ی مشتری و خواندن کاتالوگ آن.

امنیت:
- اتصال هرگز با کاربر ادمین سرور نیست؛ «اتصال‌دهنده»ی ثبت‌شده (پلاگین میزبانی PostGIS) مشخصات یک نقش محدود را می‌دهد
  که فقط به پایگاه همان مشتری دسترسی دارد. نوشتن با نقش مالک (`as_owner=True` ← SET ROLE) انجام می‌شود تا مالکیت درست بماند.
- نام schema و جدول فقط بعد از پیدا شدن در کاتالوگ استفاده می‌شود و همیشه با sql.Identifier نقل‌قول می‌شود.

هسته نمی‌داند پایگاه کجا و چگونه ساخته شده: `set_connector` اتصال‌دهنده و `set_catalog` کلاس کاتالوگ را ثبت می‌کند.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import import_module

import psycopg
from psycopg import sql

HIDDEN_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast", "topology", "tiger", "tiger_data"}
HIDDEN_TABLES = {("public", t) for t in ("spatial_ref_sys", "geometry_columns", "geography_columns",
                                        "raster_columns", "raster_overviews")}
MAP_LIMIT = 2000
TABLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")  # قاعده‌ی نام جدول در پایگاه مشتری


class TenantError(Exception):
    """خطای اتصال یا کاتالوگ پایگاه مشتری با پیام فارسی قابل نمایش."""


WRITABLE_KINDS = frozenset({"r", "p"})  # relkindهایی که می‌شود در آن‌ها ردیف نوشت: جدول عادی و پارتیشن‌بندی‌شده


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


class Connector:
    """قرارداد اتصال‌دهنده: پلاگین میزبانی آن را پیاده و با `set_connector` ثبت می‌کند."""

    def params(self, ws, force: bool = False) -> dict:
        """آرگومان‌های psycopg.connect برای نقش محدود این فضای کار؛ force = نقش را از نو بساز."""
        raise NotImplementedError

    def owner_role(self, ws) -> str:
        """نام نقش مالک داده‌ها (برای SET ROLE هنگام نوشتن)."""
        raise NotImplementedError


_connector: Connector | None = None
_catalog_path = ""


def set_connector(connector: Connector) -> None:
    global _connector
    _connector = connector


def set_catalog(path: str) -> None:
    """مسیر کلاس کاتالوگ کامل (زیرکلاس Catalog) که `catalog()` می‌سازد."""
    global _catalog_path
    _catalog_path = path


def connector() -> Connector:
    if _connector is None:
        raise TenantError("اتصال‌دهنده‌ی پایگاه داده ثبت نشده است.")
    return _connector


def catalog(ws) -> Catalog:
    """کاتالوگ یک فضای کار (کلاس ثبت‌شده‌ی پلاگین میزبانی، وگرنه کاتالوگ پایه)."""
    if not _catalog_path:
        return Catalog(ws)
    module, _, attr = _catalog_path.rpartition(".")
    return getattr(import_module(module), attr)(ws)


@contextmanager
def connect(ws, *, write: bool = False, as_owner: bool = False):
    """اتصال به پایگاه مشتری. write=False فقط‌خواندنی است؛ as_owner نوشتن را با نقش مالک انجام می‌دهد."""
    with catalog(ws).connect(read_only=not write, as_owner=as_owner) as conn:
        yield conn


class Catalog:
    """اتصال و خواندن کاتالوگ (جدول‌ها، ستون‌ها، GeoJSON) یک فضای کار."""

    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------ اتصال
    @contextmanager
    def connect(self, read_only: bool = True, as_owner: bool = False):
        link = connector()
        try:
            conn = psycopg.connect(**link.params(self.db))
        except psycopg.OperationalError as exc:
            if "password authentication failed" in str(exc) or "does not exist" in str(exc):
                try:
                    conn = psycopg.connect(**link.params(self.db, force=True))
                except psycopg.Error as exc2:
                    raise TenantError(f"اتصال به پایگاه داده ممکن نشد: {exc2}") from exc2
            else:
                raise TenantError(f"اتصال به پایگاه داده ممکن نشد: {exc}") from exc
        conn.read_only = read_only
        try:
            if as_owner:
                conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(link.owner_role(self.db))))
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
        raise TenantError("جدول پیدا نشد یا به آن دسترسی ندارید.")

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

    # ------------------------------------------------------------------ نقشه و خروجی
    def geojson(self, table: TableRef, geom_column: str | None = None, limit: int = MAP_LIMIT,
                with_keys: bool = False) -> str:
        if not table.geometry:
            raise TenantError("این جدول ستون مکانی ندارد.")
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

    def single_pk_tables(self) -> set[tuple[str, str]]:
        """جدول‌هایی که کلید اصلی تک‌ستونی دارند (شرط ویرایش و حذف در REST API)."""
        with self.connect() as conn:
            return {(n, r) for n, r in conn.execute("""
                SELECT n.nspname, c.relname FROM pg_index i
                JOIN pg_class c ON c.oid = i.indrelid JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE i.indisprimary AND i.indnkeyatts = 1 AND c.relkind IN ('r','p')""")}
