"""سهم پلاگین نقشه‌ها در صفحه‌ی خانه."""
from django.urls import reverse

from .models import WebMap


def feed(user, dbs):
    return [{"icon": "globe", "kind": "نقشه", "text": m.title, "db": m.database.db_name, "when": m.updated_at,
             "url": reverse("maps:composer", args=[m.database_id, m.pk])}
            for m in WebMap.objects.filter(database__in=dbs).select_related("database").order_by("-updated_at")[:4]]


def step_map(user, dbs, target):
    return {"label": "اولین نقشه را بسازید", "hint": "لایه‌ها را روی نقشه ببینید",
            "done": bool(dbs) and WebMap.objects.filter(database__in=dbs).exists(),
            "url": reverse("maps:index", args=[target.pk]) if target else "", "icon": "globe"}
