from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

from ._common import unary


@sdk.register
class Smooth(ToolPlugin):
    key, order, category, icon = "smooth", 70, "geometry", "t-smooth"
    level = "mid"
    title = "نرم‌سازی خط و چندضلعی"
    description = "گوشه‌های تیز را با روش چایکین گرد می‌کند؛ مناسب مسیرها و منحنی‌میزان‌ها."
    inputs, output = ("خط یا چندضلعی",), "هندسه‌ی نرم‌شده"
    example = "نرم کردن مسیر GPS خام برای نمایش زیباتر روی نقشه."
    columns = ("ستون‌های لایه ورودی", "geom")
    params = (
        Param("layer", "layer", "لایه خطی یا چندضلعی"),
        Param("iterations", "number", "تعداد دفعات نرم‌سازی", "هر چه بیشتر، نرم‌تر (۱ تا ۵)", "3", unit="بار"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t, ("LINE", "POLYGON"), ctx.ex)
        n = int(ctx.number("iterations", 1, 5))
        ctx.guard(t, col, 50_000, "این ابزار تا ۵۰٬۰۰۰ عارضه را پشتیبانی می‌کند.")
        return unary(ctx, t, col, sql.SQL("ST_ChaikinSmoothing({g}, {n})").format(g=sdk.geom4326("s", col, srid), n=sql.Literal(n)))
