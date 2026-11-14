from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class MakeValid(ToolPlugin):
    key, order, category, icon = "makevalid", 10, "quality", "t-makevalid"
    popular = True
    title = "اصلاح هندسه‌ی نامعتبر"
    description = "هندسه‌های خراب (خودمتقاطع، حلقه‌ی باز و …) را اصلاح می‌کند و دلیل خرابی هر کدام را می‌نویسد."
    inputs, output = ("هر لایه",), "هندسه‌ی اصلاح‌شده + وضعیت"
    example = "رفع خطای برش و پیوند مکانی روی لایه‌ی کاداستر که چندضلعی‌های خودمتقاطع دارد."
    columns = ("ستون‌های لایه ورودی", "was_valid", "issue", "geom")
    params = (
        Param("layer", "layer", "لایه ورودی"),
        Param("only_invalid", "bool", "فقط عارضه‌های نامعتبر", "برای مرور مشکل‌ها؛ در غیر این صورت همه می‌آیند", required=False),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, gtype = sdk.geom_of(t)
        g = sdk.geom4326("s", col, srid)
        fixed = sql.SQL("ST_MakeValid({})").format(g)
        kinds = sdk.base_kinds(gtype.upper())
        if len(kinds) == 1:
            fixed = sql.SQL("ST_CollectionExtract({}, {})").format(fixed, sql.Literal({"POINT": 1, "LINESTRING": 2, "POLYGON": 3}[kinds[0]]))
        only = ctx.params.get("only_invalid") == "on"
        return sql.SQL(
            "SELECT {attrs}ST_IsValid({g}) AS was_valid, CASE WHEN ST_IsValid({g}) THEN NULL ELSE ST_IsValidReason({g}) END AS issue, "
            "{fixed} AS geom FROM {src} s WHERE s.{c} IS NOT NULL{only}").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), g=g, fixed=fixed, src=sdk.ident(t), c=sql.Identifier(col),
            only=sql.SQL(" AND NOT ST_IsValid({})").format(g) if only else sql.SQL(""))

    def summary_extra(self, params):
        return ["فقط نامعتبرها"] if params.get("only_invalid") == "on" else []
