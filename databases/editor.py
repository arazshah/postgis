"""
ویرایش امن جدول از مرورگر پایگاه داده (افزودن، ویرایش و حذف سطر، به‌همراه هندسه).

اصول ایمنی:
- هر ذخیره یک دسته‌ی (batch) همه‌یاهیچ است: در یک تراکنش اجرا می‌شود و اگر یک تغییر خطا بدهد هیچ‌کدام اعمال نمی‌شود.
- فقط جدول‌های دارای کلید اصلی ویرایش می‌شوند تا هر سطر دقیقاً مشخص باشد.
- هر ویرایش و حذف «نسخه‌ی سطر» (md5 متن سطر) را که کاربر دیده بود می‌فرستد؛ اگر کسی در این فاصله سطر را عوض کرده باشد، تعارض اعلام می‌شود و چیزی نوشته نمی‌شود.
- نام جدول و ستون‌ها فقط بعد از پیدا شدن در کاتالوگ و با sql.Identifier به‌کار می‌روند؛ مقدارها همیشه پارامتر هستند.
- اجرا با نقش خود کاربر (SET LOCAL ROLE) است، نه ادمین سرور.
- پیش از هر تغییر، مقدار قبلی ذخیره می‌شود تا «بازگردانی آخرین ذخیره» ممکن باشد.
"""
from __future__ import annotations

import json
import re

import psycopg
from psycopg import sql

from .explorer import Explorer, ExplorerError, TableRef

MAX_CHANGES = 500
MAX_VALUE_CHARS = 100_000
KEEP_BATCHES = 30
EDIT_TTL = 15 * 60  # مهلت بی‌کاری حالت ویرایش (ثانیه)
VERSION_RE = re.compile(r"^[0-9a-f]{32}$")
GEOJSON_TYPES = {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}
EWKB_RE = re.compile(r"^[0-9a-fA-F]{10,}$")
EDITABLE_KINDS = {"r", "p"}


class EditError(ExplorerError):
    pass


# ---------------------------------------------------------------------- توان ویرایش جدول
def edit_capability(table: TableRef, cols: list[dict]) -> dict:
    """آیا جدول قابل ویرایش است؟ اگر نه، دلیل فارسی."""
    if table.kind not in EDITABLE_KINDS:
        return {"ok": False, "reason": "نما و جدول خارجی قابل ویرایش نیستند؛ فقط جدول معمولی ویرایش می‌شود."}
    if not any(c["pk"] for c in cols):
        return {"ok": False, "reason": "این جدول کلید اصلی (primary key) ندارد؛ بدون آن نمی‌شود سطرها را بی‌خطا مشخص کرد. "
                                      "با کنسول SQL یک کلید اصلی اضافه کنید."}
    return {"ok": True, "reason": ""}


def editable_columns(cols: list[dict], internal: bool = False) -> dict[str, dict]:
    """ستون‌های غیرمکانی که می‌شود مقدارشان را نوشت. ستون‌های محاسباتی هرگز؛ هویت‌ساز (always) فقط در بازگردانی."""
    out = {}
    for c in cols:
        if c["spatial"] or c["generated"]:
            continue
        if c["identity"] == "a" and not internal:
            continue
        out[c["name"]] = c
    return out


# ---------------------------------------------------------------------- پاک‌سازی ورودی
def _text(v, what: str):
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float, str)):
        s = str(v)
        if len(s) > MAX_VALUE_CHARS:
            raise EditError(f"مقدار «{what}» خیلی بلند است.")
        if "\x00" in s:
            raise EditError(f"مقدار «{what}» نویسه‌ی نامعتبر دارد.")
        return s
    raise EditError(f"مقدار «{what}» نامعتبر است.")


def _clean_geom(spec, cols: list[dict]):
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise EditError("هندسه نامعتبر است.")
    spatial = {c["name"] for c in cols if c["spatial"]}
    col = spec.get("column")
    if col not in spatial:
        raise EditError("ستون مکانی نامعتبر است.")
    if spec.get("null"):
        return {"column": col, "null": True}
    if "geojson" in spec:
        g = spec["geojson"]
        if not isinstance(g, dict) or g.get("type") not in GEOJSON_TYPES or not isinstance(g.get("coordinates"), list):
            raise EditError("هندسه‌ی GeoJSON نامعتبر است.")
        return {"column": col, "geojson": g}
    if "ewkb" in spec:
        if not isinstance(spec["ewkb"], str) or not EWKB_RE.match(spec["ewkb"]):
            raise EditError("هندسه نامعتبر است.")
        return {"column": col, "ewkb": spec["ewkb"]}
    raise EditError("هندسه نامعتبر است.")


def normalize(changes, cols: list[dict], internal: bool = False) -> list[dict]:
    """فهرست تغییرهای کاربر را اعتبارسنجی و به شکل یکنواخت درمی‌آورد؛ هرچه ناشناخته باشد رد می‌شود."""
    if not isinstance(changes, list) or not changes:
        raise EditError("هیچ تغییری برای ذخیره نیست.")
    if len(changes) > MAX_CHANGES:
        raise EditError(f"در هر ذخیره حداکثر {MAX_CHANGES} تغییر مجاز است؛ تغییرها را در چند مرحله ذخیره کنید.")
    pk_cols = [c["name"] for c in cols if c["pk"]]
    writable = editable_columns(cols, internal)
    out = []
    for raw in changes:
        if not isinstance(raw, dict) or raw.get("op") not in ("insert", "update", "delete"):
            raise EditError("نوع تغییر نامعتبر است.")
        op = raw["op"]
        item = {"op": op}
        if op in ("update", "delete"):
            pk = raw.get("pk")
            if not isinstance(pk, dict) or set(pk) != set(pk_cols) or any(v is None for v in pk.values()):
                raise EditError("کلید اصلی سطر نامعتبر است.")
            item["pk"] = {k: _text(v, k) for k, v in pk.items()}
            v = raw.get("v")
            if not isinstance(v, str) or not VERSION_RE.match(v):
                raise EditError("نسخه‌ی سطر نامعتبر است؛ صفحه را تازه کنید.")
            item["v"] = v
        if op in ("insert", "update"):
            values = raw.get("values") or {}
            if not isinstance(values, dict):
                raise EditError("مقدارها نامعتبر است.")
            clean = {}
            for k, v in values.items():
                if k not in writable:
                    raise EditError(f"ستون «{k}» قابل نوشتن نیست.")
                if op == "update" and k in pk_cols and not internal:
                    raise EditError(f"ستون کلید اصلی «{k}» را نمی‌شود ویرایش کرد.")
                clean[k] = _text(v, k)
            item["values"] = clean
            specs = raw.get("geoms") if internal and raw.get("geoms") is not None else [raw.get("geom")]
            geoms = [g for g in (_clean_geom(x, cols) for x in specs) if g is not None]
            if len({g["column"] for g in geoms}) != len(geoms):
                raise EditError("هندسه‌ی یک ستون دوبار آمده است.")
            item["geoms"] = geoms
            if op == "update" and not clean and not geoms:
                raise EditError("یکی از ویرایش‌ها هیچ تغییری ندارد.")
        out.append(item)
    return out


# ---------------------------------------------------------------------- ساخت SQL
def _geom_expr(col: dict, geo: dict, spec: dict, repair: bool):
    """عبارت SQL هندسه‌ی ورودی، تبدیل‌شده به SRID و نوع ستون."""
    srid = geo["srid"] or 0
    if "geojson" in spec:
        base = sql.SQL("ST_SetSRID(ST_GeomFromGeoJSON(CAST({} AS text)), 4326)").format(sql.Placeholder())
        params = [json.dumps(spec["geojson"])]
        if srid not in (0, 4326) and not col["base"] == "geography":
            base = sql.SQL("ST_Transform({}, {})").format(base, sql.Literal(int(srid)))
    else:
        base = sql.SQL("ST_GeomFromEWKB(decode(CAST({} AS text), 'hex'))").format(sql.Placeholder())
        params = [spec["ewkb"]]
    if repair:
        base = sql.SQL("ST_MakeValid({})").format(base)
        gtype = (geo.get("type") or "").upper()
        dim = 3 if "POLYGON" in gtype else 2 if "LINESTRING" in gtype else 1 if "POINT" in gtype else 0
        if dim:
            base = sql.SQL("ST_CollectionExtract({}, {})").format(base, sql.Literal(dim))
            if gtype.startswith("MULTI"):
                base = sql.SQL("ST_Multi({})").format(base)
    if col["base"] == "geography":
        base = sql.SQL("CAST({} AS geography)").format(base)
    return base, params


def _typed(col: dict):
    return sql.SQL("CAST(%s AS {})").format(sql.SQL(col["type"]))


def _snapshot_select(cols: list[dict]):
    """مقدار قبلی سطر برای بازگردانی: غیرمکانی به متن، مکانی به EWKB شانزده‌شانزدهی."""
    parts = []
    for c in cols:
        if c["generated"]:
            continue
        ident = sql.Identifier(c["name"])
        if c["spatial"]:
            parts.append(sql.SQL("encode(ST_AsEWKB(t.{}::geometry), 'hex')").format(ident))
        else:
            parts.append(sql.SQL("t.{}::text").format(ident))
    return sql.SQL(", ").join(parts), [c for c in cols if not c["generated"]]


def _pg_message(exc: psycopg.Error) -> str:
    d = getattr(exc, "diag", None)
    msg = getattr(d, "message_primary", None) or str(exc)
    if isinstance(exc, psycopg.errors.UniqueViolation):
        return "مقدار تکراری است؛ این مقدار قبلاً در یک ستون یکتا (یا کلید اصلی) ثبت شده. " + (d.message_detail or "")
    if isinstance(exc, psycopg.errors.NotNullViolation):
        col = getattr(d, "column_name", None)
        return f"ستون «{col}» نباید خالی باشد." if col else "یکی از ستون‌های الزامی خالی است."
    if isinstance(exc, psycopg.errors.ForeignKeyViolation):
        return "این تغییر با جدول دیگری که به آن وابسته است در تضاد است (کلید خارجی). " + (d.message_detail or "")
    if isinstance(exc, psycopg.errors.CheckViolation):
        return "مقدار شرط (CHECK) ستون را رعایت نمی‌کند."
    if isinstance(exc, psycopg.errors.InsufficientPrivilege):
        return "اجازه‌ی این تغییر را ندارید."
    if isinstance(exc, psycopg.errors.LockNotAvailable):
        return "سطر در حال استفاده است؛ چند لحظه بعد دوباره تلاش کنید."
    if isinstance(exc, (psycopg.errors.DataError, psycopg.errors.InvalidTextRepresentation)):
        return f"مقدار برای نوع ستون معتبر نیست: {msg}"
    return f"خطا: {msg}"


# ---------------------------------------------------------------------- اجرای دسته
class Editor:
    def __init__(self, ex: Explorer):
        self.ex = ex

    def apply(self, table: TableRef, changes, *, dry_run: bool = False, repair: bool = False,
              internal: bool = False) -> dict:
        """
        نتیجه: {"ok": bool, "results": [{"i", "status", "message"}], "undo": [...], "counts": {...}}
        status: ok | conflict | invalid | error | skipped
        """
        cols = self.ex.columns(table)
        cap = edit_capability(table, cols)
        if not cap["ok"]:
            raise EditError(cap["reason"])
        ops = normalize(changes, cols, internal)
        by_name = {c["name"]: c for c in cols}
        geo_by_col = {g["column"]: g for g in table.geometry}
        pk_cols = [c for c in cols if c["pk"]]
        rel = sql.Identifier(table.schema, table.name)
        results: list[dict] = []
        undo: list[dict] = []
        snap_sql, snap_cols = _snapshot_select(cols)

        with self.ex.connect(read_only=False) as conn:
            with conn.transaction():
                conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self.ex.db.role_name)))
                conn.execute(sql.SQL("SET LOCAL lock_timeout = '5s'"))
                for i, op in enumerate(ops):
                    res = {"i": i, "status": "ok", "message": ""}
                    try:
                        with conn.transaction():  # نقطه‌ی ذخیره: خطای یک تغییر بقیه را نمی‌شکند
                            inverse = self._run_op(conn, op, rel, by_name, geo_by_col, pk_cols, snap_sql, snap_cols,
                                                   repair, internal)
                            undo.append(inverse)
                    except _Conflict as exc:
                        res.update(status="conflict", message=str(exc))
                    except _Invalid as exc:
                        res.update(status="invalid", message=str(exc))
                    except psycopg.Error as exc:
                        res.update(status="error", message=_pg_message(exc))
                    results.append(res)
                ok = all(r["status"] == "ok" for r in results)
                if dry_run or not ok:
                    raise psycopg.Rollback()  # همه‌یاهیچ
        counts = {k: sum(1 for o in ops if o["op"] == k) for k in ("insert", "update", "delete")}
        return {"ok": ok, "results": results, "undo": list(reversed(undo)) if ok else [], "counts": counts,
                "dry_run": dry_run}

    # ------------------------------------------------------------------
    def _where(self, pk_cols, pk: dict):
        parts, params = [], []
        for c in pk_cols:
            parts.append(sql.SQL("t.{} = ").format(sql.Identifier(c["name"])) + _typed(c))
            params.append(pk[c["name"]])
        return sql.SQL(" AND ").join(parts), params

    def _check_geometry(self, conn, col, geo, spec, repair):
        expr, params = _geom_expr(col, geo, spec, repair)
        row = conn.execute(sql.SQL("SELECT ST_IsValid({e}::geometry), ST_IsValidReason({e}::geometry)").format(e=expr),
                           params * 2).fetchone()
        if not row[0]:
            raise _Invalid(f"هندسه نامعتبر است ({row[1]}). می‌توانید «ترمیم خودکار» را بزنید یا آن را دوباره بکشید.")
        gtype = (geo.get("type") or "").upper()
        if repair and gtype and not gtype.startswith("MULTI") and gtype != "GEOMETRY":
            parts = conn.execute(sql.SQL("SELECT ST_NumGeometries({}::geometry)").format(expr), params).fetchone()[0]
            if parts and parts > 1:
                raise _Invalid("ترمیم این شکل را به چند تکه تقسیم می‌کند ولی این ستون فقط یک تکه می‌پذیرد "
                               "(برای چندتکه‌ای باید ستون MultiPolygon/MultiLineString باشد)؛ شکل را اصلاح کنید.")

    def _run_op(self, conn, op, rel, by_name, geo_by_col, pk_cols, snap_sql, snap_cols, repair, internal):
        kind = op["op"]
        gexprs: list[tuple[str, object, list]] = []  # (ستون، عبارت یا None برای NULL، پارامترها)
        for g in op.get("geoms", []):
            if g.get("null"):
                gexprs.append((g["column"], None, []))
                continue
            gcol = by_name[g["column"]]
            geo = geo_by_col.get(g["column"], {"srid": 0, "type": ""})
            try:
                self._check_geometry(conn, gcol, geo, g, repair)
            except psycopg.Error as exc:
                raise _Invalid(f"هندسه خوانده نشد: {getattr(exc.diag, 'message_primary', None) or exc}") from exc
            expr, p = _geom_expr(gcol, geo, g, repair)
            gexprs.append((g["column"], expr, p))

        if kind == "insert":
            names, exprs, params = [], [], []
            for k, v in op["values"].items():
                names.append(sql.Identifier(k))
                exprs.append(_typed(by_name[k]))
                params.append(v)
            for col, expr, p in gexprs:
                names.append(sql.Identifier(col))
                exprs.append(expr if expr is not None else sql.SQL("NULL"))
                params += p
            pk_ret = sql.SQL(", ").join(sql.SQL("t.{}::text").format(sql.Identifier(c["name"])) for c in pk_cols)
            override = sql.SQL(" OVERRIDING SYSTEM VALUE") if internal else sql.SQL("")
            if names:
                stmt = sql.SQL("INSERT INTO {} AS t ({}){} VALUES ({}) RETURNING md5(t::text), {}").format(
                    rel, sql.SQL(", ").join(names), override, sql.SQL(", ").join(exprs), pk_ret)
            else:
                stmt = sql.SQL("INSERT INTO {} AS t DEFAULT VALUES RETURNING md5(t::text), {}").format(rel, pk_ret)
            row = conn.execute(stmt, params).fetchone()
            return {"op": "delete", "pk": {c["name"]: row[1 + n] for n, c in enumerate(pk_cols)}, "v": row[0]}

        where, wparams = self._where(pk_cols, op["pk"])
        snap = conn.execute(sql.SQL("SELECT {} FROM {} AS t WHERE {} AND md5(t::text) = %s FOR UPDATE").format(
            snap_sql, rel, where), wparams + [op["v"]]).fetchone()
        if snap is None:
            raise _Conflict("این سطر در این فاصله توسط کس دیگری تغییر کرده یا حذف شده است.")
        old = {c["name"]: snap[n] for n, c in enumerate(snap_cols)}

        if kind == "delete":
            conn.execute(sql.SQL("DELETE FROM {} AS t WHERE {}").format(rel, where), wparams)
            return {"op": "insert",
                    "values": {k: v for k, v in old.items() if not by_name[k]["spatial"]},
                    "geoms": [{"column": k, "ewkb": v} for k, v in old.items() if by_name[k]["spatial"] and v]}

        sets, params = [], []
        for k, v in op["values"].items():
            sets.append(sql.SQL("{} = ").format(sql.Identifier(k)) + _typed(by_name[k]))
            params.append(v)
        for col, expr, p in gexprs:
            sets.append(sql.SQL("{} = ").format(sql.Identifier(col)) + (expr if expr is not None else sql.SQL("NULL")))
            params += p
        row = conn.execute(sql.SQL("UPDATE {} AS t SET {} WHERE {} RETURNING md5(t::text)").format(
            rel, sql.SQL(", ").join(sets), where), params + wparams).fetchone()
        return {"op": "update", "pk": op["pk"], "v": row[0], "values": {k: old[k] for k in op["values"]},
                "geoms": [({"column": col, "ewkb": old[col]} if old.get(col) else {"column": col, "null": True})
                          for col, _, _ in gexprs]}

    # ------------------------------------------------------------------
    def row(self, table: TableRef, pk: dict) -> dict:
        """مقدار کامل (بدون کوتاه‌سازی) و نسخه‌ی یک سطر برای فرم ویرایش."""
        cols = self.ex.columns(table)
        cap = edit_capability(table, cols)
        if not cap["ok"]:
            raise EditError(cap["reason"])
        pk_cols = [c for c in cols if c["pk"]]
        if not isinstance(pk, dict) or set(pk) != {c["name"] for c in pk_cols}:
            raise EditError("کلید اصلی سطر نامعتبر است.")
        data_cols = [c for c in cols if not c["spatial"]]
        where, wparams = self._where(pk_cols, {k: _text(v, k) for k, v in pk.items()})
        select = sql.SQL(", ").join(sql.SQL("t.{}::text").format(sql.Identifier(c["name"])) for c in data_cols)
        select = (select + sql.SQL(", ")) if data_cols else select
        with self.ex.connect() as conn:
            row = conn.execute(sql.SQL("SELECT {}md5(t::text) FROM {} AS t WHERE {}").format(
                select, sql.Identifier(table.schema, table.name), where), wparams).fetchone()
        if row is None:
            raise EditError("این سطر دیگر وجود ندارد.")
        return {"values": {c["name"]: row[n] for n, c in enumerate(data_cols)}, "v": row[-1]}


class _Conflict(Exception):
    pass


class _Invalid(Exception):
    pass
