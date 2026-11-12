from django import template

register = template.Library()


@register.filter
def get(mapping, key):
    """مقدار یک کلید از dict در قالب (برای مقدارهای پارامتر صفحه)."""
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.simple_tag(takes_context=True)
def route_on(context, name, ws=None):
    """آیا مسیر «گروه:نام» (ثبت‌شده با kernel.routes) برای این کاربر و فضای کار روشن و مجاز است؟

    پیوند بین‌بخشی در قالب نباید به صفحه‌ی ۴۰۴ برود وقتی مدیر آن بخش را خاموش یا محدود کرده:
    `{% route_on "databases:import" db as imp %}{% if imp %}…{% endif %}`. مسیر ثبت‌نشده (میزبان یا اپ دیگر) همیشه روشن است.
    """
    from kernel import routes

    return routes.on(name, user=getattr(context.get("request"), "user", None), ws=ws)
