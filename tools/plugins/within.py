from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Within(ToolPlugin):
    key, order, category, icon = "within", 60, "proximity", "t-within"
    level = "mid"
    title = "انتخاب بر اساس فاصله"
    description = "عارضه‌های یک لایه را که تا فاصله‌ی مشخصی از لایه‌ی دیگر هستند جدا می‌کند و تعداد همسایه‌ها را کنارشان می‌گذارد."
    inputs, output = ("لایه اول", "لایه دوم"), "عارضه‌های نزدیک + تعداد همسایه"
    example = "مدرسه‌هایی که تا ۳۰۰ متری یک بزرگراه هستند، با تعداد بزرگراه‌های نزدیک هر کدام."
    columns = ("ستون‌های لایه اول", "neighbor_count", "geom")
    params = (
        Param("layer", "layer", "لایه‌ای که از آن انتخاب شود", "مثلاً مدرسه‌ها"),
        Param("other", "layer", "لایه مرجع", "مثلاً بزرگراه‌ها"),
        Param("distance", "number", "حداکثر فاصله", "عارضه‌هایی که دورتر باشند در نتیجه نمی‌آیند", "300", unit="متر"),
    )

    def build(self, ctx):
        ident = sql.Identifier
        a, b = ctx.table("layer"), ctx.table("other")
        ca, sa, _ = sdk.geom_of(a)
        cb, sb, _ = sdk.geom_of(b)
        d = ctx.number("distance", 1, 100_000)
        ga, gb = sdk.geom4326("a", ca, sa), sdk.geom4326("b", cb, sb)
        pre = sql.SQL("")
        if sb in (0, 4326):  # پیش‌فیلتر جعبه‌ای با نمایه لایه دوم؛ درجه طول با کسینوس عرض بزرگ‌نمایی می‌شود
            pre = sql.SQL("AND b.{cb} && ST_Expand({ga}, {d} / (111320.0 * greatest(cos(radians(least(abs(ST_Y(ST_PointOnSurface({ga}))), "
                          "85))), 0.05)))").format(cb=ident(cb), ga=ga, d=sql.Literal(d))
        return sql.SQL(
            "SELECT {attrs}c.neighbor_count, {ga}::geometry AS geom FROM {A} a CROSS JOIN LATERAL (SELECT count(*) AS neighbor_count "
            "FROM {B} b WHERE b.{cb} IS NOT NULL {pre} AND ST_DWithin({ga}::geography, {gb}::geography, {d})) c "
            "WHERE a.{ca} IS NOT NULL AND c.neighbor_count > 0").format(
            attrs=sdk.attr_sql(ctx.ex, a, "a"), ga=ga, gb=gb, A=sdk.ident(a), B=sdk.ident(b), ca=ident(ca),
            cb=ident(cb), pre=pre, d=sql.Literal(d))
