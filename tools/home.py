"""سهم پلاگین ابزارها در صفحه‌ی خانه: اجراهای اخیر."""
from django.urls import reverse

from analysis.models import ToolRun

from . import sdk


def feed(user, dbs):
    rows = []
    for t in ToolRun.objects.filter(database__in=dbs).select_related("database").order_by("-created_at")[:4]:
        tool = sdk.get(t.tool)
        rows.append({"icon": "toolbox", "kind": "ابزار تحلیل",
                     "text": getattr(tool, "title", t.tool) + (f" — {t.summary}" if t.summary else ""),
                     "db": t.database.db_name, "when": t.created_at, "url": reverse("tools:page", args=[t.database_id])})
    return rows
