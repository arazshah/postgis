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
    geom: str = ""  # layer: point | line | polygon | "" (هر نوع)
    choices: tuple[tuple[str, str], ...] = ()
    empty: str = ""  # layer اختیاری: متن گزینهٔ «انتخاب نشده»


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
    # --- مجاورت و فاصله ---
    ToolInfo("within", "proximity", "t-within", ("لایه اول", "لایه دوم"), "عارضه‌های نزدیک + تعداد همسایه",
             "مدرسه‌هایی که تا ۳۰۰ متری یک بزرگراه هستند، با تعداد بزرگراه‌های نزدیک هر کدام.",
             ("ستون‌های لایه اول", "neighbor_count", "geom"),
             (Param("layer", "layer", "لایه‌ای که از آن انتخاب شود", "مثلاً مدرسه‌ها"),
              Param("other", "layer", "لایه مرجع", "مثلاً بزرگراه‌ها"),
              Param("distance", "number", "حداکثر فاصله (متر)", "عارضه‌هایی که دورتر باشند در نتیجه نمی‌آیند", "300"))),
    ToolInfo("voronoi", "proximity", "t-voronoi", ("لایه نقطه‌ای", "مرز (اختیاری)"), "حوزه نفوذ هر نقطه",
             "حوزه‌ی خدمات هر کلانتری: هر نقطه‌ی شهر به نزدیک‌ترین کلانتری می‌رسد.",
             ("ستون‌های لایه نقطه‌ای", "area_m2", "geom"),
             (Param("layer", "layer", "لایه مراکز", "مثلاً کلانتری‌ها", geom="point"),
              Param("other", "layer", "مرز برش (اختیاری)", "بدون مرز، حوزه‌های بیرونی تا مرز تقریبی داده‌ها کشیده می‌شوند",
                    required=False, geom="polygon", empty="بدون مرز"))),
    # --- شمارش و تراکم ---
    ToolInfo("cluster", "aggregate", "t-cluster", ("لایه نقطه‌ای",), "چندضلعی هر خوشه + تعداد",
             "کانون‌های تصادف: جاهایی که دست‌کم ۵ تصادف در شعاع ۲۰۰ متر دارند.",
             ("cluster_id", "point_count", "geom"),
             (Param("layer", "layer", "لایه نقطه‌ای", geom="point"),
              Param("distance", "number", "شعاع همسایگی (متر)", "نقطه‌های نزدیک‌تر از این فاصله به هم می‌پیوندند", "200"),
              Param("minpoints", "number", "حداقل نقطه در هر خوشه", "گروه‌های کوچک‌تر نقطهٔ پراکنده حساب می‌شوند", "5"))),
    ToolInfo("measure", "aggregate", "t-measure", ("چندضلعی", "خط یا چندضلعی"), "چندضلعی‌ها + طول یا مساحت",
             "کیلومتر معبر در هر محله، یا مساحت فضای سبز هر منطقه.",
             ("ستون‌های چندضلعی", "length_m + km_per_km2", "یا area_m2 + share_pct"),
             (Param("layer", "layer", "لایه چندضلعی", "مثلاً محله‌ها", geom="polygon"),
              Param("other", "layer", "لایه‌ای که اندازه‌گیری شود", "خطی برای طول، چندضلعی برای مساحت"),
              Param("mode", "choice", "اندازه‌گیری", default="length", required=False,
                    choices=(("length", "طول خط‌ها"), ("area", "مساحت چندضلعی‌ها"))))),
    # --- همپوشانی و تغییر ---
    ToolInfo("clip", "overlay", "t-clip", ("هر لایه", "مرز چندضلعی"), "بخش داخل مرز",
             "معابر فقط داخل منطقه ۶، یا مدرسه‌های داخل یک شهرستان.",
             ("ستون‌های لایه ورودی", "geom"),
             (Param("layer", "layer", "لایه‌ای که بریده شود", "نقطه، خط یا چندضلعی"),
              Param("other", "layer", "مرز برش", "مثلاً منطقه شهرداری", geom="polygon"))),
    ToolInfo("erase", "overlay", "t-erase", ("چندضلعی", "چندضلعی حذفی"), "چندضلعی باقی‌مانده",
             "بخش‌هایی از شهر که بیرون حریم ۵۰۰ متری هر مدرسه‌اند؛ یعنی مناطق کم‌برخوردار.",
             ("ستون‌های لایه اول", "area_m2", "geom"),
             (Param("layer", "layer", "لایه‌ای که از آن حذف شود", "مثلاً مرز شهر", geom="polygon"),
              Param("other", "layer", "ناحیهٔ حذفی", "مثلاً حریم مدرسه‌ها", geom="polygon"))),
    # --- شبکه معابر ---
    ToolInfo("route", "network", "t-route", ("دو نقطه",), "خط مسیر + طول",
             "کوتاه‌ترین مسیر خودرو از یک نقطه تا نقطه‌ی دیگر روی خیابان‌ها.",
             ("distance_m", "edges", "geom"),
             (Param("lon", "text", "طول جغرافیایی مبدأ", placeholder="51.389"),
              Param("lat", "text", "عرض جغرافیایی مبدأ", placeholder="35.700"),
              Param("lon2", "text", "طول جغرافیایی مقصد", placeholder="51.420"),
              Param("lat2", "text", "عرض جغرافیایی مقصد", placeholder="35.720")),
             needs_routing=True),
    ToolInfo("netnearest", "network", "t-netnearest", ("نقاط مبدأ", "نقاط مقصد"), "همان نقاط + فاصله روی خیابان",
             "هر خانه تا نزدیک‌ترین درمانگاه چند متر راه دارد (نه فاصله مستقیم).",
             ("ستون‌های لایه مبدأ", "network_m", "nearest_name (اختیاری)", "geom"),
             (Param("layer", "layer", "لایه مبدأ", "مثلاً خانه‌ها یا مدرسه‌ها (حداکثر ۳۰۰۰ نقطه)", geom="point"),
              Param("other", "layer", "لایه مقصد", "مثلاً درمانگاه‌ها (حداکثر ۵۰۰ نقطه)", geom="point"),
              Param("label", "text", "ستون نام در لایه مقصد", "اختیاری؛ برای نوشتن نام نزدیک‌ترین", required=False, placeholder="name"),
              Param("distance", "number", "حداکثر فاصله روی شبکه (متر)", "نقطه‌هایی که دورتر باشند بدون مقدار می‌مانند", "5000")),
             needs_routing=True),
    ToolInfo("coverage", "network", "t-coverage", ("نقاط مرکز",), "حوزه دسترسی هر مرکز",
             "پوشش ۸۰۰ متری پیاده‌ی همه‌ی ایستگاه‌های مترو؛ هر بخش به نزدیک‌ترین ایستگاه تعلق دارد.",
             ("ستون‌های لایه مرکز", "distance_m", "edges", "geom"),
             (Param("layer", "layer", "لایه مراکز", "مثلاً ایستگاه‌ها (حداکثر ۵۰۰ نقطه)", geom="point"),
              Param("distance", "number", "فاصله روی شبکه معابر (متر)", default="800")),
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
