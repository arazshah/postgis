"""کارهای دوره‌ای دستیار: به‌روزرسانی embeddingها و پاک‌سازی شمارنده‌های قدیمی."""
from datetime import timedelta

from django.utils import timezone

from .models import Usage

KEEP_DAYS = 90
EMBED_PER_RUN = 300


def maintenance() -> dict:
    from core.models import SiteSettings
    from kb import embedding

    out = {"embedded": 0, "deleted": 0, "error": ""}
    out["deleted"] = Usage.objects.filter(created_at__lt=timezone.now() - timedelta(days=KEEP_DAYS)).delete()[0]
    conf = SiteSettings.get()
    if conf.assistant_enabled and conf.assistant_key_ready:
        res = embedding.embed_pending(conf, limit=EMBED_PER_RUN)
        out["embedded"], out["error"] = res["embedded"], res["error"]
    return out
