"""فهرست ابزارهای آماده با ظاهر و فرم: افزودن ابزار تازه = یک `ToolInfo` اینجا + منطق اجرا در analysis/tools.py.

فرم هر ابزار از روی `params` ساخته می‌شود (بدون if در قالب). انواع پارامتر:
layer (فهرست لایه‌های مکانی، با فیلتر geom)، number، text (ستون یا متن، ltr)، choice (چیپ)، bool.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from analysis import tools as engine


@dataclass(frozen=True)
class Param:
    name: str
    kind: str
    label: str
    help: str = ""
    default: str = ""
    required: bool = True
    placeholder: str = ""
    geom: str = ""  # layer: point | polygon | "" (هر نوع)
    choices: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ToolInfo:
    key: str
    category: str
    icon: str
    inputs: tuple[str, ...]
    output: str
    example: str
    columns: tuple[str, ...]
    params: tuple[Param, ...]
    needs_routing: bool = False
    # برای نمایش
    title: str = field(default="", compare=False)
    description: str = field(default="", compare=False)


CATEGORIES = (
    ("proximity", "مجاورت و فاصله", "حریم، نزدیک‌ترین و فاصله‌ها"),
    ("aggregate", "شمارش و تراکم", "شمردن و خلاصه کردن نقطه‌ها"),
    ("overlay", "همپوشانی و تغییر", "برش دو لایه چندضلعی و مقایسه نسخه‌ها"),
    ("network", "شبکه معابر", "دسترسی روی خیابان‌ها"),
)
OUTPUT = Param("output", "text", "نام جدول خروجی", "حروف انگلیسی کوچک، عدد و _", required=True)

_INFO = [
    ToolInfo("buffer", "proximity", "t-buffer", ("هر لایه",), "چندضلعی حریم",
             "حریم ۵۰۰ متری ایستگاه‌های مترو را بساز تا ببینی کدام مدرسه‌ها داخلش هستند.",
             ("ستون‌های لایه ورودی", "geom"),
             (Param("layer", "layer", "لایه ورودی"),
              Param("distance", "number", "فاصله (متر)", "فاصلهٔ حریم از هر عارضه", "500"),
              Param("dissolve", "bool", "همه حریم‌ها یکی شوند", "به‌جای یک حریم برای هر عارضه، یک چندضلعی واحد", required=False))),
    ToolInfo("nearest", "proximity", "t-nearest", ("لایه مبدأ", "لایه هدف"), "همان عارضه‌ها + فاصله",
             "برای هر مدرسه نزدیک‌ترین پارک و فاصلهٔ آن را پیدا کن.",
             ("ستون‌های لایه مبدأ", "distance_m", "nearest_name (اختیاری)"),
             (Param("layer", "layer", "لایه مبدأ"),
              Param("other", "layer", "لایه هدف", "نزدیک‌ترینِ این لایه پیدا می‌شود"),
              Param("label", "text", "ستون نام در لایه هدف", "اختیاری؛ برای نوشتن نام نزدیک‌ترین", required=False, placeholder="name"))),
    ToolInfo("count", "aggregate", "t-count", ("چندضلعی", "نقطه"), "چندضلعی‌ها + تعداد",
             "تعداد مدرسه‌های هر محله، با جمع یا میانگین یک ستون عددی مثل قیمت.",
             ("ستون‌های چندضلعی", "point_count", "جمع یا میانگین ستون (اختیاری)"),
             (Param("layer", "layer", "لایه چندضلعی", "مثلاً محله‌ها", geom="polygon"),
              Param("other", "layer", "لایه نقطه‌ای که شمرده شود", "مثلاً مدرسه‌ها", geom="point"),
              Param("value", "text", "ستون عددی لایه نقطه‌ای", "اختیاری؛ برای جمع یا میانگین", required=False, placeholder="price"),
              Param("agg", "choice", "محاسبهٔ ستون", default="sum", required=False,
                    choices=(("sum", "جمع"), ("avg", "میانگین"), ("min", "کمینه"), ("max", "بیشینه"))))),
    ToolInfo("hexbin", "aggregate", "t-hexbin", ("لایه نقطه‌ای",), "شبکه شش‌ضلعی + تعداد",
             "نقشهٔ حرارتی تصادفات یا مدرسه‌ها با خانه‌های ۵۰۰ متری.",
             ("count", "geom"),
             (Param("layer", "layer", "لایه نقطه‌ای", geom="point"),
              Param("size", "number", "اندازهٔ هر خانه (متر)", "ضلع تقریبی هر شش‌ضلعی", "500"))),
    ToolInfo("overlap", "overlay", "t-overlap", ("چندضلعی منطقه", "چندضلعی دسته‌دار"), "سهم هر دسته در هر منطقه",
             "سهم هر کاربری زمین (مسکونی، تجاری…) از مساحت هر محله.",
             ("zone", "category", "area_m2", "share_pct"),
             (Param("layer", "layer", "لایه مناطق", "مثلاً محله", geom="polygon"),
              Param("other", "layer", "لایه چندضلعی دسته‌دار", "مثلاً کاربری زمین", geom="polygon"),
              Param("zone", "text", "ستون نام مناطق (لایه اول)", placeholder="name"),
              Param("category", "text", "ستون دسته (لایه دوم)", placeholder="landuse"))),
    ToolInfo("change", "overlay", "t-change", ("نسخهٔ قدیم", "نسخهٔ جدید"), "مساحت هر «از ← به»",
             "ببین چه مساحتی از کاربری ۱۴۰۰ تا ۱۴۰۵ از زمین کشاورزی به مسکونی تبدیل شد.",
             ("from_category", "to_category", "area_m2"),
             (Param("layer", "layer", "نسخهٔ قدیم", "لایه چندضلعی", geom="polygon"),
              Param("other", "layer", "نسخهٔ جدید", "لایه چندضلعی", geom="polygon"),
              Param("category", "text", "ستون دسته در نسخهٔ قدیم", placeholder="landuse"),
              Param("category2", "text", "ستون دسته در نسخهٔ جدید", placeholder="landuse"))),
    ToolInfo("isochrone", "network", "t-isochrone", ("نقطهٔ شروع",), "محدودهٔ دسترسی",
             "تا کجا می‌شود از یک نقطه با ۱۰۰۰ متر پیاده‌روی روی خیابان‌ها رسید.",
             ("distance_m", "edges", "geom"),
             (Param("lon", "text", "طول جغرافیایی", "نقطهٔ شروع", placeholder="51.389"),
              Param("lat", "text", "عرض جغرافیایی", placeholder="35.700"),
              Param("distance", "number", "فاصله روی شبکه معابر (متر)", default="1000")),
             needs_routing=True),
]
# عنوان و توضیح از موتور اجرا (analysis.tools.TOOLS) می‌آید تا یک منبع حقیقت بماند
CATALOG = []
for _i in _INFO:
    _t = engine.TOOL_MAP[_i.key]
    CATALOG.append(ToolInfo(**{**_i.__dict__, "title": _t.title, "description": _t.description}))
INFO = {i.key: i for i in CATALOG}


def category_groups():
    return [{"key": k, "title": t, "hint": h, "tools": [i for i in CATALOG if i.category == k]} for k, t, h in CATEGORIES
            if any(i.category == k for i in CATALOG)]
