"""SDK ابزار تحلیل: هر ابزار یک کلاس `ToolPlugin` در ماژول خودش (tools/plugins/<key>.py یا `geotools.py` هر اپ).

ابزار فقط «SELECT نتیجه» را می‌سازد (`build`)؛ ساخت جدول، نوع هندسه، کلید، نمایه و مالکیت را موتور (tools/engine.py)
برای همه یکسان انجام می‌دهد. SQL فقط با `psycopg.sql` (Identifier/Literal) ساخته می‌شود؛ متن کاربر هرگز مستقیم وارد SQL نمی‌شود.
همه‌ی فاصله‌ها به متر و روی geography (WGS84) حساب می‌شوند تا SRID جدول‌ها مهم نباشد.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from psycopg import sql

from kernel.plugins import registry

POINT, CATEGORY = "tool", "tool.category"
PARAM_KINDS = ("layer", "number", "text", "choice", "bool")
NUMERIC = {"int2", "int4", "int8", "float4", "float8", "numeric"}
EDGES = ("'SELECT gid AS id, source, target, length_m AS cost, "
         "CASE WHEN reverse_cost < 0 THEN -1 ELSE length_m END AS reverse_cost FROM routing.ways'")
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class Param:
    """یک فیلد فرم ابزار. kind: layer (با فیلتر geom)، number، text (ستون یا متن، ltr)، choice (چیپ)، bool."""
    name: str
    kind: str
    label: str
    help: str = ""
    default: str = ""
    required: bool = True
    placeholder: str = ""
    geom: str = ""  # layer: point | line | polygon | "" (هر نوع)
    choices: tuple[tuple[str, str], ...] = ()
    empty: str = ""  # layer اختیاری: متن گزینهٔ «انتخاب نشده»


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    hint: str


class ToolPlugin:
    """پایه‌ی هر ابزار. زیرکلاس ویژگی‌ها را پر می‌کند و `build` را می‌نویسد."""
    key: str = ""
    title: str = ""
    description: str = ""
    category: str = ""
    icon: str = ""  # نام آیکون در core/icons.py
    inputs: tuple[str, ...] = ()
    output: str = ""
    example: str = ""
    columns: tuple[str, ...] = ()
    params: tuple[Param, ...] = ()
    needs_routing: bool = False
    chart_hint: dict | None = None  # پیشنهاد نمودار برای جدول نتیجه (تاریخچه)
    order: int = 100  # ترتیب در گالری
    plugin: str = "tools"

    def build(self, ctx: Context):
        """SELECT نتیجه به‌صورت `sql.Composable`؛ ورودی نامعتبر = ToolError با پیام فارسی."""
        raise NotImplementedError

    def summary_extra(self, params: dict) -> list[str]:
        """تکه‌های ویژه‌ی این ابزار در خلاصه‌ی ردیف تاریخچه."""
        return []

    def after_create(self, conn, target) -> None:
        """بررسی پس از ساخت جدول (همان تراکنش)؛ ToolError = لغو و پیام به کاربر."""

    def summary(self, params: dict) -> str:
        parts = []
        if params.get("layer"):
            parts.append(params["layer"].removeprefix("public."))
        if params.get("other"):
            parts.append("با " + params["other"].removeprefix("public."))
        for k, label, unit in (("distance", "فاصله", "متر"), ("size", "اندازه خانه", "متر")):
            if params.get(k):
                parts.append(f"{label} {params[k]} {unit}")
        parts += self.summary_extra(params)
        if params.get("value"):
            parts.append(f"{params.get('agg') or 'sum'} {params['value']}")
        if params.get("category"):
            parts.append(f"دسته {params['category']}" + (f" ← {params['category2']}" if params.get("category2") else ""))
        if params.get("dissolve") == "on":
            parts.append("یکپارچه")
        return " · ".join(parts)[:300]


def register(cls: type[ToolPlugin]) -> type[ToolPlugin]:
    """دکوراتور ثبت ابزار در نقطه‌ی توسعه‌ی `tool`."""
    tool = cls()
    registry.add(POINT, tool.key, tool, plugin=tool.plugin, order=tool.order)
    return cls


def category(key: str, title: str, hint: str, *, order: int, plugin: str = "tools") -> None:
    registry.add(CATEGORY, key, Category(key, title, hint), plugin=plugin, order=order)


def all_tools() -> list[ToolPlugin]:
    return registry.values(POINT)


def get(key: str) -> ToolPlugin | None:
    return registry.get(POINT, key)


def categories() -> list[Category]:
    return registry.values(CATEGORY)


# ---------------------------------------------------------------------- زمینه‌ی ساخت SELECT
@dataclass
class Context:
    """آنچه `build` لازم دارد: کاتالوگ پایگاه کاربر (فقط خواندن)، پارامترهای خام فرم و کمک‌تابع‌های اعتبارسنجی."""
    ex: object
    tables: dict
    params: dict
    guards: list = field(default_factory=list)  # (پرس‌وجوی شمارش، سقف، پیام): پیش از ساخت جدول بررسی می‌شود

    def table(self, name_key: str):
        t = self.tables.get(self.params.get(name_key) or "")
        if t is None:
            raise ToolError("لایه انتخاب نشده یا وجود ندارد.")
        return t

    def number(self, k: str, lo: float, hi: float) -> float:
        try:
            v = float(str(self.params.get(k, "")).replace(",", "").translate(_FA_DIGITS))
        except ValueError as exc:
            raise ToolError("عدد نامعتبر است.") from exc
        if not lo <= v <= hi:
            raise ToolError(f"مقدار باید بین {lo:g} و {hi:g} باشد.")
        return v

    def guard(self, t, col: str, cap: int, msg: str) -> None:
        self.guards.append((sql.SQL("SELECT count(*) FROM (SELECT 1 FROM {} WHERE {} IS NOT NULL LIMIT {}) x").format(
            sql.Identifier(t.schema, t.name), sql.Identifier(col), sql.Literal(cap + 1)), cap, msg))

    def need_routing(self) -> None:
        if "routing.ways" not in self.tables:
            raise ToolError("شبکه معابر (routing.ways) ندارید؛ از «داده آماده ایران» شبکه مسیریابی بگیرید.")

    def cols(self, t) -> set[str]:
        return {c["name"] for c in self.ex.columns(t)}

    def attr_cols(self, t) -> set[str]:
        return {c["name"] for c in self.ex.columns(t) if not c["spatial"]}


# ---------------------------------------------------------------------- کمک‌تابع‌های SQL
def geom4326(alias: str, col: str, srid: int):
    g = sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(col))
    if srid in (0, 4326):
        return sql.SQL("ST_SetSRID({}::geometry, 4326)").format(g)
    return sql.SQL("ST_Transform({}::geometry, 4326)").format(g)


def attrs(ex, t, alias: str, prefix: str = "", exclude=()) -> list:
    out = []
    for c in ex.columns(t):
        if c["spatial"] or c["name"] in exclude or c["name"] in ("gid",):
            continue
        out.append(sql.SQL("{}.{} AS {}").format(sql.Identifier(alias), sql.Identifier(c["name"]),
                                                 sql.Identifier(f"{prefix}{c['name']}"[:63])))
    return out


def attr_sql(ex, t, alias: str):
    """ستون‌های غیرمکانی با ویرگول پایانی (یا خالی)."""
    a = attrs(ex, t, alias)
    return sql.SQL(", ").join(a) + sql.SQL(", ") if a else sql.SQL("")


def geom_of(t, want: tuple[str, ...] | None = None, ex=None) -> tuple[str, int, str]:
    """(نام ستون مکانی، SRID، نوع). `want` نوع‌های مجاز است؛ ناسازگار = ToolError."""
    if not t.geometry:
        raise ToolError(f"جدول {t.name} ستون مکانی ندارد.")
    g = t.geometry[0]
    gtype = (g.get("type") or "").upper()
    if want and gtype in ("GEOMETRY", "") and ex is not None:
        # ستون با نوع عمومی: نوع واقعی چند ردیف اول
        with ex.connect() as conn:
            rows = conn.execute(sql.SQL("SELECT DISTINCT GeometryType({c}) FROM (SELECT {c} FROM {t} WHERE {c} IS NOT NULL "
                                        "LIMIT 200) s").format(c=sql.Identifier(g["column"]),
                                                               t=sql.Identifier(t.schema, t.name))).fetchall()
        gtype = ",".join(sorted(r[0] for r in rows if r[0])) or gtype
    if want and not any(w in gtype for w in want) and gtype not in ("GEOMETRY", ""):
        raise ToolError(f"جدول {t.name} از نوع {gtype} است؛ این ابزار {'/'.join(want)} می‌خواهد.")
    return g["column"], int(g.get("srid") or 0), gtype


def in_srid(alias: str, col: str, srid: int, target: int):
    """ستون مکانی در SRID لایه دیگر، برای شرط ST_Intersects (نمایه مکانی لایه اول)."""
    ident_ = sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(col))
    if srid != target and srid != 0 and target != 0:
        return sql.SQL("ST_Transform({}, {})").format(ident_, sql.Literal(target))
    return ident_


def bbox_pre(alias: str, col: str, srid: int, other):
    """شرط && روی نمایه مکانی (فقط وقتی SRID ستون روشن است)؛ خالی = بدون پیش‌فیلتر."""
    c = sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(col))
    if srid == 4326:
        return sql.SQL("AND {} && {}").format(c, other)
    if srid > 0:
        return sql.SQL("AND {} && ST_Transform({}, {})").format(c, other, sql.Literal(srid))
    return sql.SQL("")


def base_kinds(gtype: str) -> list[str]:
    return [k for k in ("POINT", "LINESTRING", "POLYGON") if k in gtype]


def nearest_vertex(lon, lat):
    return sql.SQL("ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint({}, {}), 4326) LIMIT 1").format(
        sql.Literal(lon), sql.Literal(lat))


def ident(t):
    return sql.Identifier(t.schema, t.name)
