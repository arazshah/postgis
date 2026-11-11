"""
مرورگر ساده پایگاه داده برای کاربران (چیزی شبیه pgAdmin، خیلی ساده‌تر).

امنیت:
- هرگز با کاربر ادمین سرور وصل نمی‌شود (اتصال از kernel.tenantdb با اتصال‌دهنده‌ی databases/gateway.py). برای هر پایگاه داده یک نقش محدود «<user>_web» ساخته می‌شود
  که عضو نقش همان کاربر است، superuser نیست و فقط به دیتابیس خودش دسترسی دارد.
- نام schema و جدول فقط بعد از پیدا شدن در کاتالوگ استفاده می‌شود و همیشه با sql.Identifier نقل‌قول می‌شود.
- کنسول SQL با prepare=True اجرا می‌شود؛ یعنی دقیقاً یک دستور در هر اجرا (چند دستور با ; رد می‌شود).
"""
from __future__ import annotations

import json
import time

import psycopg
from psycopg import sql

from kernel.tenantdb import HIDDEN_SCHEMAS, HIDDEN_TABLES, MAP_LIMIT, Catalog, TableRef, TenantError  # noqa: F401

from .provisioner import Provisioner, ProvisionError

CELL_MAX = 200
PAGE_SIZE = 50
EXPORT_LIMIT = 100_000
SQL_MAX_ROWS = 500
SQL_MAP_BYTES = 4_000_000
GEOM_TEXT_MAX = 80


ExplorerError = TenantError  # همان خطای دروازه؛ نام قدیمی برای سازگاری


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<باینری {len(bytes(value))} بایت>"
    text = str(value)
    return text if len(text) <= CELL_MAX else text[:CELL_MAX] + "…"


class Explorer(Catalog):
    """کاتالوگ کامل برای مرورگر داده: افزون بر اتصال و فهرست جدول‌ها (kernel.tenantdb.Catalog)، صفحه‌ی داده،
    خروجی، پزشک داده، حذف و کنسول SQL."""

    def __init__(self, db):
        super().__init__(db)
        self.server = db.server

    def _ensure_role(self, force: bool = False) -> str:
        """رمز نقش محدود مرورگر (برای ابزارهایی مثل GDAL که خودشان وصل می‌شوند)."""
        from .gateway import ensure_role

        return ensure_role(self.db, force)

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
