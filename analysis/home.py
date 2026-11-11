"""سهم پلاگین تحلیل در صفحه‌ی خانه: پرسش‌های فارسی اخیر و گام اتصال مدل زبانی."""
from django.urls import reverse

from .models import LlmConfig, Question


def feed(user, dbs):
    return [{"icon": "spark", "kind": "پرسش فارسی", "text": q.text, "db": q.database.db_name, "when": q.created_at,
             "url": reverse("analysis:page", args=[q.database_id]) + "#history"}
            for q in Question.objects.filter(database__in=dbs).select_related("database").order_by("-created_at")[:4]]


def step_llm(user, dbs, target):
    return {"label": "مدل زبانی را وصل کنید", "hint": "برای پرسش فارسی", "done": LlmConfig.objects.filter(user=user).exists(),
            "url": reverse("accounts:profile") + "#ai", "icon": "spark"}
