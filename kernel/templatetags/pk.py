from django import template

register = template.Library()


@register.filter
def get(mapping, key):
    """مقدار یک کلید از dict در قالب (برای مقدارهای پارامتر صفحه)."""
    try:
        return mapping.get(key)
    except AttributeError:
        return None
