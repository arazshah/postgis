"""فیلترهای قالب فارسی: تاریخ شمسی، اعداد فارسی، حجم."""
import datetime
import json

import jdatetime
from django import template
from django.utils import timezone

register = template.Library()

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


@register.filter
def fanum(value):
    if value is None:
        return ""
    return str(value).translate(_FA_DIGITS)


@register.filter
def json_attr(value):
    """JSON فشرده برای data-attribute؛ نقل‌قول‌ها را خود قالب escape می‌کند."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@register.filter
def jdate(value, fmt="%Y/%m/%d"):
    if not value:
        return "—"
    if not isinstance(value, datetime.datetime):  # تاریخ بدون ساعت
        return jdatetime.date.fromgregorian(date=value).strftime(fmt).translate(_FA_DIGITS)
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return jdatetime.datetime.fromgregorian(datetime=value).strftime(fmt).translate(_FA_DIGITS)


@register.filter
def jdatetime_full(value):
    return jdate(value, "%Y/%m/%d ساعت %H:%M")


@register.filter
def fasize(num):
    try:
        num = float(num)
    except (TypeError, ValueError):
        return "—"
    for unit in ["بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"]:
        if num < 1024 or unit == "ترابایت":
            text = f"{num:.0f}" if unit == "بایت" else f"{num:.1f}".rstrip("0").rstrip(".")
            return f"{text} {unit}".translate(_FA_DIGITS)
        num /= 1024
    return ""


@register.filter
def pct_width(value):
    """عرض نوار پیشرفت؛ حداکثر ۱۰۰ و با نقطه انگلیسی برای CSS."""
    try:
        return f"{min(float(value), 100):.1f}"
    except (TypeError, ValueError):
        return "0"


@register.filter
def money(value):
    """۱۴۹٬۰۰۰ — جداکننده هزارگان فارسی با ارقام فارسی."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value
    return f"{n:,}".replace(",", "٬").translate(_FA_DIGITS)


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None
