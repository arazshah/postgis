"""برچسب‌های قاب پنل مدیریت (ناوبری، جست‌وجوی سراسری)."""
import json

from django import template
from django.utils.safestring import mark_safe

from core import admin_nav

register = template.Library()


@register.simple_tag(takes_context=True)
def admin_nav_groups(context):
    request = context["request"]
    return admin_nav.build(request)


@register.simple_tag(takes_context=True)
def admin_palette(context):
    """JSON فهرست بخش‌ها برای Ctrl+K؛ در script از نوع json امن است."""
    request = context["request"]
    rows = admin_nav.palette(admin_nav.build(request), request)
    data = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    return mark_safe(f'<script type="application/json" id="ap-palette">{data}</script>')  # noqa: S308
