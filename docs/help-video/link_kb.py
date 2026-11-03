"""به مقاله‌های اصلی پایگاه دانش پیوند ویدیوی راهنمای مربوط را اضافه می‌کند (اگر نباشد): python docs/help-video/link_kb.py"""
import os
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_TESTING", "1")
import django  # noqa: E402

django.setup()
from core.help import GUIDE_MAP  # noqa: E402

MAP = {
    "account": "create-account", "create": "create-database", "connect": "connection-info", "import": "import-formats",
    "explore": "explorer-overview", "sql": "sql-console", "ready": "osm-data-overview", "analysis": "analysis-tools",
    "backups": "backups-overview", "manage": "install-extension", "publish": "publish-layer-overview",
    "mapbuilder": "map-builder", "maps": "multi-layer-maps", "mapcharts": "map-charts", "mapshow": "map-slides-present",
    "wms": "wms-wfs-qgis-server", "rest": "rest-api-overview", "survey": "survey-overview",
    "gnss": "survey-external-receiver", "surface": "survey-surface-contours", "team": "team-roles",
    "usage": "usage-and-performance", "enterprise": "enterprise-overview", "billing": "plans-overview",
    "support": "support-ticket", "limits": "free-plan-limits", "workspace": "notifications-center",
    "classroom": "classroom-overview", "assistant": "ask-in-persian", "find": "find-features",
}


def fa(n):
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


n = 0
for slug, art in MAP.items():
    g = GUIDE_MAP.get(slug)
    if g is None or not g.has_video:
        continue
    f = next(root.glob(f"kb/content/*/{art}.md"), None)
    if f is None:
        print("مقاله پیدا نشد:", art)
        continue
    s = f.read_text(encoding="utf-8")
    if f"help:{slug}" in s:
        continue
    parts = s.split("---\n", 2)
    mins, secs = divmod(g.seconds, 60)
    dur = f"{fa(mins)} دقیقه" + (f" و {fa(secs)} ثانیه" if secs else "")
    line = f"🎬 **[ویدیوی راهنما: {g.title}](help:{slug})** را ببینید ({dur}، بدون نیاز به صدا)."
    s = "---\n" + re.sub(r"reviewed: .*", "reviewed: 2026-11-01", parts[1]) + "---\n" + line + "\n\n" + parts[2].lstrip("\n")
    f.write_text(s, encoding="utf-8")
    n += 1
print(n, "مقاله به‌روز شد")
