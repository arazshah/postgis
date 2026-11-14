"""کمک‌تابع‌های مشترک ابزارهای تک‌لایه‌ای: SELECT استاندارد «صفات + ستون‌های افزوده + هندسه‌ی نتیجه»."""
from psycopg import sql

from tools import sdk


def unary(ctx, t, col, expr, extra=None, where=None):
    """`expr` عبارت هندسه‌ی نتیجه است (با sdk.geom4326("s", ...) ساخته شده)."""
    return sql.SQL("SELECT {attrs}{extra}{expr} AS geom FROM {src} s WHERE s.{c} IS NOT NULL{where}").format(
        attrs=sdk.attr_sql(ctx.ex, t, "s"), extra=extra or sql.SQL(""), expr=expr, src=sdk.ident(t),
        c=sql.Identifier(col), where=(sql.SQL(" AND ") + where) if where is not None else sql.SQL(""))


def deg_per_m(g):
    """درجه‌ی تقریبی هم‌ارز یک متر در عرض هندسه‌ی `g` (برای پیش‌فیلتر جعبه‌ای)."""
    return sql.SQL("(1.0 / (111320.0 * greatest(cos(radians(least(abs(ST_Y(ST_PointOnSurface({g}))), 85))), 0.05)))").format(g=g)


def num_col(ctx, t, key: str, required: bool = False) -> str:
    """ستون عددی (غیرمکانی) انتخابی کاربر؛ خالی و اختیاری = ""."""
    name = (ctx.params.get(key) or "").strip()
    if not name:
        if required:
            raise sdk.ToolError("ستون عددی را مشخص کنید.")
        return ""
    c = next((c for c in ctx.ex.columns(t) if c["name"] == name and not c["spatial"]), None)
    if c is None or c["base"] not in sdk.NUMERIC:
        raise sdk.ToolError(f"ستون «{name}» باید یک ستون عددی در لایه {t.name} باشد.")
    return name
