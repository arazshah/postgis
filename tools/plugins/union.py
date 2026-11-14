from tools import sdk
from tools.sdk import Param, ToolPlugin

from ._overlay import pieces


@sdk.register
class Union(ToolPlugin):
    key, order, category, icon = "union", 40, "overlay", "t-union"
    level = "adv"
    title = "اجتماع دو لایه"
    description = "دو لایه‌ی چندضلعی را روی هم می‌اندازد و سه نوع تکه می‌سازد: فقط اول، فقط دوم و مشترک؛ با صفات هر دو."
    inputs, output = ("لایه چندضلعی اول", "لایه چندضلعی دوم"), "همه‌ی تکه‌ها + ستون part"
    example = "ترکیب نقشه‌ی کاربری قدیم و جدید برای دیدن همه‌ی پهنه‌ها در یک لایه."
    columns = ("a_… و b_… (صفات)", "part (both | a_only | b_only)", "geom")
    params = (
        Param("layer", "layer", "لایه چندضلعی اول", geom="polygon"),
        Param("other", "layer", "لایه چندضلعی دوم", geom="polygon"),
    )

    def build(self, ctx):
        return pieces(ctx, ("both", "a", "b"))
