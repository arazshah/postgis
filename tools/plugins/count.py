from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolError, ToolPlugin


@sdk.register
class Count(ToolPlugin):
    key, order, category, icon = "count", 30, "aggregate", "t-count"
    title = "شمارش در چندضلعی"
    description = "تعداد نقطه‌های یک لایه داخل هر چندضلعی؛ مثلاً مدرسه‌های هر محله."
    inputs, output = ("چندضلعی", "نقطه"), "چندضلعی‌ها + تعداد"
    example = "تعداد مدرسه‌های هر محله، با جمع یا میانگین یک ستون عددی مثل قیمت."
    columns = ("ستون‌های چندضلعی", "point_count", "جمع یا میانگین ستون (اختیاری)")
    chart_hint = {"kind": "hist", "field": "point_count"}
    params = (
        Param("layer", "layer", "لایه چندضلعی", "مثلاً محله‌ها", geom="polygon"),
        Param("other", "layer", "لایه نقطه‌ای که شمرده شود", "مثلاً مدرسه‌ها", geom="point"),
        Param("value", "text", "ستون عددی لایه نقطه‌ای", "اختیاری؛ برای جمع یا میانگین", required=False, placeholder="price"),
        Param("agg", "choice", "محاسبهٔ ستون", default="sum", required=False,
              choices=(("sum", "جمع"), ("avg", "میانگین"), ("min", "کمینه"), ("max", "بیشینه"))),
    )

    def build(self, ctx):
        ex, params = ctx.ex, ctx.params
        p, q = ctx.table("layer"), ctx.table("other")
        cp, sp, _ = sdk.geom_of(p, ("POLYGON",), ex)
        cq, sq, _ = sdk.geom_of(q)
        gq_in_p = sdk.in_srid("q", cq, sq, sp)
        attrs = sdk.attrs(ex, p, "p")
        extra = sql.SQL("")
        value = (params.get("value") or "").strip()
        agg = "sum"
        if value:  # جمع یا میانگین یک ستون عددی لایه نقطه‌ای در هر چندضلعی
            agg = params.get("agg") if params.get("agg") in ("sum", "avg", "min", "max") else "sum"
            col_q = next((c for c in ex.columns(q) if c["name"] == value and not c["spatial"]), None)
            if col_q is None or col_q["base"] not in sdk.NUMERIC:
                raise ToolError("ستون مقدار باید یک ستون عددی در لایه نقطه‌ای باشد.")
            extra = sql.SQL(", {a}(q.{v}::float8) AS {n}").format(
                a=sql.SQL(agg), v=sql.Identifier(value), n=sql.Identifier(f"{agg}_{value}"[:63]))
        return sql.SQL(
            "SELECT {attrs}c.point_count{extra_out}, {gp} AS geom FROM {P} p CROSS JOIN LATERAL "
            "(SELECT count(*) AS point_count{extra} FROM {Q} q WHERE ST_Intersects(p.{cp}, {gq})) c "
            "WHERE p.{cp} IS NOT NULL").format(
            attrs=sql.SQL(", ").join(attrs) + sql.SQL(", ") if attrs else sql.SQL(""), Q=sdk.ident(q),
            cp=sql.Identifier(cp), gq=gq_in_p, gp=sdk.geom4326("p", cp, sp), P=sdk.ident(p),
            extra=extra, extra_out=sql.SQL(", c.{}").format(sql.Identifier(f"{agg}_{value}"[:63])) if value else sql.SQL(""))
