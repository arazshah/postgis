"""واکنش پلاگین REST API به رویدادهای جدول؛ در plugin.py ثبت می‌شود."""
from .models import ApiTable


def table_dropped(*, ws, schema, table, **_) -> int:
    return ApiTable.objects.filter(service__database=ws, schema=schema, table=table).delete()[0]


def table_renamed(*, ws, schema, table, new, **_) -> None:
    ApiTable.objects.filter(service__database=ws, schema=schema, table=table).update(table=new)


def table_usage(*, ws, schema, table, **_) -> dict:
    return {"api": ApiTable.objects.filter(service__database=ws, schema=schema, table=table).count()}
