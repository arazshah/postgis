"""بررسی سیستم ابزارهای ثبت‌شده (داخلی یا از اپ‌های دیگر): `manage.py check` و CI."""
from django.core.checks import Error, register

from . import engine, sdk


@register()
def tools_ok(app_configs, **kwargs):
    from core.icons import ICONS

    cats = {c.key for c in sdk.categories()}
    out = []

    def bad(tool, msg):
        out.append(Error(f"ابزار {tool.key or type(tool).__name__}: {msg}", id="tools.E001"))

    for t in sdk.all_tools():
        if not (t.key and t.title and t.description and t.example and t.columns and t.output):
            bad(t, "کلید، عنوان، توضیح، مثال، خروجی و ستون‌ها لازم است.")
        if len(t.key) > 20:
            bad(t, "کلید ابزار حداکثر ۲۰ نویسه است (ستون ToolRun.tool).")
        if t.category not in cats:
            bad(t, f"دسته‌ی ناشناخته: {t.category!r}")
        if t.icon not in ICONS:
            bad(t, f"آیکون {t.icon!r} در core/icons.py نیست.")
        names = [p.name for p in t.params]
        if len(set(names)) != len(names) or set(names) & set(engine.COMMON_PARAMS):
            bad(t, "نام پارامترها باید یکتا باشد و با output/replace برخورد نکند.")
        for p in t.params:
            if p.kind not in sdk.PARAM_KINDS:
                bad(t, f"نوع پارامتر ناشناخته: {p.name}={p.kind!r}")
            if p.kind == "choice" and not p.choices:
                bad(t, f"پارامتر انتخابی {p.name} گزینه ندارد.")
        if type(t).build is sdk.ToolPlugin.build:
            bad(t, "متد build پیاده نشده است.")
    return out
