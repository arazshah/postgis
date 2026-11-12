"""
ورود فایل به یک جدول موجود با نگاشت ستون‌ها (افزودن یا جایگزینی کل داده‌ها).

روش: فایل اول با ogr2ogr در یک جدول موقت (staging) خوانده می‌شود؛ بعد در یک تراکنش، با نقش خود کاربر،
ستون‌های نگاشت‌شده به نوع ستون مقصد تبدیل و در جدول اصلی درج می‌شود (در حالت جایگزینی، پیش از آن TRUNCATE).
چون همه‌چیز در یک تراکنش است، هر خطا (نوع نادرست، الزامی خالی، CHECK و ...) کل ورود را برمی‌گرداند و جدول دست‌نخورده می‌ماند.
نام‌ها همیشه از کاتالوگ می‌آیند و با sql.Identifier نقل‌قول می‌شوند؛ مقدار داده‌ها در SQL نمی‌آید (فقط از جدول موقت خوانده می‌شود).
"""
from __future__ import annotations

import re

import psycopg
from psycopg import sql

from databases.explorer import ExplorerError

STAGING_FID = "_gp_fid"
STAGING_GEOM = "_gp_geom"
STAGING_RE = re.compile(r"^_gp_imp_\d{1,12}$")
TEXTUAL = {"text", "varchar", "bpchar", "name", "citext"}


class IntoError(ExplorerError):
    pass


def staging_name(job_id: int) -> str:
    return f"_gp_imp_{int(job_id)}"


def norm(name: str) -> str:
    """نام ستون برای مقایسه: حروف کوچک، بدون فاصله و نشانه."""
    return re.sub(r"[^0-9a-z؀-ۿ]+", "", str(name).lower())


def target_columns(cols: list[dict]) -> list[dict]:
    """ستون‌های داده‌ای که می‌شود به آن‌ها مقدار نگاشت کرد (نه هندسه، نه محاسبه‌شده، نه IDENTITY ALWAYS)."""
    return [c for c in cols if not c["spatial"] and not c["generated"] and c["identity"] != "a"]


def is_required(c: dict) -> bool:
    return bool(c["not_null"]) and not c["default"] and not c["identity"]


def auto_map(cols: list[dict], fields: list[str]) -> dict[str, int]:
    """نگاشت خودکار نام ستون مقصد → شماره‌ی ستون فایل (بر اساس نام یکسان یا مشابه)."""
    exact = {f.lower(): i for i, f in enumerate(fields)}
    loose: dict[str, int] = {}
    for i, f in enumerate(fields):
        loose.setdefault(norm(f), i)
    out: dict[str, int] = {}
    for c in target_columns(cols):
        n = c["name"]
        i = exact.get(n.lower(), loose.get(norm(n)))
        if i is not None:
            out[n] = i
    return out


def geom_compat(src_type: str, dst_type: str) -> bool:
    """آیا نوع هندسه‌ی فایل در ستون مقصد جا می‌شود؟ (نقطه در نقطه/چندنقطه و ...)"""
    s = (src_type or "").upper().replace(" ", "")
    d = (dst_type or "").upper()
    if not s or d in ("GEOMETRY", "GEOGRAPHY", ""):
        return True
    for base in ("POINT", "LINESTRING", "POLYGON"):
        if base in s:
            return base in d
    return True  # نوع ناشناخته را PostGIS هنگام درج می‌سنجد


def _cast(col: dict, expr: sql.Composable) -> sql.Composable:
    """مقدار موقت (هر نوعی که GDAL ساخته) → نوع ستون مقصد؛ رشته‌ی خالی برای نوع غیرمتنی NULL می‌شود."""
    as_text = sql.SQL("CAST({} AS text)").format(expr)
    if col["base"] in TEXTUAL:
        return sql.SQL("CAST({} AS {})").format(as_text, sql.SQL(col["type"]))
    return sql.SQL("CAST(NULLIF(btrim({}), '') AS {})").format(as_text, sql.SQL(col["type"]))


def _geom_expr(geo: dict, dims: int | None, src: sql.Composable) -> sql.Composable:
    """هندسه‌ی فایل → SRID، نوع (چندتکه) و بُعد ستون مقصد."""
    srid = int(geo["srid"] or 0)
    g = src
    if srid:
        g = sql.SQL("CASE WHEN ST_SRID({g}) IN (0, {s}) THEN ST_SetSRID({g}, {s}) ELSE ST_Transform({g}, {s}) END").format(
            g=src, s=sql.Literal(srid))
    if str(geo.get("type") or "").upper().startswith("MULTI"):
        g = sql.SQL("ST_Multi({})").format(g)
    if dims == 2:
        g = sql.SQL("ST_Force2D({})").format(g)
    elif dims == 3:
        g = sql.SQL("ST_Force3DZ({})").format(g)
    if geo.get("geography"):
        g = sql.SQL("CAST({} AS geography)").format(g)
    return g


def merge_statements(table, cols: list[dict], mapping: dict[str, str], staging: str, *, replace: bool,
                     geo: dict | None, dims: int | None, with_geom: bool) -> list[sql.Composable]:
    """دستورهای ادغام: (اختیاری) TRUNCATE و INSERT ... SELECT از جدول موقت.

    mapping: نام ستون مقصد → نام ستون در جدول موقت.
    geo: اطلاعات ستون هندسه‌ی مقصد {column, type, srid, geography} یا None؛ with_geom: جدول موقت ستون هندسه دارد.
    """
    if not STAGING_RE.match(staging):
        raise IntoError("نام جدول موقت نامعتبر است.")
    by_name = {c["name"]: c for c in cols}
    dst_cols: list[sql.Composable] = []
    sel: list[sql.Composable] = []
    for name, src in mapping.items():
        c = by_name.get(name)
        if c is None or c["spatial"] or c["generated"] or c["identity"] == "a":
            raise IntoError(f"ستون «{name}» قابل پر شدن نیست.")
        dst_cols.append(sql.Identifier(name))
        sel.append(_cast(c, sql.SQL("s.{}").format(sql.Identifier(src))))
    if geo and with_geom:
        dst_cols.append(sql.Identifier(geo["column"]))
        sel.append(_geom_expr(geo, dims, sql.SQL("s.{}").format(sql.Identifier(STAGING_GEOM))))
    if not dst_cols:
        raise IntoError("هیچ ستونی نگاشت نشده است.")
    stmts: list[sql.Composable] = []
    rel = sql.Identifier(table.schema, table.name)
    if replace:
        stmts.append(sql.SQL("TRUNCATE TABLE {}").format(rel))
    stmts.append(sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {} AS s ORDER BY s.{}").format(
        rel, sql.SQL(", ").join(dst_cols), sql.SQL(", ").join(sel),
        sql.Identifier("public", staging), sql.Identifier(STAGING_FID)))
    return stmts


def drop_staging(ex, staging: str) -> None:
    if not STAGING_RE.match(staging):
        return
    try:
        with ex.connect(read_only=False) as conn:
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(ex.db.role_name)))
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier("public", staging)))
            conn.commit()
    except (psycopg.Error, ExplorerError):
        pass  # پاک‌سازی بهترین‌تلاش است؛ جدول موقت بعداً با نام یکتایش قابل‌شناسایی است


def run_merge(ex, table, mapping_idx: dict[str, int], staging: str, *, replace: bool) -> int:
    """ادغام جدول موقت در جدول مقصد؛ تعداد سطرهای درج‌شده را برمی‌گرداند."""
    cols = ex.columns(table)
    geo = next(iter(table.geometry), None)
    with ex.connect(read_only=False) as conn:
        try:
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(ex.db.role_name)))
            conn.execute(sql.SQL("SET LOCAL lock_timeout = '15s'"))
            conn.execute(sql.SQL("SET LOCAL statement_timeout = '3600s'"))
            scols = [r[0] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s "
                "ORDER BY ordinal_position", (staging,))]
            if not scols:
                raise IntoError("فایل خوانده نشد (جدول موقت ساخته نشد).")
            with_geom = STAGING_GEOM in scols
            fields = [c for c in scols if c not in (STAGING_FID, STAGING_GEOM)]
            mapping = {}
            for name, i in mapping_idx.items():
                if not 0 <= i < len(fields):
                    raise IntoError("نگاشت ستون‌ها با ساختار فایل نمی‌خواند؛ از نو شروع کنید.")
                mapping[name] = fields[i]
            dims = None
            if geo and not geo.get("geography"):
                row = conn.execute(
                    "SELECT coord_dimension FROM public.geometry_columns WHERE f_table_schema = %s "
                    "AND f_table_name = %s AND f_geometry_column = %s", (table.schema, table.name, geo["column"])).fetchone()
                dims = row[0] if row else None
            if dims == 4:
                dims = None
            stmts = merge_statements(table, cols, mapping, staging, replace=replace, geo=geo, dims=dims,
                                     with_geom=with_geom)
            count = 0
            for stmt in stmts:
                cur = conn.execute(stmt)
                count = cur.rowcount if cur.rowcount and cur.rowcount > 0 else count
            conn.commit()
            return count
        except IntoError:
            conn.rollback()
            raise
        except psycopg.errors.InsufficientPrivilege as exc:
            conn.rollback()
            raise IntoError("اجازه نوشتن در این جدول را ندارید.") from exc
        except psycopg.errors.LockNotAvailable as exc:
            conn.rollback()
            raise IntoError("جدول در حال استفاده است؛ چند لحظه بعد دوباره تلاش کنید.") from exc
        except psycopg.errors.FeatureNotSupported as exc:
            conn.rollback()
            raise IntoError("جدول توسط جدول دیگری ارجاع شده است و خالی کردنش ممکن نیست؛ به‌جای «جایگزینی» از «افزودن» "
                            "استفاده کنید.") from exc
        except psycopg.Error as exc:
            conn.rollback()
            msg = getattr(exc.diag, "message_primary", None) or str(exc)
            detail = getattr(exc.diag, "message_detail", None)
            raise IntoError(f"ورود برگردانده شد و جدول تغییری نکرد: {msg}" + (f" — {detail}" if detail else "")) from exc
