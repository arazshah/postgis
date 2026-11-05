import json

from django import template

register = template.Library()


@register.filter
def dv_json(user):
    """داده‌ی یک کاربر برای پر کردن مودال ویرایش/بازنشانی (JSON در data-attribute؛ قالب خودش escape می‌کند)."""
    return json.dumps({
        "user": user.pk, "username": user.username or user.phone or "", "full_name": user.full_name,
        "organization": user.organization, "phone": user.phone or "", "role": "admin" if user.is_superuser else "user",
    }, ensure_ascii=False, separators=(",", ":"))
