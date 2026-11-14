from tools import sdk
from tools.sdk import Param, ToolPlugin

from ._overlay import pieces


@sdk.register
class SymDiff(ToolPlugin):
    key, order, category, icon = "symdiff", 50, "overlay", "t-symdiff"
    level = "adv"
    title = "تفاضل متقارن"
    description = "بخش‌هایی را می‌دهد که فقط در یکی از دو لایه هستند و بخش مشترک را حذف می‌کند."
    inputs, output = ("لایه چندضلعی اول", "لایه چندضلعی دوم"), "تکه‌های غیرمشترک + ستون part"
    example = "اختلاف دو نسخه‌ی مرز شهر: کجا اضافه و کجا کم شده است؟"
    columns = ("a_… و b_… (صفات)", "part (a_only | b_only)", "geom")
    params = (
        Param("layer", "layer", "لایه چندضلعی اول", geom="polygon"),
        Param("other", "layer", "لایه چندضلعی دوم", geom="polygon"),
    )

    def build(self, ctx):
        return pieces(ctx, ("a", "b"))
