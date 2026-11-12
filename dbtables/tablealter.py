"""
تغییر ساختار جدول موجود: ستون، ایندکس، نام و هندسه (SRID و نوع).

امنیت مثل سازنده‌ی جدول: هیچ SQL خامی پذیرفته نمی‌شود؛ نوع‌ها از فهرست سفید، نام‌ها از کاتالوگ یا الگوی سخت‌گیر،
مقدارها با sql.Literal. عملیات پرخطر (حذف ستون، تغییر نوع، تبدیل مختصات، تغییر نام جدول) تأیید تایپ‌شده می‌خواهند.
"""
from __future__ import annotations

from dataclasses import dataclass

from psycopg import sql

from . import tablebuilder as tb
from .tablebuilder import BuildError

# نوع پایگاه داده → کلید سازنده (برای تغییر مقدار پیش‌فرض)
BASE_TO_KEY = {"text": "text", "varchar": "varchar", "int2": "smallint", "int4": "integer", "int8": "bigint",
               "float8": "double", "numeric": "numeric", "bool": "boolean", "date": "date", "timestamptz": "timestamptz",
               "time": "time", "uuid": "uuid"}
# نوع‌هایی که از رابط برای «تغییر نوع» پیشنهاد می‌شوند (فهرست انتخابی قیدش جداست و این‌جا نیست)
CHANGEABLE = [k for k in tb.TYPES if k != "choice"]
DANGEROUS = {"drop_column", "change_type", "rename_table", "geometry"}
OPS = ("add_column", "rename_column", "rename_table", "drop_column", "change_type", "set_not_null", "set_default",
       "add_index", "drop_index", "geometry")


@dataclass
class Plan:
    op: str
    statements: list
    summary: str
    danger: str = ""  # اگر پر باشد، کاربر باید این متن را (نام ستون یا جدول) برای تأیید بنویسد
    renamed_table: str = ""
    touches_columns: bool = False  # تاریخچه‌ی بازگردانی ویرایش را بی‌اعتبار می‌کند

    def script(self) -> str:
        return ";\n".join(s.as_string(None) for s in self.statements) + ";"


def _find(cols: list[dict], name, what="ستون") -> dict:
    c = next((x for x in cols if x["name"] == name), None)
    if c is None:
        raise BuildError(f"{what} «{name}» در جدول نیست.")
    return c


def _rel(table) -> sql.Identifier:
    return sql.Identifier(table.schema, table.name)


def _alter(table, *parts) -> sql.Composable:
    return sql.SQL("ALTER TABLE {} {}").format(_rel(table), sql.SQL(" ").join(parts))


def _index_name(table, columns: list[str], taken: set[str]) -> str:
    base = f"{table.name}_{'_'.join(columns)}"[:55]
    name, n = f"{base}_idx", 1
    while name in taken:
        n += 1
        name = f"{base}_{n}_idx"
    return name


def build(table, cols: list[dict], indexes: list[dict], op: str, p) -> Plan:
    """دستورهای یک عملیات ساختاری را از پارامترها می‌سازد؛ پارامتر ناشناخته یا نامعتبر BuildError می‌دهد."""
    if op not in OPS:
        raise BuildError("عملیات نامعتبر است.")
    if not isinstance(p, dict):
        raise BuildError("پارامترها نامعتبر است.")
    names = {c["name"] for c in cols}
    taken_idx = {i["name"] for i in indexes}

    if op == "add_column":
        raw = {**p, "name": p.get("name")}
        col = tb._column(raw, set(names))  # noqa: SLF001 - اعتبارسنجی مشترک با سازنده
        if len(cols) >= tb.MAX_COLUMNS:
            raise BuildError(f"حداکثر {tb.MAX_COLUMNS} ستون در هر جدول مجاز است.")
        stmts = [_alter(table, sql.SQL("ADD COLUMN"), tb.column_sql(col))]
        if p.get("index") and col["type"] != "jsonb" and not col["unique"]:
            iname = _index_name(table, [col["name"]], taken_idx)
            stmts.append(sql.SQL("CREATE INDEX {} ON {} ({})").format(
                sql.Identifier(iname), _rel(table), sql.Identifier(col["name"])))
        note = " (اجباری بدون مقدار پیش‌فرض فقط روی جدول خالی ممکن است)" if col["not_null"] and "default" not in col else ""
        return Plan(op, stmts, f"افزودن ستون «{col['name']}»{note}", touches_columns=True)

    if op == "rename_column":
        c = _find(cols, p.get("column"))
        new = tb.check_name(p.get("new_name"), "نام تازه‌ی ستون")
        if new in names:
            raise BuildError(f"ستونی به نام «{new}» از قبل هست.")
        return Plan(op, [_alter(table, sql.SQL("RENAME COLUMN {} TO {}").format(
            sql.Identifier(c["name"]), sql.Identifier(new)))], f"تغییر نام «{c['name']}» به «{new}»",
            touches_columns=True)

    if op == "rename_table":
        new = tb.check_name(p.get("new_name"), "نام تازه‌ی جدول")
        if new == table.name:
            raise BuildError("نام تازه با نام فعلی یکی است.")
        return Plan(op, [sql.SQL("ALTER TABLE {} RENAME TO {}").format(_rel(table), sql.Identifier(new))],
                    f"تغییر نام جدول به «{new}»", danger=table.name, renamed_table=new, touches_columns=True)

    if op == "drop_column":
        c = _find(cols, p.get("column"))
        if c["pk"]:
            raise BuildError("ستون کلید اصلی را نمی‌شود حذف کرد؛ ویرایش ردیف‌ها به آن نیاز دارد.")
        return Plan(op, [_alter(table, sql.SQL("DROP COLUMN {}").format(sql.Identifier(c["name"])))],
                    f"حذف ستون «{c['name']}» و همه‌ی داده‌هایش", danger=c["name"], touches_columns=True)

    if op == "set_not_null":
        c = _find(cols, p.get("column"))
        on = bool(p.get("value"))
        if c["pk"] and not on:
            raise BuildError("ستون کلید اصلی همیشه اجباری است.")
        return Plan(op, [_alter(table, sql.SQL("ALTER COLUMN {} {} NOT NULL").format(
            sql.Identifier(c["name"]), sql.SQL("SET" if on else "DROP")))],
            f"{'اجباری' if on else 'اختیاری'} کردن «{c['name']}»")

    if op == "set_default":
        c = _find(cols, p.get("column"))
        if c["spatial"] or c["generated"] or c["identity"]:
            raise BuildError("برای این ستون مقدار پیش‌فرض تعریف نمی‌شود.")
        raw = p.get("value")
        if raw in (None, ""):
            return Plan(op, [_alter(table, sql.SQL("ALTER COLUMN {} DROP DEFAULT").format(sql.Identifier(c["name"])))],
                        f"برداشتن مقدار پیش‌فرض «{c['name']}»")
        kind = BASE_TO_KEY.get(c["base"])
        if kind is None:
            raise BuildError("تغییر مقدار پیش‌فرض این نوع ستون از رابط پشتیبانی نمی‌شود؛ از کنسول SQL استفاده کنید.")
        tb._default(kind, raw, c["name"])  # noqa: SLF001 - فقط اعتبارسنجی
        col = {"name": c["name"], "type": kind, "default": str(raw).strip(), "length": 255, "precision": 38, "scale": 0}
        expr = _default_expr(col)
        return Plan(op, [_alter(table, sql.SQL("ALTER COLUMN {} SET DEFAULT {}").format(sql.Identifier(c["name"]), expr))],
                    f"مقدار پیش‌فرض «{c['name']}»")

    if op == "change_type":
        c = _find(cols, p.get("column"))
        if c["spatial"]:
            raise BuildError("نوع ستون مکانی را از بخش «هندسه» عوض کنید.")
        if c["pk"] and c["identity"]:
            raise BuildError("نوع ستون شماره‌ی خودکار کلید اصلی را نمی‌شود عوض کرد.")
        if c["generated"]:
            raise BuildError("نوع ستون محاسباتی را نمی‌شود عوض کرد.")
        kind = p.get("type")
        if kind not in CHANGEABLE:
            raise BuildError("نوع تازه نامعتبر است.")
        new = {"name": c["name"], "type": kind}
        param = tb.TYPES[kind].get("param")
        if param == "length":
            new["length"] = tb._int(p.get("length", 255), 1, 10485760, "طول ستون")  # noqa: SLF001
        elif param == "precision":
            new["precision"] = tb._int(p.get("precision", 12), 1, 38, "دقت ستون")  # noqa: SLF001
            new["scale"] = tb._int(p.get("scale", 2), 0, new["precision"], "تعداد رقم اعشار")  # noqa: SLF001
        stmts = []
        if c["default"]:
            stmts.append(_alter(table, sql.SQL("ALTER COLUMN {} DROP DEFAULT").format(sql.Identifier(c["name"]))))
        stmts.append(_alter(table, sql.SQL("ALTER COLUMN {n} TYPE {t} USING {n}::text::{t}").format(
            n=sql.Identifier(c["name"]), t=tb._type_sql(new))))  # noqa: SLF001
        return Plan(op, stmts, f"تغییر نوع «{c['name']}» از {c['type']} به {tb.TYPES[kind]['label']}"
                    + (" (مقدار پیش‌فرض برداشته می‌شود)" if c["default"] else ""), danger=c["name"],
                    touches_columns=True)

    if op == "add_index":
        cs = p.get("columns")
        if not isinstance(cs, list) or not cs or len(cs) > 8 or len(set(cs)) != len(cs):
            raise BuildError("یک تا هشت ستون برای ایندکس انتخاب کنید.")
        picked = [_find(cols, x) for x in cs]
        spatial = [c for c in picked if c["spatial"]]
        if spatial and len(picked) > 1:
            raise BuildError("ایندکس مکانی فقط روی یک ستون هندسه ساخته می‌شود.")
        if any(c["base"] in ("jsonb", "json") for c in picked):
            raise BuildError("روی ستون JSON ایندکس معمولی ساخته نمی‌شود.")
        unique = bool(p.get("unique"))
        if spatial and unique:
            raise BuildError("ایندکس مکانی یکتا نمی‌شود.")
        names_ = [c["name"] for c in picked]
        iname = _index_name(table, names_, taken_idx)
        method = sql.SQL(" USING gist") if spatial else sql.SQL("")
        return Plan(op, [sql.SQL("CREATE {}INDEX {} ON {}{} ({})").format(
            sql.SQL("UNIQUE " if unique else ""), sql.Identifier(iname), _rel(table), method,
            sql.SQL(", ").join(sql.Identifier(n) for n in names_))],
            f"ساخت ایندکس {'مکانی ' if spatial else ''}روی {'، '.join(names_)}")

    if op == "drop_index":
        idx = next((i for i in indexes if i["name"] == p.get("name")), None)
        if idx is None:
            raise BuildError("ایندکس پیدا نشد.")
        if idx["primary"] or idx["constraint"]:
            raise BuildError("این ایندکس پشتوانه‌ی کلید اصلی یا یک قید یکتایی است و جدا حذف نمی‌شود.")
        return Plan(op, [sql.SQL("DROP INDEX {}").format(sql.Identifier(table.schema, idx["name"]))],
                    f"حذف ایندکس «{idx['name']}»")

    # geometry: نوع، بُعد و SRID ستون هندسه
    c = _find(cols, p.get("column"))
    if not c["spatial"] or c["base"] != "geometry":
        raise BuildError("فقط ستون geometry پشتیبانی می‌شود.")
    g = tb._geometry({"type": p.get("type"), "dim": p.get("dim") or "XY", "srid": p.get("srid"),  # noqa: SLF001
                      "name": c["name"]})
    mode = p.get("mode")
    if mode not in ("transform", "label"):
        raise BuildError("روش تغییر SRID را انتخاب کنید.")
    expr: sql.Composable = sql.Identifier(c["name"])
    if mode == "transform":
        expr = sql.SQL("ST_Transform({}, {})").format(expr, sql.Literal(g["srid"]))
    else:
        expr = sql.SQL("ST_SetSRID({}, {})").format(expr, sql.Literal(g["srid"]))
    if g["type"].startswith("Multi"):
        expr = sql.SQL("ST_Multi({})").format(expr)
    expr = {"XY": sql.SQL("ST_Force2D({})"), "XYZ": sql.SQL("ST_Force3DZ({})"), "XYM": sql.SQL("ST_Force3DM({})")}[
        g["dim"]].format(expr)
    typ = tb._geom_type_sql({**g, "geography": False})  # noqa: SLF001
    return Plan(op, [_alter(table, sql.SQL("ALTER COLUMN {n} TYPE {t} USING {e}").format(
        n=sql.Identifier(c["name"]), t=typ, e=expr))],
        f"تغییر «{c['name']}» به {g['type']}{tb.DIMENSIONS[g['dim']]} با SRID {g['srid']} "
        f"({'تبدیل مختصات' if mode == 'transform' else 'فقط تغییر برچسب SRID'})", danger=c["name"],
        touches_columns=True)


def _default_expr(col: dict) -> sql.Composable:
    """عبارت مقدار پیش‌فرض بدون گرد کردن (نوع numeric بدون دقت)."""
    raw = col["default"]
    kind = col["type"]
    if raw == "@now":
        return sql.SQL({"date": "CURRENT_DATE", "timestamptz": "now()", "time": "CURRENT_TIME"}[kind])
    if raw == "@uuid":
        return sql.SQL("gen_random_uuid()")
    _, value = tb._default(kind, raw, col["name"])  # noqa: SLF001
    lit = sql.Literal(value)
    if kind in ("date", "timestamptz", "time", "uuid", "numeric", "double"):
        return sql.SQL("{}::{}").format(lit, sql.SQL(tb.TYPES[kind]["sql"]))
    return lit
