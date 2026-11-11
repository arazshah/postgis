"""واکنش پلاگین نقشه‌ها به رویدادهای جدول؛ در plugin.py ثبت می‌شود."""
from .models import MapLayer


def table_dropped(*, ws, schema, table, **_) -> int:
    MapLayer.objects.filter(webmap__database=ws, schema=schema, table=table).delete()
    return 0  # حذف لایه‌ی نقشه جزو «انتشار برداشته شد» حساب نمی‌شود


def table_renamed(*, ws, schema, table, new, **_) -> None:
    MapLayer.objects.filter(webmap__database=ws, schema=schema, table=table).update(table=new)


def table_usage(*, ws, schema, table, **_) -> dict:
    return {"maps": MapLayer.objects.filter(webmap__database=ws, schema=schema, table=table).count()}


def table_map_targets(*, ws, editable, **_) -> dict:
    """نقشه‌های این پایگاه برای منوی «افزودن به نقشه» در زبانه‌ی نقشه‌ی جدول (فقط برای ویرایشگر)."""
    from .models import WebMap

    return {"maps": list(WebMap.objects.filter(database=ws).only("pk", "title")) if editable else []}
